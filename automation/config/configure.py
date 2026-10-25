"""Interactive configuration wizard for config/nextcloud.yaml, settings.yaml
and smtp.yaml - run through `configure.sh` (and by `install.sh`).

Walks through every value of a file. What is already set is offered as the
answer (Enter keeps it), anything not set yet is proposed with its default
and marked "neu" - so the same dialog serves the first install, changing a
single value later, and filling in settings a newer version added
(`--missing` asks only for those). Files are always written complete: every
known key with its current value and a German comment saying what it is
for, also the optional sections (switched off with `enabled: false`), so
the file itself documents what can be set. Keys this wizard doesn't know
are kept unchanged at the end of the file. The previous file is saved as
`<name>.yaml.bak`.

The `config/*.example.yaml` templates are generated from the same schema
(`--write-examples`, checked by automation/tests/test_configure.py), so the
templates, the wizard and the defaults can't drift apart. The defaults
themselves must match what automation/config/settings.py,
adapters/smtp_config.py and website/src/Config.php fall back to.

Other usage: `--get settings.public_url` prints one value (for install.sh).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets as _secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from automation.config.settings import REPO_ROOT

CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Field:
    key: str
    prompt: str  # short German question
    help: tuple = ()  # comment lines, written above the key and shown in the dialog
    kind: str = "str"  # str | int | float | bool | choice | secret
    default: Any = None
    choices: tuple = ()
    required: bool = False  # may not be left empty
    optional: bool = False  # "-" clears it (written as null)
    example: Any = None  # value for the *.example.yaml if not the default
    check: Optional[Callable[[Any], Optional[str]]] = None  # -> error text or None
    generate: Optional[Callable[[], Any]] = None  # proposal when the value is empty


@dataclass(frozen=True)
class Section:
    """A nested mapping that is switched on/off with its first field,
    `enabled` (e.g. webhooks). Written even when off, so it's documented."""

    key: str
    help: tuple
    fields: tuple


def _check_url(value: Any) -> Optional[str]:
    if value and not re.match(r"^https?://[^/\s]+", str(value)):
        return "Bitte eine vollständige Adresse mit http:// oder https:// angeben."
    return None


def _check_email(value: Any) -> Optional[str]:
    if value and not re.match(r"^[^@\s]+@[^@\s]+$", str(value)):
        return "Das sieht nicht wie eine E-Mail-Adresse aus."
    return None


def _check_emails(value: Any) -> Optional[str]:
    from automation.adapters.smtp_config import parse_recipients

    try:
        parse_recipients(value)
    except ValueError as exc:
        return f"{exc} - mehrere Adressen mit Komma trennen."
    return None


def _check_timezone(value: Any) -> Optional[str]:
    if not re.match(r"^[A-Za-z_]+(/[A-Za-z0-9_+\-]+)*$", str(value)):
        return "Bitte eine Zeitzone wie Europe/Berlin angeben."
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+, needs the system's tz database

        ZoneInfo(str(value))
    except ImportError:
        pass
    except Exception:
        return f"Unbekannte Zeitzone '{value}'."
    return None


def _check_positive(value: Any) -> Optional[str]:
    return None if value is None or value > 0 else "Bitte eine Zahl größer als 0 angeben."


MIN_WEBHOOK_SECRET_LENGTH = 24  # keep equal to Config::MIN_WEBHOOK_SECRET_LENGTH in website/src/Config.php


def _check_webhook_secret(value: Any) -> Optional[str]:
    text = str(value)
    if text.upper().startswith("CHANGE_ME"):
        return "Das ist der Platzhalter aus der Vorlage - ein eigenes, zufälliges Secret verwenden."
    if len(text) < MIN_WEBHOOK_SECRET_LENGTH:
        return f"Zu kurz - mindestens {MIN_WEBHOOK_SECRET_LENGTH} Zeichen."
    return None


def _check_instance_name(value: Any) -> Optional[str]:
    if not re.match(r"^[A-Za-z0-9_\-]+$", str(value)):
        return "Nur Buchstaben, Ziffern, _ und - (der Name steht in jedem Workflow als nextcloud_instance)."
    return None


SETTINGS_HEADER = (
    "Allgemeine Einstellungen von Nextcloud Deck Workflows (Automation und Website).",
    "Erzeugt von configure.sh - erneut ausführen, um Werte zu ändern oder neue zu ergänzen.",
    "Relative Pfade gelten ab dem Projektordner.",
)

SETTINGS = (
    Field("workflows_dir", "Ordner mit den Workflow-Dateien", (
        "Ordner mit den Workflow-Dateien (*.yaml, auch in Unterordnern).",
    ), default="workflows", required=True),
    Field("state_db_path", "Datei für den gespeicherten Zustand", (
        "SQLite-Datei mit dem Zustand der Automation (gesehene Karten, Historie, Links ...).",
    ), default="automation/var/state.sqlite3", required=True),
    Field("log_level", "Wie ausführlich protokolliert wird", (
        "Wie ausführlich automation/var/automation.log schreibt: DEBUG, INFO, WARNING oder ERROR.",
    ), kind="choice", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR")),
    Field("timezone", "Zeitzone", (
        "Zeitzone, in der die Website Zeiten anzeigt und Actions Daten schreiben",
        "(z. B. das Ablaufdatum eines Einmal-Links). Gespeichert wird immer in UTC.",
    ), default="Europe/Berlin", required=True, check=_check_timezone),
    Field("public_url", "Öffentliche Adresse des website/-Ordners", (
        "Adresse, unter der der Ordner website/ von außen erreichbar ist, z. B.",
        "https://example.com/nextcloudDeckWorkflows/website - nötig für „Einmal-Link erstellen“",
        "(Links lauten <public_url>/link.php?h=...). Leer = keine Einmal-Links.",
    ), optional=True, example="https://example.com/nextcloudDeckWorkflows/website", check=_check_url),
    Field("max_run_seconds", "Maximale Laufzeit eines Automation-Laufs (Sekunden)", (
        "Ein Lauf pollt und arbeitet Workflows so lange erneut ab, wie der vorige Durchgang",
        "noch etwas ausgelöst hat - und startet nach so vielen Sekunden nichts Neues mehr.",
        "Unter dem Zeitlimit des Hosters für Cron-Jobs halten: STRATO beendet sie nach",
        "15 Minuten (900 s), 600 ist dort sicher.",
    ), kind="int", default=600, check=_check_positive),
    Field("health_stale_minutes", "Ab wie vielen Minuten ohne Lauf die Statusseite Alarm meldet", (
        "So alt darf der letzte Lauf sein, bevor website/health.php „gestoppt“ meldet (HTTP 503).",
        "15 passt zu einem Cron-Job alle paar Minuten; bei stündlichem Cron z. B. 90,",
        "bei täglichem 1560.",
    ), kind="int", default=15, check=_check_positive),
    Field("history_retention_days", "Wie viele Tage die Historie aufbewahrt wird", (
        "Ausführungs-Historie (Historie, Statusseite) wird nach so vielen Tagen gelöscht.",
    ), kind="int", default=90, check=_check_positive),
    Section("error_notifications", (
        "E-Mail, sobald ein Workflow `threshold`-mal hintereinander fehlgeschlagen ist",
        "(und erneut, wenn er sich erholt und wieder so oft fehlschlägt). Nutzt config/smtp.yaml.",
    ), (
        Field("enabled", "Fehler-Benachrichtigung per E-Mail einschalten?", kind="bool", default=False),
        Field("threshold", "Nach wie vielen Fehlschlägen in Folge", kind="int", default=3, check=_check_positive),
        Field("to", "Empfänger-Adresse(n)", ("Mehrere Adressen mit Komma trennen.",), required=True, default="",
              example="admin@example.com", check=_check_emails),
    )),
    Section("webhooks", (
        "Nextcloud (Flow/Webhooks, Admin-Einstellung) ruft website/webhook.php auf, wenn sich",
        "ein Board ändert - dann wird seltener gepollt. Siehe automation/README.md „Webhooks“.",
        "Aufruf: <public_url>/webhook.php?instance=<Instanz>&board_id=<Id> mit dem Header",
        "X-Webhook-Secret: <secret> (das Secret wird nur im Header akzeptiert, nie in der Adresse).",
    ), (
        Field("enabled", "Webhooks einschalten?", kind="bool", default=False),
        Field("secret", "Geheimer Schlüssel (Header X-Webhook-Secret)", (
            f"Mindestens {MIN_WEBHOOK_SECRET_LENGTH} Zeichen, zufällig. Zu kurze oder der Platzhalter werden nicht angenommen.",
        ), required=True, default="", example="CHANGE_ME_TO_A_LONG_RANDOM_STRING",
              generate=lambda: _secrets.token_urlsafe(32), check=_check_webhook_secret),
        Field("require_https", "Webhooks nur über HTTPS annehmen?", (
            "Aus nur für lokale Tests - sonst läge das Secret im Klartext im Netz.",
        ), kind="bool", default=True),
        Field("fallback_poll_minutes", "Ohne Webhook-Ping trotzdem alle so viele Minuten pollen",
              kind="int", default=15, check=_check_positive),
    )),
)

SMTP_HEADER = (
    "SMTP-Server für „E-Mail senden“ und die Fehler-Benachrichtigung.",
    "Erzeugt von configure.sh - erneut ausführen, um Werte zu ändern.",
)

SMTP = (
    Field("host", "SMTP-Server", ("Name des SMTP-Servers.",), required=True, default="", example="smtp.example.com"),
    Field("port", "Port", ("587 für STARTTLS (üblich), 25 ohne Verschlüsselung.",), kind="int", default=587),
    Field("use_tls", "STARTTLS verwenden?", ("Verbindung per STARTTLS verschlüsseln.",), kind="bool", default=True),
    Field("username", "Benutzername (leer = ohne Anmeldung)", ("Anmeldename am SMTP-Server, leer = ohne Anmeldung.",),
          default="", example="workflow-bot@example.com"),
    Field("password", "Passwort", ("Passwort zum Benutzernamen.",), kind="secret", default="", example="CHANGE_ME"),
    Field("from_address", "Absender-Adresse", ("Absender der E-Mails, leer = der Benutzername.",),
          default="", example="workflow-bot@example.com", check=_check_email),
)

NEXTCLOUD_HEADER = (
    "Nextcloud-Instanzen, mit denen die Automation arbeitet - ein Eintrag je Instanz.",
    "Workflows verweisen über `nextcloud_instance` auf den Namen.",
    "Erzeugt von configure.sh - erneut ausführen, um Werte zu ändern oder Instanzen zu ergänzen.",
)

INSTANCE = (
    Field("name", "Name der Instanz", ("Kurzname, auf den Workflows verweisen.",), default="prod",
          required=True, check=_check_instance_name),
    Field("url", "Adresse der Nextcloud", ("Adresse der Nextcloud, z. B. https://cloud.example.com.",),
          required=True, default="", example="https://cloud.example.com", check=_check_url),
    Field("username", "Benutzername", ("Nextcloud-Benutzer, als der die Automation arbeitet.",),
          required=True, default="", example="workflow-bot"),
    Field("app_password", "App-Passwort", (
        "App-Passwort (Nextcloud: Einstellungen > Sicherheit > App-Passwörter).",
        "Statt dessen geht auch encrypted_app_password, siehe automation/config/secrets.py.",
    ), kind="secret", required=True, default="", example="CHANGE_ME"),
)

FILES = ("nextcloud", "settings", "smtp")


# -- dialog --------------------------------------------------------------------

class ConsoleIO:
    def say(self, text: str = "") -> None:
        print(text)

    def ask(self, prompt: str) -> str:
        return input(prompt).strip()

    def secret(self, prompt: str) -> str:
        return getpass.getpass(prompt).strip()


_YES = {"j", "ja", "y", "yes", "true", "1", "an", "on"}
_NO = {"n", "nein", "no", "false", "0", "aus", "off"}


def confirm(io: ConsoleIO, question: str, default: bool) -> bool:
    hint = "J/n" if default else "j/N"
    while True:
        answer = io.ask(f"{question} [{hint}]: ").lower()
        if answer == "":
            return default
        if answer in _YES:
            return True
        if answer in _NO:
            return False
        io.say("  Bitte j oder n eingeben.")


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def _display(field: Field, value: Any) -> str:
    if field.kind == "secret":
        return "gesetzt - Enter behält es" if not _is_empty(value) else "leer"
    if field.kind == "bool":
        return "ja" if value else "nein"
    if _is_empty(value):
        return "leer"
    return str(value)


def _parse(field: Field, raw: str) -> Any:
    """Raises ValueError with a German message for an unusable answer."""

    if field.kind == "int":
        try:
            return int(raw)
        except ValueError:
            raise ValueError("Bitte eine ganze Zahl eingeben.") from None
    if field.kind == "float":
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            raise ValueError("Bitte eine Zahl eingeben.") from None
    if field.kind == "bool":
        if raw.lower() in _YES:
            return True
        if raw.lower() in _NO:
            return False
        raise ValueError("Bitte j oder n eingeben.")
    if field.kind == "choice":
        for choice in field.choices:
            if raw.lower() == str(choice).lower():
                return choice
        raise ValueError("Erlaubt: " + ", ".join(str(c) for c in field.choices))
    return raw


def ask_field(io: ConsoleIO, field: Field, value: Any, is_new: bool, indent: str = "") -> Any:
    io.say()
    io.say(f"{indent}{field.key} - {field.prompt}" + ("   [NEU]" if is_new else ""))
    for line in field.help:
        io.say(f"{indent}  {line}")
    if field.choices:
        io.say(f"{indent}  Möglich: " + ", ".join(str(c) for c in field.choices))
    if _is_empty(value) and field.generate is not None:
        value = field.generate()
        io.say(f"{indent}  Vorschlag (neu erzeugt): {value}")
    hint = ("Standard: " if is_new else "") + _display(field, value)
    if field.optional:
        hint += "; - = leeren"
    while True:
        prompt = f"{indent}  Wert [{hint}]: "
        raw = io.secret(prompt) if field.kind == "secret" else io.ask(prompt)
        if raw == "":
            candidate = value
        elif raw == "-" and field.optional:
            candidate = None
        else:
            try:
                candidate = _parse(field, raw)
            except ValueError as exc:
                io.say(f"{indent}  {exc}")
                continue
        if field.required and _is_empty(candidate):
            io.say(f"{indent}  Dieser Wert ist nötig.")
            continue
        error = field.check(candidate) if field.check is not None and not _is_empty(candidate) else None
        if error:
            io.say(f"{indent}  {error}")
            continue
        return candidate


def configure_fields(io: ConsoleIO, fields: tuple, current: dict, only_missing: bool, indent: str = "") -> dict:
    result: dict = {}
    for item in fields:
        if isinstance(item, Section):
            existing = current.get(item.key)
            result[item.key] = _configure_section(io, item, existing if isinstance(existing, dict) else None,
                                                  only_missing, indent)
            continue
        present = item.key in current
        value = current[item.key] if present else item.default
        if only_missing and present:
            result[item.key] = value
        else:
            result[item.key] = ask_field(io, item, value, not present, indent)
    return result


def _configure_section(io: ConsoleIO, section: Section, current: Optional[dict], only_missing: bool, indent: str) -> dict:
    enabled_field, *other_fields = section.fields
    current = current or {}
    present = bool(current)
    result: dict = {}
    if only_missing and present and all(field.key in current for field in section.fields):
        return {field.key: current[field.key] for field in section.fields}
    io.say()
    io.say(f"{indent}== {section.key}" + ("" if present else "   [NEU]"))
    for line in section.help:
        io.say(f"{indent}  {line}")
    # An existing section without `enabled` counts as on - same as the loaders.
    enabled_value = bool(current.get("enabled", True)) if present else enabled_field.default
    result["enabled"] = ask_field(io, enabled_field, enabled_value, "enabled" not in current, indent + "  ")
    for field in other_fields:
        field_present = field.key in current
        value = current[field.key] if field_present else field.default
        if result["enabled"] and not (only_missing and field_present):
            result[field.key] = ask_field(io, field, value, not field_present, indent + "  ")
        else:
            result[field.key] = value  # switched off: kept / documented, not asked
    return result


def _workflows_using(instance_name: str) -> int:
    settings_file = _read(CONFIG_DIR / "settings.yaml") or {}
    workflows_dir = REPO_ROOT / str(settings_file.get("workflows_dir") or "workflows")
    count = 0
    for path in workflows_dir.rglob("*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(data, dict) and data.get("nextcloud_instance") == instance_name:
            count += 1
    return count


def configure_nextcloud(io: ConsoleIO, current: dict, only_missing: bool) -> dict:
    existing = [entry for entry in (current.get("instances") or []) if isinstance(entry, dict)]
    instances = []
    if existing:
        io.say("Vorhandene Instanzen: " + ", ".join(f"{e.get('name')} ({e.get('url')})" for e in existing))
    for entry in existing:
        io.say()
        io.say(f"-- Instanz „{entry.get('name')}“")
        updated = _configure_instance(io, entry, only_missing)
        old_name = entry.get("name")
        if old_name and updated["name"] != old_name:
            used = _workflows_using(old_name)
            if used:
                io.say(f"  Achtung: {used} Workflow(s) verweisen noch auf „{old_name}“ - dort nextcloud_instance anpassen.")
        instances.append(updated)
    if len(instances) > 1 and not only_missing and confirm(io, "Eine Instanz entfernen?", False):
        names = [entry["name"] for entry in instances]
        name = io.ask("Name der zu entfernenden Instanz (" + ", ".join(names) + "): ")
        if name in names:
            instances = [entry for entry in instances if entry["name"] != name]
            io.say(f"  „{name}“ wird entfernt.")
    if not instances:
        io.say("Noch keine Nextcloud-Instanz eingerichtet - jetzt die erste anlegen:")
        instances.append(_configure_instance(io, {}, False, taken=set()))
    while not only_missing and confirm(io, "Weitere Nextcloud-Instanz hinzufügen?", False):
        instances.append(_configure_instance(io, {}, False, taken={entry["name"] for entry in instances}))
    return {**current, "instances": instances}


def _configure_instance(io: ConsoleIO, entry: dict, only_missing: bool, taken: Optional[set] = None) -> dict:
    result = dict(entry)  # unknown keys (e.g. encrypted_app_password) stay
    encrypted = "encrypted_app_password" in entry and "app_password" not in entry
    for field in INSTANCE:
        if field.key == "app_password" and encrypted:
            io.say()
            io.say("  app_password - App-Passwort: verschlüsselt gespeichert (encrypted_app_password).")
            new = io.secret("  Neues App-Passwort [Enter behält das gespeicherte]: ")
            if new:
                encrypted_value = _try_encrypt(new)
                if encrypted_value:
                    result["encrypted_app_password"] = encrypted_value
                else:
                    io.say("  Verschlüsseln nicht möglich (cryptography/config/secret.key fehlt) - wird als app_password gespeichert.")
                    result.pop("encrypted_app_password", None)
                    result["app_password"] = new
            continue
        present = field.key in entry
        value = entry[field.key] if present else field.default
        if only_missing and present:
            continue
        while True:
            answer = ask_field(io, field, value, not present, "  ")
            if field.key == "name" and taken is not None and answer in taken:
                io.say("  Diesen Namen gibt es schon.")
                continue
            break
        result[field.key] = answer
    return result


def _try_encrypt(plaintext: str) -> Optional[str]:
    try:
        from automation.config import secrets as config_secrets

        return config_secrets.encrypt(plaintext)
    except Exception:
        return None


# -- writing -------------------------------------------------------------------

def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar
    return json.dumps(value, ensure_ascii=False, default=str)  # lists/dicts as YAML flow style


def _comment(lines: tuple, indent: str) -> list:
    return [f"{indent}# {line}" for line in lines]


def _render_fields(fields: tuple, values: dict, indent: str = "") -> list:
    out: list = []
    for item in fields:
        out.append("")
        if isinstance(item, Section):
            section_values = values.get(item.key) or {}
            out += _comment(item.help, indent)
            out.append(f"{indent}{item.key}:")
            for field in item.fields:
                out += _comment((field.prompt,) + field.help, indent + "  ")
                out.append(f"{indent}  {field.key}: {_scalar(section_values.get(field.key, field.default))}")
            known = {field.key for field in item.fields}
            for key, value in section_values.items():
                if key not in known:
                    out.append(f"{indent}  {key}: {_scalar(value)}")
            continue
        out += _comment(item.help or (item.prompt,), indent)
        out.append(f"{indent}{item.key}: {_scalar(values.get(item.key, item.default))}")
    return out


def _render_extra(values: dict, known: set) -> list:
    extra = {key: value for key, value in values.items() if key not in known}
    if not extra:
        return []
    out = ["", "# Weitere Einträge (configure.sh kennt sie nicht, sie bleiben unverändert):"]
    out += [f"{key}: {_scalar(value)}" for key, value in extra.items()]
    return out


def render(name: str, values: dict) -> str:
    if name == "nextcloud":
        out = _comment(NEXTCLOUD_HEADER, "") + ["", "instances:"]
        known = {field.key for field in INSTANCE} | {"encrypted_app_password"}
        for index, instance in enumerate(values.get("instances") or []):
            if index:
                out.append("")
            for position, field in enumerate(INSTANCE):
                if field.key == "app_password" and "app_password" not in instance and "encrypted_app_password" in instance:
                    out += _comment(("App-Passwort, verschlüsselt (siehe automation/config/secrets.py).",), "    ")
                    out.append(f"    encrypted_app_password: {_scalar(instance['encrypted_app_password'])}")
                    continue
                out += _comment(field.help, "  " if position == 0 else "    ")
                prefix = "  - " if position == 0 else "    "
                out.append(f"{prefix}{field.key}: {_scalar(instance.get(field.key, field.default))}")
            for key, value in instance.items():
                if key not in known:
                    out.append(f"    {key}: {_scalar(value)}")
        out += _render_extra(values, {"instances"})
    else:
        header, fields = (SETTINGS_HEADER, SETTINGS) if name == "settings" else (SMTP_HEADER, SMTP)
        out = _comment(header, "") + _render_fields(fields, values)
        out += _render_extra(values, {item.key for item in fields})
    return "\n".join(out) + "\n"


def _defaults(fields: tuple, examples: bool) -> dict:
    values: dict = {}
    for item in fields:
        if isinstance(item, Section):
            values[item.key] = _defaults(item.fields, examples)
        else:
            values[item.key] = item.example if examples and item.example is not None else item.default
    return values


def example_text(name: str) -> str:
    if name == "nextcloud":
        values = {"instances": [_defaults(INSTANCE, True)]}
    else:
        values = _defaults(SETTINGS if name == "settings" else SMTP, True)
    text = render(name, values)
    return (f"# VORLAGE - die echte config/{name}.yaml erzeugt configure.sh (fragt alle Werte ab).\n"
            f"# Von Hand: als config/{name}.yaml kopieren und anpassen.\n" + text)


def _read(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _flatten(values: Any, prefix: str = "") -> dict:
    if isinstance(values, dict):
        flat: dict = {}
        for key, value in values.items():
            flat.update(_flatten(value, f"{prefix}{key}."))
        return flat
    if isinstance(values, list):
        flat = {}
        for index, value in enumerate(values):
            flat.update(_flatten(value, f"{prefix}{index}."))
        return flat
    return {prefix[:-1]: values}


def _secret_key(key: str) -> bool:
    return key.split(".")[-1] in {"password", "app_password", "encrypted_app_password", "secret"}


def save(io: ConsoleIO, name: str, before: Optional[dict], after: dict, assume_yes: bool = False) -> bool:
    path = CONFIG_DIR / f"{name}.yaml"
    text = render(name, after)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        io.say(f"config/{name}.yaml: unverändert.")
        return False
    old, new = _flatten(before or {}), _flatten(after)
    changes = [key for key in sorted(set(old) | set(new)) if old.get(key) != new.get(key)]
    io.say()
    if before is None:
        io.say(f"config/{name}.yaml wird neu angelegt.")
    elif changes:
        io.say(f"Änderungen in config/{name}.yaml:")
        for key in changes:
            if _secret_key(key):
                io.say(f"  {key}: (geändert)")
            else:
                io.say(f"  {key}: {old.get(key, '–')!s} -> {new.get(key, '–')!s}")
    else:
        io.say(f"config/{name}.yaml: Werte unverändert, Datei wird vervollständigt (Kommentare/neue Standardwerte).")
    if not assume_yes and not confirm(io, f"config/{name}.yaml speichern?", True):
        io.say("  Nicht gespeichert.")
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    mode = None
    if path.exists():
        mode = path.stat().st_mode & 0o777
        backup = CONFIG_DIR / f"{name}.yaml.bak"
        backup.write_bytes(path.read_bytes())
        os.chmod(backup, mode)  # holds the same passwords: not more readable than the original
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)
    io.say("  Gespeichert" + (f" (vorherige Fassung: config/{name}.yaml.bak)." if mode is not None else "."))
    return True


# -- checks after saving ---------------------------------------------------------

def test_nextcloud(io: ConsoleIO, values: dict) -> None:
    try:
        import requests
    except ImportError:
        io.say("  requests fehlt - Verbindungstest übersprungen.")
        return
    for instance in values.get("instances") or []:
        password = instance.get("app_password")
        if not password and instance.get("encrypted_app_password"):
            try:
                from automation.config import secrets as config_secrets

                password = config_secrets.decrypt(instance["encrypted_app_password"])
            except Exception as exc:
                io.say(f"  {instance.get('name')}: Passwort nicht entschlüsselbar ({exc}) - übersprungen.")
                continue
        url = str(instance.get("url") or "").rstrip("/") + "/index.php/apps/deck/api/v1.1/boards"
        try:
            response = requests.get(url, auth=(instance.get("username"), password), timeout=10,
                                    headers={"OCS-APIRequest": "true", "Accept": "application/json"})
            status = response.status_code
        except Exception as exc:
            io.say(f"  {instance.get('name')}: nicht erreichbar ({exc}).")
            continue
        if status == 200:
            io.say(f"  {instance.get('name')}: OK - Deck antwortet ({len(response.json() or [])} Boards sichtbar).")
        elif status == 401:
            io.say(f"  {instance.get('name')}: HTTP 401 - Benutzername oder App-Passwort stimmt nicht.")
        elif status == 404:
            io.say(f"  {instance.get('name')}: HTTP 404 - Adresse falsch oder die Deck-App ist nicht installiert.")
        else:
            io.say(f"  {instance.get('name')}: HTTP {status} - bitte Adresse und Zugangsdaten prüfen.")


def test_smtp(io: ConsoleIO, values: dict) -> None:
    to = io.ask("  Empfänger der Test-Mail: ")
    if not to:
        return
    from automation.adapters.smtp_config import SmtpConfig, send_email

    config = SmtpConfig(
        host=values["host"], port=int(values["port"]), username=values.get("username") or None,
        password=values.get("password") or None, use_tls=bool(values.get("use_tls")),
        from_address=values.get("from_address") or values.get("username"),
    )
    try:
        send_email(config, to=to, subject="Test von Nextcloud Deck Workflows",
                   body="Diese Test-Mail hat configure.sh verschickt - der SMTP-Versand funktioniert.")
        io.say("  Test-Mail verschickt.")
    except Exception as exc:
        io.say(f"  Versand fehlgeschlagen: {exc}")


# -- entry point ---------------------------------------------------------------

def missing_keys(name: str, current: Optional[dict]) -> list:
    """Known keys not yet in the file (for the overview and --missing)."""

    if current is None:
        return []
    if name == "nextcloud":
        return [f"{entry.get('name')}.{field.key}" for entry in current.get("instances") or [] if isinstance(entry, dict)
                for field in INSTANCE
                if field.key not in entry and not (field.key == "app_password" and "encrypted_app_password" in entry)]
    missing = []
    for item in SETTINGS if name == "settings" else SMTP:
        if item.key not in current:
            missing.append(item.key)
        elif isinstance(item, Section) and isinstance(current[item.key], dict):
            missing += [f"{item.key}.{field.key}" for field in item.fields if field.key not in current[item.key]]
    return missing


def run(io: ConsoleIO, names: list, only_missing: bool) -> int:
    io.say("Nextcloud Deck Workflows - Konfiguration")
    io.say("Enter übernimmt den Wert in [Klammern]; Strg+C bricht die aktuelle Datei ohne Speichern ab.")
    io.say()
    currents = {}
    for name in names:
        try:
            currents[name] = _read(CONFIG_DIR / f"{name}.yaml")
        except yaml.YAMLError as exc:
            io.say(f"config/{name}.yaml ist kein gültiges YAML ({exc}).")
            if not confirm(io, "Mit Standardwerten neu aufbauen? (die alte Datei wird als .bak gesichert)", False):
                return 1
            currents[name] = {}
        current = currents[name]
        missing = missing_keys(name, current)
        status = "fehlt noch" if current is None else (f"{len(missing)} neue Werte: " + ", ".join(missing) if missing else "vollständig")
        io.say(f"  config/{name}.yaml: {status}")

    for name in names:
        current = currents[name]
        if only_missing and current is not None and not missing_keys(name, current):
            continue
        io.say()
        io.say(f"=== config/{name}.yaml ===")
        try:
            if name == "smtp" and current is None and not confirm(
                    io, "E-Mail-Versand (send_email, Fehler-Benachrichtigung) einrichten?", False):
                io.say("  Übersprungen - ohne config/smtp.yaml können keine E-Mails verschickt werden.")
                continue
            if name == "nextcloud":
                values = configure_nextcloud(io, current or {}, only_missing and current is not None)
            else:
                fields = SETTINGS if name == "settings" else SMTP
                values = configure_fields(io, fields, current or {}, only_missing and current is not None)
                values.update({key: value for key, value in (current or {}).items() if key not in values})
            save(io, name, current, values)
        except (KeyboardInterrupt, EOFError):
            io.say()
            io.say(f"  Abgebrochen - config/{name}.yaml bleibt unverändert.")
            continue
        try:
            if name == "nextcloud" and confirm(io, "Verbindung zu Nextcloud jetzt testen?", True):
                test_nextcloud(io, values)
            if name == "smtp" and confirm(io, "Test-Mail verschicken?", False):
                test_smtp(io, values)
            if name == "settings":
                if values.get("error_notifications", {}).get("enabled") and not (CONFIG_DIR / "smtp.yaml").exists() \
                        and "smtp" not in names:
                    io.say("  Hinweis: Fehler-Benachrichtigungen brauchen config/smtp.yaml (./configure.sh smtp).")
                if values.get("webhooks", {}).get("enabled"):
                    base = values.get("public_url") or "<public_url>"
                    io.say(f"  In Nextclouds Webhook-Einstellungen eintragen: {base}/webhook.php?instance=<Instanz>&board_id=<Id>")
                    io.say(f"  und den Header  X-Webhook-Secret: {values['webhooks']['secret']}")
        except (KeyboardInterrupt, EOFError):
            io.say()
    io.say()
    io.say("Fertig. Später erneut: ./configure.sh (alles), ./configure.sh settings (eine Datei),")
    io.say("./configure.sh --missing (nur Werte, die eine neue Version hinzugefügt hat).")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="configure.sh", description="Konfiguration von Nextcloud Deck Workflows")
    parser.add_argument("files", nargs="*",
                        help="nur diese Dateien: nextcloud, settings, smtp (Standard: alle)")
    parser.add_argument("--missing", action="store_true", help="nur Werte abfragen, die noch fehlen")
    parser.add_argument("--get", metavar="DATEI.SCHLÜSSEL", help="einen Wert ausgeben, z. B. settings.public_url")
    parser.add_argument("--write-examples", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.write_examples:
        for name in FILES:
            (CONFIG_DIR / f"{name}.example.yaml").write_text(example_text(name), encoding="utf-8")
        return 0
    if args.get:
        name, _, key = args.get.partition(".")
        value: Any = _read(CONFIG_DIR / f"{name}.yaml") or {}
        for part in key.split(".") if key else []:
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            print(value)
        return 0
    unknown = [name for name in args.files if name not in FILES]
    if unknown:
        parser.error("unbekannte Datei: " + ", ".join(unknown) + " (möglich: " + ", ".join(FILES) + ")")
    return run(ConsoleIO(), args.files or list(FILES), args.missing)


if __name__ == "__main__":
    sys.exit(main())
