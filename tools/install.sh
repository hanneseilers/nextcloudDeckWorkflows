#!/usr/bin/env bash
#
# Guided installer - run this ON THE SERVER, inside the uploaded project
# directory (where automation/, website/, config/, workflows/ are siblings
# of this script).
#
# Walks through: environment checks, PHP/Python dependencies, an interactive
# config wizard (config/*.yaml from the *.example.yaml templates), optional
# HTTP Basic Auth for website/, writable-directory checks, a cron hint, and
# a final verification pass.
#
# Deliberately no `set -e`: a single missing optional tool (composer, zip,
# openssl, crontab) must not abort the whole guided flow. Every step checks
# its own preconditions and reports clearly instead of dying, except for the
# few genuinely fatal problems checked right at the start.

set -u
set -o pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

CONFIG_DIR="$PROJECT_ROOT/config"
AUTOMATION_DIR="$PROJECT_ROOT/automation"
WEBSITE_DIR="$PROJECT_ROOT/website"
WORKFLOWS_DIR="$PROJECT_ROOT/workflows"

PYTHON_BIN="python3"
ENTERED_NEXTCLOUD_URL=""
ENTERED_NEXTCLOUD_USER=""
ENTERED_NEXTCLOUD_PASS=""

WARNINGS=()
TODO=()

log()  { printf '\n==> %s\n' "$1"; }
info() { printf '    %s\n' "$1"; }
warn() { printf 'WARNUNG: %s\n' "$1" >&2; WARNINGS+=("$1"); }
die()  { printf 'FEHLER: %s\n' "$1" >&2; exit 1; }
note_todo() { TODO+=("$1"); }

yaml_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# ask "Frage" ["Default"] -> gibt die Antwort (oder den Default) auf stdout aus.
# Prompt geht explizit nach stderr, damit `var=$(ask ...)` sauber nur die
# Antwort einsammelt.
ask() {
    local prompt="$1" default="${2:-}" answer
    if [ -n "$default" ]; then
        printf '%s [%s]: ' "$prompt" "$default" >&2
    else
        printf '%s: ' "$prompt" >&2
    fi
    read -r answer
    echo "${answer:-$default}"
}

ask_secret() {
    local prompt="$1" answer
    printf '%s: ' "$prompt" >&2
    read -r -s answer
    printf '\n' >&2
    echo "$answer"
}

# confirm "Frage" [j|n] -> Exit-Code 0 = ja
confirm() {
    local prompt="$1" default="${2:-n}" answer hint="j/N"
    [ "$default" = "j" ] && hint="J/n"
    printf '%s [%s]: ' "$prompt" "$hint" >&2
    read -r answer
    answer="${answer:-$default}"
    case "$answer" in
        j|J|y|Y|ja|Ja|yes|Yes) return 0 ;;
        *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------

section_env_checks() {
    log "1/8 Umgebungs-Check"

    if command -v php >/dev/null 2>&1; then
        info "PHP: $(php -r 'echo PHP_VERSION;' 2>/dev/null)"
        local ext
        for ext in curl mbstring; do
            if php -m 2>/dev/null | grep -qi "^${ext}\$"; then
                info "PHP-Extension '$ext': vorhanden"
            else
                warn "PHP-Extension '$ext' fehlt - website/ funktioniert damit evtl. nicht."
            fi
        done
    else
        warn "php wurde nicht gefunden - die Website kann so nicht laufen."
    fi

    if command -v composer >/dev/null 2>&1; then
        info "Composer: $(composer --version 2>/dev/null | head -1)"
    else
        info "Composer: nicht gefunden"
    fi

    if command -v python3 >/dev/null 2>&1; then
        info "Python: $(python3 --version 2>&1)"
    else
        warn "python3 wurde nicht gefunden - die Automation kann so nicht laufen."
    fi

    command -v pip3 >/dev/null 2>&1 && info "pip3: vorhanden" || warn "pip3 wurde nicht gefunden."
    command -v crontab >/dev/null 2>&1 && info "crontab: vorhanden" || info "crontab: nicht gefunden (Cron muss anders eingerichtet werden)"
}

section_php_deps() {
    log "2/8 PHP-Abhängigkeiten"

    if [ -f "$WEBSITE_DIR/vendor/autoload.php" ]; then
        info "website/vendor/ ist bereits vorhanden - nichts zu tun."
        return
    fi

    if command -v composer >/dev/null 2>&1; then
        info "Installiere PHP-Abhängigkeiten (composer install --no-dev) ..."
        if (cd "$WEBSITE_DIR" && composer install --no-dev --optimize-autoloader --no-interaction); then
            info "website/vendor/ erfolgreich installiert."
        else
            warn "composer install ist fehlgeschlagen."
            note_todo "PHP-Abhängigkeiten manuell installieren: cd website && composer install --no-dev"
        fi
    else
        warn "composer ist nicht installiert - website/vendor/ fehlt."
        note_todo "Composer lokal installieren, 'composer install --no-dev' im website/-Ordner ausführen und den vendor/-Ordner hochladen."
    fi
}

section_python_deps() {
    log "3/8 Python-Abhängigkeiten"

    if ! command -v python3 >/dev/null 2>&1; then
        warn "python3 fehlt - Schritt übersprungen."
        note_todo "python3 installieren, dann 'pip3 install -r automation/requirements.txt' ausführen."
        return
    fi

    local made_venv="n"
    if [ -x "$AUTOMATION_DIR/.venv/bin/python" ]; then
        info "automation/.venv existiert bereits."
        made_venv="j"
    elif confirm "Virtuelle Umgebung (automation/.venv) anlegen? (empfohlen)" "j"; then
        if python3 -m venv "$AUTOMATION_DIR/.venv"; then
            info "venv angelegt."
            made_venv="j"
        else
            warn "venv konnte nicht angelegt werden - installiere stattdessen für den aktuellen Nutzer (pip install --user)."
        fi
    fi

    if [ "$made_venv" = "j" ]; then
        info "Installiere Pakete in automation/.venv ..."
        if "$AUTOMATION_DIR/.venv/bin/pip" install -q -r "$AUTOMATION_DIR/requirements.txt"; then
            info "Erfolgreich installiert."
            PYTHON_BIN="$AUTOMATION_DIR/.venv/bin/python"
        else
            warn "pip install im venv ist fehlgeschlagen."
            note_todo "Python-Abhängigkeiten manuell installieren: automation/.venv/bin/pip install -r automation/requirements.txt"
        fi
    else
        info "Installiere Pakete für den aktuellen Nutzer (pip3 install --user) ..."
        if command -v pip3 >/dev/null 2>&1 && pip3 install -q --user -r "$AUTOMATION_DIR/requirements.txt"; then
            info "Erfolgreich installiert."
        else
            warn "pip3 install --user ist fehlgeschlagen oder pip3 fehlt."
            note_todo "Python-Abhängigkeiten manuell installieren: pip3 install --user -r automation/requirements.txt"
        fi
    fi
}

section_config_nextcloud() {
    local target="$CONFIG_DIR/nextcloud.yaml"

    if [ -f "$target" ] && ! confirm "config/nextcloud.yaml existiert bereits - überschreiben?" "n"; then
        info "config/nextcloud.yaml bleibt unverändert."
        return
    fi

    echo "instances:" > "$target"
    local more="j" name url user pass
    while [ "$more" = "j" ]; do
        name="$(ask "Name der Instanz (z.B. prod)" "prod")"
        url="$(ask "Nextcloud-URL (z.B. https://cloud.example.com)" "")"
        user="$(ask "Benutzername" "")"
        pass="$(ask_secret "App-Passwort (Nextcloud Einstellungen > Sicherheit)")"
        {
            echo "  - name: $(yaml_escape "$name")"
            echo "    url: \"$(yaml_escape "$url")\""
            echo "    username: \"$(yaml_escape "$user")\""
            echo "    app_password: \"$(yaml_escape "$pass")\""
        } >> "$target"

        ENTERED_NEXTCLOUD_URL="$url"
        ENTERED_NEXTCLOUD_USER="$user"
        ENTERED_NEXTCLOUD_PASS="$pass"

        if confirm "Weitere Nextcloud-Instanz hinzufügen?" "n"; then
            more="j"
        else
            more="n"
        fi
    done
    info "config/nextcloud.yaml geschrieben."
}

section_config_settings() {
    local target="$CONFIG_DIR/settings.yaml"
    if [ -f "$target" ] && ! confirm "config/settings.yaml existiert bereits - überschreiben?" "n"; then
        info "config/settings.yaml bleibt unverändert."
        return
    fi

    local workflows_dir log_level
    workflows_dir="$(ask "workflows_dir (relativ zum Projekt-Root)" "workflows")"
    log_level="$(ask "log_level (DEBUG/INFO/WARNING/ERROR)" "INFO")"

    {
        echo "workflows_dir: $(yaml_escape "$workflows_dir")"
        echo "state_db_path: automation/var/state.sqlite3"
        echo "log_level: $(yaml_escape "$log_level")"
    } > "$target"
    info "config/settings.yaml geschrieben."
}

section_config_smtp() {
    local target="$CONFIG_DIR/smtp.yaml"

    if [ -f "$target" ]; then
        if ! confirm "config/smtp.yaml existiert bereits - überschreiben?" "n"; then
            info "config/smtp.yaml bleibt unverändert."
            return
        fi
    elif ! confirm "E-Mail-Versand (send_email-Action) jetzt einrichten?" "n"; then
        info "config/smtp.yaml wird übersprungen."
        note_todo "Falls gewünscht: config/smtp.yaml aus config/smtp.example.yaml anlegen (für die send_email-Action)."
        return
    fi

    local host port user pass from
    host="$(ask "SMTP-Host" "smtp.example.com")"
    port="$(ask "SMTP-Port" "587")"
    user="$(ask "SMTP-Benutzername (leer = kein Login)" "")"
    pass=""
    [ -n "$user" ] && pass="$(ask_secret "SMTP-Passwort")"
    from="$(ask "Absenderadresse" "${user:-noreply@example.com}")"

    local use_tls="true"
    confirm "STARTTLS verwenden?" "j" || use_tls="false"

    {
        echo "host: $(yaml_escape "$host")"
        echo "port: $port"
        if [ -n "$user" ]; then echo "username: \"$(yaml_escape "$user")\""; else echo "username: null"; fi
        if [ -n "$pass" ]; then echo "password: \"$(yaml_escape "$pass")\""; else echo "password: null"; fi
        echo "use_tls: $use_tls"
        echo "from_address: \"$(yaml_escape "$from")\""
    } > "$target"
    info "config/smtp.yaml geschrieben."
}

section_website_protection() {
    log "5/8 Zugriffsschutz für website/"

    if [ -f "$WEBSITE_DIR/.htaccess" ]; then
        info "website/.htaccess existiert bereits - wird nicht verändert."
        return
    fi

    if ! confirm "HTTP-Basic-Auth für website/ jetzt einrichten? (empfohlen - es gibt kein eigenes Login)" "j"; then
        warn "website/ bleibt ungeschützt - jede/r mit der URL kann Workflows anlegen/löschen!"
        note_todo "website/ unbedingt extern schützen (z.B. .htaccess Basic-Auth oder Passwortschutz der Hosting-Verwaltung)."
        return
    fi

    if ! command -v openssl >/dev/null 2>&1; then
        warn "openssl fehlt - Passwort kann nicht gehasht werden, Zugriffsschutz wird übersprungen."
        note_todo "website/ manuell schützen (z.B. über die Hosting-Verwaltung)."
        return
    fi

    local user pass hash htpasswd_path
    user="$(ask "Benutzername" "admin")"
    pass="$(ask_secret "Passwort")"
    hash="$(openssl passwd -apr1 "$pass" 2>/dev/null)"
    if [ -z "$hash" ]; then
        warn "Passwort-Hash konnte nicht erzeugt werden - Zugriffsschutz wird übersprungen."
        note_todo "website/ manuell schützen (z.B. über die Hosting-Verwaltung)."
        return
    fi
    htpasswd_path="$WEBSITE_DIR/.htpasswd"

    printf '%s:%s\n' "$user" "$hash" > "$htpasswd_path"
    chmod 600 "$htpasswd_path"

    cat > "$WEBSITE_DIR/.htaccess" <<EOF
# Erzeugt von tools/install.sh. Setzt Apache mit AllowOverride voraus.
# Apache 2.2: zusätzlich "Order deny,allow" und "Deny from all" nötig.
AuthType Basic
AuthName "Nextcloud Deck Workflows"
AuthUserFile $htpasswd_path
Require valid-user
EOF

    info "website/.htaccess + .htpasswd angelegt (Benutzer: $user)."
    note_todo "Falls der Webserver nginx (statt Apache) ist: Zugriffsschutz dort separat einrichten, .htaccess wird von nginx ignoriert."
}

section_writable_checks() {
    log "6/8 Schreibrechte-Check"

    mkdir -p "$AUTOMATION_DIR/var" "$WORKFLOWS_DIR"

    local dir testfile
    for dir in "$AUTOMATION_DIR/var" "$WORKFLOWS_DIR"; do
        testfile="$dir/.install_write_test"
        if ( touch "$testfile" 2>/dev/null && rm -f "$testfile" 2>/dev/null ); then
            info "$dir ist beschreibbar."
        else
            warn "$dir ist NICHT beschreibbar."
            note_todo "Schreibrechte für $dir setzen (z.B. chmod 775 '$dir')."
        fi
    done
}

section_cron() {
    log "7/8 Cron-Job"

    local cron_entry="*/5 * * * * cd $PROJECT_ROOT && $PYTHON_BIN -m automation.main >> $AUTOMATION_DIR/var/cron.log 2>&1"

    info "Empfohlene Cron-Zeile (alle 5 Minuten):"
    info "  $cron_entry"

    if ! command -v crontab >/dev/null 2>&1; then
        warn "crontab ist auf diesem System nicht verfügbar."
        note_todo "Cron-Job über die Hosting-Verwaltung einrichten: $cron_entry"
        return
    fi

    if confirm "Jetzt automatisch zur Crontab hinzufügen?" "n"; then
        if (crontab -l 2>/dev/null; echo "$cron_entry") | crontab -; then
            info "Cron-Job eingetragen."
        else
            warn "Eintragen in die Crontab ist fehlgeschlagen."
            note_todo "Cron-Job manuell eintragen (crontab -e): $cron_entry"
        fi
    else
        note_todo "Cron-Job manuell eintragen (crontab -e): $cron_entry"
    fi
}

section_verification() {
    log "8/8 Verifikation"

    if command -v php >/dev/null 2>&1; then
        local php_errors=0 file
        while IFS= read -r -d '' file; do
            if ! php -l "$file" >/dev/null 2>&1; then
                warn "PHP-Syntaxfehler in $file"
                php_errors=$((php_errors + 1))
            fi
        done < <(find "$WEBSITE_DIR" -name '*.php' -not -path '*/vendor/*' -print0)
        [ "$php_errors" -eq 0 ] && info "Alle PHP-Dateien syntaktisch OK." || warn "$php_errors PHP-Datei(en) mit Syntaxfehlern (siehe oben)."
    else
        warn "php fehlt - PHP-Syntaxcheck übersprungen."
    fi

    if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        local err_file="$AUTOMATION_DIR/var/.install_check_err"

        info "Prüfe Modul-Liste (--list-modules) ..."
        if "$PYTHON_BIN" -m automation.main --list-modules >/dev/null 2>"$err_file"; then
            info "OK."
        else
            warn "'--list-modules' ist fehlgeschlagen: $(cat "$err_file" 2>/dev/null)"
        fi

        info "Prüfe Dry-Run (--dry-run) ..."
        if "$PYTHON_BIN" -m automation.main --dry-run >/dev/null 2>"$err_file"; then
            info "OK."
        else
            warn "'--dry-run' ist fehlgeschlagen: $(cat "$err_file" 2>/dev/null)"
        fi
        rm -f "$err_file"
    else
        warn "Python-Interpreter '$PYTHON_BIN' nicht ausführbar - Verifikation übersprungen."
    fi

    if [ -n "$ENTERED_NEXTCLOUD_URL" ] && command -v curl >/dev/null 2>&1; then
        info "Teste Verbindung zu $ENTERED_NEXTCLOUD_URL ..."
        local code
        code="$(curl -s -o /dev/null -w '%{http_code}' \
            -u "$ENTERED_NEXTCLOUD_USER:$ENTERED_NEXTCLOUD_PASS" \
            -H 'OCS-APIRequest: true' \
            --max-time 10 \
            "$ENTERED_NEXTCLOUD_URL/index.php/apps/deck/api/v1.1/boards" 2>/dev/null)"
        if [ "$code" = "200" ]; then
            info "Nextcloud-Verbindung OK (HTTP 200)."
        else
            warn "Nextcloud-Verbindung lieferte HTTP ${code:-?} - URL/Zugangsdaten in config/nextcloud.yaml prüfen."
        fi
    fi
}

main() {
    echo "Nextcloud Deck Workflows - Installation"

    [ -d "$AUTOMATION_DIR" ] && [ -d "$WEBSITE_DIR" ] && [ -d "$CONFIG_DIR" ] || \
        die "automation/, website/ oder config/ fehlen - bitte im entpackten Projekt-Wurzelverzeichnis ausführen."

    if [ -f "$PROJECT_ROOT/BUILD_INFO.txt" ]; then
        echo "---"
        cat "$PROJECT_ROOT/BUILD_INFO.txt"
        echo "---"
    fi

    section_env_checks
    section_php_deps
    section_python_deps

    log "4/8 Konfiguration"
    section_config_nextcloud
    section_config_settings
    section_config_smtp

    section_website_protection
    section_writable_checks
    section_cron
    section_verification

    echo
    echo "=== Zusammenfassung ==="
    if [ "${#WARNINGS[@]}" -eq 0 ]; then
        echo "Keine Probleme festgestellt."
    else
        echo "Warnungen:"
        local w
        for w in "${WARNINGS[@]}"; do echo "  - $w"; done
    fi
    if [ "${#TODO[@]}" -gt 0 ]; then
        echo
        echo "Noch zu erledigen:"
        local t
        for t in "${TODO[@]}"; do echo "  - $t"; done
    fi
    echo
    echo "Fertig. Workflows lassen sich jetzt über website/ anlegen; automation/main.py läuft über den Cron-Job."
}

main "$@"
