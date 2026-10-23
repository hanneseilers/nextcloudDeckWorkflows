#!/usr/bin/env bash
#
# Prüft auf dem Webspace (per SSH ausführen), ob die Voraussetzungen für
# Nextcloud Deck Workflows erfüllt sind - bevor oder nach dem Hochladen.
# Ändert nichts dauerhaft: alle Testdateien werden wieder entfernt.
#
#   ./check_server.sh [Optionen]
#
#   --project-dir DIR      Projektverzeichnis (Standard: Verzeichnis dieses Skripts
#                          bzw. dessen übergeordnetes, wenn es in tools/ liegt)
#   --nextcloud-url URL    Nextcloud-Adresse prüfen (Erreichbarkeit, Version, Uhrzeit)
#   --web-url URL          Öffentliche Adresse von website/ - legt kurz eine
#                          Prüfseite an, ruft sie über den Webserver ab und löscht
#                          sie wieder (PHP des Webservers, Zugriffsschutz)
#   --php BIN / --python BIN   bestimmte Programme statt der gefundenen verwenden
#   --no-network           alle Netzwerk-Tests auslassen
#   -h | --help
#
# Exit-Code: 0 = keine Fehler (Warnungen möglich), 1 = mindestens ein Fehler.

set -u

MIN_PHP="8.2"      # symfony/yaml 7.4 (website/composer.lock) braucht PHP >= 8.2
MIN_PYTHON="3.9"
MIN_SQLITE="3.24.0" # ON CONFLICT ... DO UPDATE (Upserts) in Python und PHP
CRON_LIMIT_HINT=900 # STRATO beendet Cron-Jobs nach 15 Minuten

PROJECT_DIR=""
NEXTCLOUD_URL=""
WEB_URL=""
PHP_BIN=""
PYTHON_BIN=""
NETWORK=1

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
FAILS=()
WARNS=()
CLEANUP=()

section() { printf '\n== %s ==\n' "$1"; }
pass() { printf '  [OK]      %s\n' "$1"; PASS_COUNT=$((PASS_COUNT + 1)); }
warn() { printf '  [WARNUNG] %s\n' "$1"; WARN_COUNT=$((WARN_COUNT + 1)); WARNS+=("$1"); }
fail() { printf '  [FEHLER]  %s\n' "$1"; FAIL_COUNT=$((FAIL_COUNT + 1)); FAILS+=("$1"); }
info() { printf '  [INFO]    %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

cleanup() {
    local path
    for path in "${CLEANUP[@]+"${CLEANUP[@]}"}"; do
        rm -rf -- "$path" 2>/dev/null
    done
}
trap cleanup EXIT
trap 'exit 130' INT TERM

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --project-dir) PROJECT_DIR="${2:-}"; shift 2 ;;
        --nextcloud-url) NEXTCLOUD_URL="${2:-}"; shift 2 ;;
        --web-url) WEB_URL="${2:-}"; shift 2 ;;
        --php) PHP_BIN="${2:-}"; shift 2 ;;
        --python) PYTHON_BIN="${2:-}"; shift 2 ;;
        --no-network) NETWORK=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unbekannte Option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -z "$PROJECT_DIR" ]; then
    PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    case "$PROJECT_DIR" in */tools) PROJECT_DIR="$(dirname "$PROJECT_DIR")" ;; esac
fi
if [ ! -d "$PROJECT_DIR" ]; then
    printf 'Projektverzeichnis %s existiert nicht.\n' "$PROJECT_DIR" >&2
    exit 2
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

# "a.b.c" >= "x.y.z"?
version_ge() {
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]
}

# --------------------------------------------------------------------------
section "System"

info "Host: $(uname -n 2>/dev/null) - $(uname -srm 2>/dev/null)"
if [ -r /etc/os-release ]; then
    info "Betriebssystem: $(. /etc/os-release && printf '%s' "${PRETTY_NAME:-unbekannt}")"
fi
info "Benutzer: $(id -un 2>/dev/null) (uid $(id -u 2>/dev/null)), Shell: ${SHELL:-?}, umask $(umask)"
info "Projektverzeichnis: $PROJECT_DIR"
info "Uhrzeit lokal: $(date '+%Y-%m-%d %H:%M:%S %Z (%z)'), UTC: $(date -u '+%Y-%m-%d %H:%M:%S')"

case "$PROJECT_DIR" in
    /mnt/web*|*/strato*) info "Sieht nach STRATO-Webspace aus: Cron-Jobs laufen dort max. 15 Minuten und nur stündlich oder seltener (siehe automation/README.md, Abschnitt STRATO)." ;;
esac

cpu_limit="$(ulimit -t 2>/dev/null)"
if [ "$cpu_limit" = "unlimited" ] || [ -z "$cpu_limit" ]; then
    pass "Keine CPU-Zeitbegrenzung für Prozesse dieser Shell (ulimit -t)"
else
    warn "CPU-Zeitbegrenzung ulimit -t = ${cpu_limit}s - ein Lauf kann vorzeitig beendet werden; max_run_seconds darunter halten"
fi
proc_limit="$(ulimit -u 2>/dev/null)"
if [ -n "$proc_limit" ] && [ "$proc_limit" != "unlimited" ] && [ "$proc_limit" -lt 20 ] 2>/dev/null; then
    warn "Sehr wenige Prozesse erlaubt (ulimit -u = $proc_limit) - Sofort-Läufe der Website könnten scheitern"
else
    info "Prozesslimit (ulimit -u): ${proc_limit:-?}"
fi
mem_limit="$(ulimit -v 2>/dev/null)"
if [ -n "$mem_limit" ] && [ "$mem_limit" != "unlimited" ] && [ "$mem_limit" -lt 262144 ] 2>/dev/null; then
    warn "Virtueller Speicher begrenzt auf ${mem_limit} KB (ulimit -v) - Python könnte nicht starten"
fi

# --------------------------------------------------------------------------
section "Speicherplatz und Dateisystem"

free_kb="$(df -Pk "$PROJECT_DIR" 2>/dev/null | awk 'NR==2 {print $4}')"
if [ -n "$free_kb" ]; then
    if [ "$free_kb" -lt 102400 ] 2>/dev/null; then
        fail "Nur $((free_kb / 1024)) MB frei im Projektverzeichnis (mind. 100 MB empfohlen)"
    elif [ "$free_kb" -lt 512000 ] 2>/dev/null; then
        warn "$((free_kb / 1024)) MB frei - für Python-Abhängigkeiten und Logs knapp"
    else
        pass "$((free_kb / 1024)) MB frei im Projektverzeichnis"
    fi
else
    warn "Freier Speicher konnte nicht ermittelt werden (df)"
fi

TEST_DIR="$PROJECT_DIR/.check_server_$$"
if mkdir "$TEST_DIR" 2>/dev/null; then
    CLEANUP+=("$TEST_DIR")
    pass "Projektverzeichnis ist beschreibbar"
    printf '#!/bin/sh\necho ok\n' > "$TEST_DIR/exec_test.sh"
    chmod +x "$TEST_DIR/exec_test.sh"
    if [ "$("$TEST_DIR/exec_test.sh" 2>/dev/null)" = "ok" ]; then
        pass "Dateien im Projektverzeichnis sind ausführbar (kein noexec - nötig für eine Python-venv)"
    else
        warn "Dateien im Projektverzeichnis lassen sich nicht ausführen (noexec?) - eine venv dort funktioniert nicht, nur der System-Python mit automation/vendor"
    fi
    if ln -s "$TEST_DIR/exec_test.sh" "$TEST_DIR/link" 2>/dev/null; then
        pass "Symbolische Links möglich"
    else
        warn "Keine symbolischen Links möglich (venv nutzt sie)"
    fi
else
    fail "Projektverzeichnis $PROJECT_DIR ist nicht beschreibbar"
    TEST_DIR=""
fi

for sub in automation/var workflows config; do
    dir="$PROJECT_DIR/$sub"
    if [ -d "$dir" ]; then
        probe="$dir/.check_server_write_$$"
        if ( : > "$probe" ) 2>/dev/null; then
            rm -f "$probe"
            pass "$sub/ ist beschreibbar"
        else
            fail "$sub/ ist nicht beschreibbar (chmod u+w $dir)"
        fi
    else
        info "$sub/ existiert noch nicht (wird bei der Installation angelegt)"
    fi
done

# --------------------------------------------------------------------------
section "PHP (Kommandozeile)"

if [ -z "$PHP_BIN" ]; then
    for candidate in php php8.5 php8.4 php8.3 php8.2 /bin/php /usr/bin/php /usr/local/bin/php; do
        if have "$candidate" || [ -x "$candidate" ]; then PHP_BIN="$candidate"; break; fi
    done
fi
others=""
for candidate in /usr/bin/php[0-9]* /usr/local/bin/php[0-9]* /opt/RZphp*/bin/php-cli; do
    [ -x "$candidate" ] && others="$others $candidate"
done
[ -n "$others" ] && info "Weitere PHP-Versionen gefunden:$others"

if [ -z "$PHP_BIN" ]; then
    fail "Kein PHP auf der Kommandozeile gefunden (für composer/install.sh nötig; die Website nutzt das PHP des Webservers)"
else
    php_version="$("$PHP_BIN" -r 'echo PHP_VERSION;' 2>/dev/null)"
    if [ -z "$php_version" ]; then
        fail "$PHP_BIN lässt sich nicht ausführen"
    elif version_ge "$php_version" "$MIN_PHP"; then
        pass "PHP $php_version ($PHP_BIN) >= $MIN_PHP"
    else
        fail "PHP $php_version ($PHP_BIN) ist zu alt - mindestens $MIN_PHP nötig (symfony/yaml). Andere Version im Kunden-Login bzw. per --php wählen"
    fi

    if [ -n "$php_version" ]; then
        php_report="$("$PHP_BIN" -r '
            $ext = ["pdo_sqlite", "curl", "dom", "mbstring", "openssl", "json", "session", "hash"];
            foreach ($ext as $e) { echo "ext:$e:", extension_loaded($e) ? "1" : "0", "\n"; }
            echo "ext:ctype:", extension_loaded("ctype") ? "1" : "0", "\n";
            echo "sqlite:", class_exists("PDO") && in_array("sqlite", PDO::getAvailableDrivers(), true)
                ? (new PDO("sqlite::memory:"))->query("select sqlite_version()")->fetchColumn() : "", "\n";
            echo "disabled:", ini_get("disable_functions"), "\n";
            echo "open_basedir:", ini_get("open_basedir"), "\n";
            echo "memory_limit:", ini_get("memory_limit"), "\n";
            $p = function_exists("proc_open") ? @proc_open(["/bin/sh", "-c", "echo pong"], [1 => ["pipe", "w"]], $pipes) : false;
            $out = is_resource($p) ? trim(stream_get_contents($pipes[1])) : "";
            if (is_resource($p)) { proc_close($p); }
            echo "proc_open:", $out === "pong" ? "1" : "0", "\n";
        ' 2>/dev/null)"
        for e in pdo_sqlite curl dom mbstring openssl json session hash; do
            if printf '%s\n' "$php_report" | grep -qx "ext:$e:1"; then
                pass "PHP-Erweiterung $e"
            else
                fail "PHP-Erweiterung $e fehlt (CLI)"
            fi
        done
        printf '%s\n' "$php_report" | grep -qx "ext:ctype:1" && pass "PHP-Erweiterung ctype" \
            || info "PHP-Erweiterung ctype fehlt - wird durch symfony/polyfill-ctype ersetzt"
        php_sqlite="$(printf '%s\n' "$php_report" | sed -n 's/^sqlite://p')"
        if [ -n "$php_sqlite" ] && version_ge "$php_sqlite" "$MIN_SQLITE"; then
            pass "SQLite in PHP $php_sqlite >= $MIN_SQLITE"
        elif [ -n "$php_sqlite" ]; then
            fail "SQLite in PHP $php_sqlite ist zu alt (mindestens $MIN_SQLITE)"
        fi
        disabled="$(printf '%s\n' "$php_report" | sed -n 's/^disabled://p')"
        [ -n "$disabled" ] && info "disable_functions (CLI): $disabled"
        if printf '%s\n' "$php_report" | grep -qx "proc_open:1"; then
            pass "proc_open funktioniert (CLI)"
        else
            warn "proc_open ist auf der Kommandozeile nicht nutzbar - entscheidend ist aber der Webserver (--web-url prüfen)"
        fi
        basedir="$(printf '%s\n' "$php_report" | sed -n 's/^open_basedir://p')"
        [ -n "$basedir" ] && info "open_basedir (CLI): $basedir"
        info "memory_limit (CLI): $(printf '%s\n' "$php_report" | sed -n 's/^memory_limit://p')"
    fi
fi

if have composer; then
    pass "composer vorhanden ($(composer --version 2>/dev/null | head -n1))"
elif [ -f "$PROJECT_DIR/website/vendor/autoload.php" ]; then
    pass "composer nicht nötig - website/vendor/ ist schon vorhanden"
else
    warn "Weder composer noch website/vendor/ vorhanden - Build mit tools/build.sh erzeugen (bündelt vendor/)"
fi

# --------------------------------------------------------------------------
section "Python"

if [ -z "$PYTHON_BIN" ]; then
    for candidate in "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/automation/.venv/bin/python" \
                     python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 /usr/bin/python3; do
        if [ -x "$candidate" ] || have "$candidate"; then PYTHON_BIN="$candidate"; break; fi
    done
fi
others=""
for candidate in /usr/bin/python3.[0-9]* /usr/local/bin/python3.[0-9]*; do
    case "$candidate" in *-config|*m) continue ;; esac
    [ -x "$candidate" ] && others="$others $candidate"
done
[ -n "$others" ] && info "Weitere Python-Versionen gefunden:$others"

if [ -z "$PYTHON_BIN" ]; then
    fail "Kein python3 gefunden - die Automatisierung läuft in Python"
else
    py_version="$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())' 2>/dev/null)"
    if [ -z "$py_version" ]; then
        fail "$PYTHON_BIN lässt sich nicht ausführen"
    elif version_ge "$py_version" "$MIN_PYTHON"; then
        pass "Python $py_version ($PYTHON_BIN) >= $MIN_PYTHON"
    else
        fail "Python $py_version ($PYTHON_BIN) ist zu alt - mindestens $MIN_PYTHON nötig (per --python eine neuere wählen)"
        py_version=""  # the remaining Python checks would only repeat this failure
    fi
fi

if [ -n "${py_version:-}" ]; then
    py_report="$(cd "$PROJECT_DIR" && "$PYTHON_BIN" - <<'PY' 2>&1
import importlib, os, sys
def flag(name, ok, detail=""):
    print(f"{name}:{1 if ok else 0}:{detail}")
for mod in ("sqlite3", "ssl", "fcntl", "json", "smtplib", "venv", "ensurepip"):
    try:
        m = importlib.import_module(mod)
        detail = ""
        if mod == "sqlite3":
            detail = m.sqlite_version
        elif mod == "ssl":
            detail = m.OPENSSL_VERSION
        flag("std_" + mod, True, detail)
    except Exception as exc:
        flag("std_" + mod, False, type(exc).__name__)
try:
    import pip  # noqa: F401
    flag("pip", True, pip.__version__)
except Exception:
    flag("pip", False)
# The project's own dependencies - through automation/__init__.py, which puts
# automation/vendor/ (bundled by tools/build.sh) on sys.path when it exists.
vendored = os.path.isdir(os.path.join("automation", "vendor"))
if os.path.isfile(os.path.join("automation", "__init__.py")):
    sys.path.insert(0, os.getcwd())
    try:
        import automation  # noqa: F401
    except Exception:
        pass
for mod, dist in (("yaml", "PyYAML"), ("requests", "requests"), ("icalendar", "icalendar"), ("dateutil", "python-dateutil")):
    try:
        m = importlib.import_module(mod)
        flag("dep_" + dist, True, getattr(m, "__version__", ""))
    except Exception as exc:
        flag("dep_" + dist, False, type(exc).__name__)
try:
    import cryptography
    flag("opt_cryptography", True, cryptography.__version__)
except Exception:
    flag("opt_cryptography", False)
flag("vendor", vendored)
PY
)"
    get() { printf '%s\n' "$py_report" | grep "^$1:" | head -n1; }
    for mod in sqlite3 ssl fcntl json smtplib; do
        line="$(get "std_$mod")"
        case "$line" in
            *:1:*) pass "Python-Modul $mod ${line##*:}" ;;
            *) fail "Python-Modul $mod fehlt (${line##*:})" ;;
        esac
    done
    py_sqlite="$(get std_sqlite3)"; py_sqlite="${py_sqlite##*:}"
    if [ -n "$py_sqlite" ]; then
        if version_ge "$py_sqlite" "$MIN_SQLITE"; then
            pass "SQLite in Python $py_sqlite >= $MIN_SQLITE"
        else
            fail "SQLite in Python $py_sqlite ist zu alt (mindestens $MIN_SQLITE)"
        fi
    fi
    venv_line="$(get std_venv)"; ensure_line="$(get std_ensurepip)"; pip_line="$(get pip)"
    case "$venv_line$ensure_line" in
        *venv:1:*ensurepip:1:*) pass "venv und ensurepip vorhanden (eigene Umgebung möglich)" ;;
        *) warn "venv/ensurepip fehlt - keine eigene Python-Umgebung; Abhängigkeiten dann über automation/vendor (tools/build.sh)" ;;
    esac
    case "$pip_line" in
        pip:1:*) pass "pip ${pip_line##*:}" ;;
        *) info "pip nicht vorhanden (nur nötig, wenn automation/vendor fehlt)" ;;
    esac
    missing_deps=""
    for dist in PyYAML requests icalendar python-dateutil; do
        line="$(get "dep_$dist")"
        case "$line" in
            *:1:*) pass "Abhängigkeit $dist ${line##*:}" ;;
            *) missing_deps="$missing_deps $dist" ;;
        esac
    done
    if [ -n "$missing_deps" ]; then
        if [ -d "$PROJECT_DIR/automation" ]; then
            fail "Python-Abhängigkeiten fehlen:$missing_deps (install.sh installiert sie, oder Build mit tools/build.sh bündelt sie in automation/vendor)"
        else
            info "Python-Abhängigkeiten noch nicht installiert:$missing_deps (normal vor dem Hochladen)"
        fi
    fi
    case "$(get opt_cryptography)" in
        *:1:*) pass "Optional: cryptography vorhanden (verschlüsselte App-Passwörter möglich)" ;;
        *) info "Optional: cryptography fehlt - encrypted_app_password geht nicht, app_password schon" ;;
    esac

    # Locking: the automation relies on flock (run lock) and SQLite locking on
    # this filesystem - both can silently not work on some network filesystems.
    if [ -n "$TEST_DIR" ]; then
        lock_result="$("$PYTHON_BIN" - "$TEST_DIR" <<'PY' 2>&1
import fcntl, os, sqlite3, subprocess, sys, time
d = sys.argv[1]
path = os.path.join(d, "lock")
holder = open(path, "a")
fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
child = subprocess.run([sys.executable, "-c",
    "import fcntl,sys\nf=open(sys.argv[1],'a')\ntry:\n fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); print('free')\nexcept OSError: print('held')",
    path], capture_output=True, text=True)
print("flock:" + child.stdout.strip())
db = os.path.join(d, "t.sqlite3")
a = sqlite3.connect(db, timeout=0.2); b = sqlite3.connect(db, timeout=0.2)
a.execute("create table t (k text primary key, v int)"); a.commit()
a.execute("insert into t values ('x', 1) on conflict(k) do update set v = excluded.v + 1"); a.execute("insert into t values ('x', 1) on conflict(k) do update set v = excluded.v + 1"); a.commit()
a.execute("begin immediate")
try:
    b.execute("begin immediate"); print("sqlite_lock:none")
except sqlite3.OperationalError:
    print("sqlite_lock:ok")
a.rollback()
print("upsert:" + str(a.execute("select v from t").fetchone()[0]))
PY
)"
        case "$lock_result" in *flock:held*) pass "Dateisperren (flock) funktionieren - überlappende Läufe werden verhindert" ;;
            *) fail "Dateisperren (flock) wirken nicht zwischen Prozessen ($lock_result) - überlappende Läufe möglich" ;; esac
        case "$lock_result" in *sqlite_lock:ok*) pass "SQLite-Sperren funktionieren auf diesem Dateisystem" ;;
            *) fail "SQLite-Sperren wirken nicht auf diesem Dateisystem - Datenbank kann beschädigt werden" ;; esac
        case "$lock_result" in *upsert:2*) pass "SQLite-Upserts funktionieren" ;;
            *) fail "SQLite-Upserts (ON CONFLICT DO UPDATE) funktionieren nicht" ;; esac
    fi

    # Detached background start - what webhook.php/link.php do via proc_open.
    started=$(date +%s)
    sh -c "sleep 3 &" >/dev/null 2>&1
    if [ $(( $(date +%s) - started )) -le 2 ]; then
        pass "Hintergrundprozesse lassen sich abgekoppelt starten"
    else
        warn "Ein abgekoppelter Hintergrundprozess blockiert die Shell - Sofort-Läufe der Website könnten langsam sein"
    fi
fi

# --------------------------------------------------------------------------
section "Werkzeuge"

for tool in curl openssl tar; do
    if have "$tool"; then pass "$tool vorhanden"; else warn "$tool fehlt"; fi
done
have unzip && pass "unzip vorhanden" || info "unzip fehlt (nur für .zip-Uploads nötig)"
if have crontab; then
    if crontab -l >/dev/null 2>&1 || crontab -l 2>&1 | grep -qi "no crontab"; then
        pass "crontab nutzbar (Cron-Job kann per Kommandozeile eingetragen werden)"
    else
        warn "crontab vorhanden, aber nicht nutzbar - Cron-Job über die Hosting-Verwaltung einrichten"
    fi
else
    info "crontab fehlt - Cron-Job über die Hosting-Verwaltung einrichten (bei STRATO: Kunden-Login > Verwaltung > Cron-Jobs)"
fi

# --------------------------------------------------------------------------
section "Konfiguration"

settings="$PROJECT_DIR/config/settings.yaml"
if [ -f "$settings" ]; then
    pass "config/settings.yaml vorhanden"
    max_run="$(sed -n 's/^max_run_seconds:[[:space:]]*\([0-9.]*\).*/\1/p' "$settings" | head -n1)"
    max_run="${max_run%%.*}"
    if [ -n "$max_run" ] && [ "$max_run" -ge "$CRON_LIMIT_HINT" ] 2>/dev/null; then
        warn "max_run_seconds = $max_run - bei STRATO werden Cron-Jobs nach 900 s beendet; z. B. 600 setzen"
    else
        info "max_run_seconds = ${max_run:-600 (Standard)}"
    fi
    grep -q '^public_url:' "$settings" && pass "public_url gesetzt (für Einmal-Links)" \
        || info "public_url nicht gesetzt - nur nötig für die Action \"Einmal-Link erstellen\""
else
    info "config/settings.yaml fehlt noch (install.sh legt sie an)"
fi
nextcloud_cfg="$PROJECT_DIR/config/nextcloud.yaml"
if [ -f "$nextcloud_cfg" ]; then
    pass "config/nextcloud.yaml vorhanden"
    perms="$(stat -c '%a' "$nextcloud_cfg" 2>/dev/null)"
    case "$perms" in
        ?[0-7][4-7]|?[4-7][0-7]) warn "config/nextcloud.yaml ist für andere lesbar (Rechte $perms) - chmod 600 empfohlen" ;;
        "") ;;
        *) pass "config/nextcloud.yaml nur für den Besitzer lesbar ($perms)" ;;
    esac
    [ -z "$NEXTCLOUD_URL" ] && NEXTCLOUD_URL="$(sed -n 's/^[[:space:]]*url:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' "$nextcloud_cfg" | head -n1)"
else
    info "config/nextcloud.yaml fehlt noch (install.sh legt sie an)"
fi

# --------------------------------------------------------------------------
section "Netzwerk"

if [ "$NETWORK" -eq 0 ]; then
    info "Übersprungen (--no-network)"
elif ! have curl; then
    warn "Ohne curl keine Netzwerk-Tests"
else
    check_url_time() {  # compares the server's Date header with the local clock
        local date_header remote now skew
        date_header="$(curl -sSI --max-time 15 "$1" 2>/dev/null | tr -d '\r' | sed -n 's/^[Dd]ate: //p' | head -n1)"
        [ -z "$date_header" ] && return
        remote="$(date -u -d "$date_header" +%s 2>/dev/null)" || return
        now="$(date -u +%s)"; skew=$(( now - remote )); skew=${skew#-}
        if [ "$skew" -gt 120 ]; then
            warn "Uhrzeit weicht um ${skew}s von $1 ab - Zeitpläne und Statusseite werden ungenau"
        else
            pass "Uhrzeit stimmt mit $1 überein (Abweichung ${skew}s)"
        fi
    }
    if [ -n "$NEXTCLOUD_URL" ]; then
        base="${NEXTCLOUD_URL%/}"
        status_json="$(curl -sS --max-time 20 "$base/status.php" 2>&1)"
        case "$(printf '%s' "$status_json" | tr -d ' ')" in
            *'"installed":true'*)
                nc_version="$(printf '%s' "$status_json" | tr -d ' ' | sed -n 's/.*"versionstring":"\([^"]*\)".*/\1/p')"
                pass "Nextcloud erreichbar: $base (Version ${nc_version:-?})"
                check_url_time "$base/status.php" ;;
            *) fail "Nextcloud unter $base nicht erreichbar oder kein Nextcloud ($(printf '%s' "$status_json" | head -c 120))" ;;
        esac
        deck_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H 'OCS-APIRequest: true' "$base/index.php/apps/deck/api/v1.1/boards")"
        case "$deck_code" in
            401) pass "Deck-API antwortet (401 ohne Anmeldung - erwartet)" ;;
            200) pass "Deck-API antwortet" ;;
            404) fail "Deck-API nicht gefunden (404) - ist die Deck-App installiert?" ;;
            *) warn "Deck-API antwortet mit HTTP $deck_code" ;;
        esac
    else
        info "Keine Nextcloud-Adresse bekannt - mit --nextcloud-url URL prüfen"
    fi
    pypi_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://pypi.org/simple/pyyaml/)"
    if [ "$pypi_code" = "200" ]; then
        pass "pypi.org erreichbar (pip install möglich)"
    else
        info "pypi.org nicht erreichbar (HTTP $pypi_code) - Abhängigkeiten dann über automation/vendor (tools/build.sh)"
    fi
    smtp_cfg="$PROJECT_DIR/config/smtp.yaml"
    if [ -f "$smtp_cfg" ] && [ -n "${py_version:-}" ]; then
        smtp_host="$(sed -n 's/^host:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' "$smtp_cfg" | head -n1)"
        smtp_port="$(sed -n 's/^port:[[:space:]]*\([0-9]*\).*/\1/p' "$smtp_cfg" | head -n1)"
        if [ -n "$smtp_host" ] && "$PYTHON_BIN" -c "import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 10).close()" "$smtp_host" "${smtp_port:-587}" 2>/dev/null; then
            pass "SMTP-Server $smtp_host:${smtp_port:-587} erreichbar"
        else
            fail "SMTP-Server ${smtp_host:-?}:${smtp_port:-587} nicht erreichbar (ausgehende Verbindungen gesperrt?)"
        fi
    fi
fi

# --------------------------------------------------------------------------
section "Webserver (PHP der Website)"

if [ -z "$WEB_URL" ]; then
    info "Übersprungen - mit --web-url https://deine-domain/pfad/website prüfen (PHP des Webservers kann von der Kommandozeile abweichen)"
elif [ "$NETWORK" -eq 0 ] || ! have curl; then
    info "Übersprungen (kein Netzwerk/curl)"
elif [ ! -d "$PROJECT_DIR/website" ]; then
    warn "website/ fehlt im Projektverzeichnis - Webserver-Test nicht möglich"
else
    web="${WEB_URL%/}"
    token="$(od -An -N8 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')"
    probe_name="check_server_${token:-$$}.php"
    probe="$PROJECT_DIR/website/$probe_name"
    cat > "$probe" <<'PHP'
<?php
header('Content-Type: text/plain');
$ext = ['pdo_sqlite', 'curl', 'dom', 'mbstring', 'openssl', 'json', 'session', 'hash'];
foreach ($ext as $e) { echo "ext:$e:", extension_loaded($e) ? '1' : '0', "\n"; }
echo 'version:', PHP_VERSION, "\n";
echo 'sapi:', PHP_SAPI, "\n";
echo 'max_execution_time:', ini_get('max_execution_time'), "\n";
echo 'display_errors:', ini_get('display_errors'), "\n";
echo 'disabled:', ini_get('disable_functions'), "\n";
function run_sh(string $cmd): ?string {
    if (!function_exists('proc_open')) { return null; }
    $p = @proc_open(['/bin/sh', '-c', $cmd], [1 => ['pipe', 'w']], $pipes);
    if (!is_resource($p)) { return null; }
    $out = trim((string) stream_get_contents($pipes[1]));
    proc_close($p);
    return $out;
}
$pong = run_sh('echo pong');
echo 'proc_open:', $pong === 'pong' ? '1' : '0', "\n";
echo 'python3:', $pong === 'pong' ? (string) run_sh('command -v python3 2>/dev/null') : '', "\n";
echo 'sqlite:', in_array('sqlite', PDO::getAvailableDrivers(), true)
    ? (new PDO('sqlite::memory:'))->query('select sqlite_version()')->fetchColumn() : '', "\n";
PHP
    CLEANUP+=("$probe")
    web_report="$(curl -s --max-time 30 -w '\nhttp:%{http_code}' "$web/$probe_name")"
    rm -f "$probe"
    web_code="$(printf '%s\n' "$web_report" | sed -n 's/^http://p' | tail -n1)"
    if [ "$web_code" = "401" ]; then
        warn "Die Website verlangt eine Anmeldung (401) - Webserver-PHP konnte nicht geprüft werden. Test ohne Zugriffsschutz wiederholen"
    elif [ "$web_code" != "200" ]; then
        fail "Prüfseite über $web nicht abrufbar (HTTP $web_code) - stimmt --web-url? Zeigt die Adresse auf website/?"
    else
        web_version="$(printf '%s\n' "$web_report" | sed -n 's/^version://p')"
        if version_ge "$web_version" "$MIN_PHP"; then
            pass "Webserver-PHP $web_version ($(printf '%s\n' "$web_report" | sed -n 's/^sapi://p')) >= $MIN_PHP"
        else
            fail "Webserver-PHP $web_version ist zu alt - mindestens $MIN_PHP (PHP-Version im Kunden-Login umstellen)"
        fi
        for e in pdo_sqlite curl dom mbstring openssl json session hash; do
            printf '%s\n' "$web_report" | grep -qx "ext:$e:1" && pass "Webserver-PHP-Erweiterung $e" \
                || fail "Webserver-PHP-Erweiterung $e fehlt"
        done
        web_sqlite="$(printf '%s\n' "$web_report" | sed -n 's/^sqlite://p')"
        if [ -n "$web_sqlite" ] && ! version_ge "$web_sqlite" "$MIN_SQLITE"; then
            fail "SQLite im Webserver-PHP $web_sqlite ist zu alt (mindestens $MIN_SQLITE)"
        fi
        info "max_execution_time (Web): $(printf '%s\n' "$web_report" | sed -n 's/^max_execution_time://p') s"
        if printf '%s\n' "$web_report" | grep -qx "proc_open:1"; then
            pass "proc_open im Webserver erlaubt - Webhooks und Einmal-Links lösen sofort einen Lauf aus"
            py_web="$(printf '%s\n' "$web_report" | sed -n 's/^python3://p')"
            if [ -n "$py_web" ] || [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
                pass "Der Webserver findet Python (${py_web:-$PROJECT_DIR/.venv/bin/python})"
            else
                warn "Der Webserver findet kein python3 im PATH und keine .venv im Projekt - Sofort-Läufe starten nicht"
            fi
        else
            warn "proc_open im Webserver gesperrt - Webhooks/Einmal-Links werden erst beim nächsten Cron-Lauf ausgeführt"
        fi
        case "$(printf '%s\n' "$web_report" | sed -n 's/^display_errors://p')" in
            1|On|on|stdout) warn "display_errors ist an - PHP-Hinweise könnten in Antworten der Website landen" ;;
        esac

        # Access protection of the deployed site.
        index_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$web/index.php")"
        case "$index_code" in
            401) pass "website/ ist per Anmeldung geschützt (401)" ;;
            200) warn "website/index.php ist ohne Anmeldung erreichbar - die Website hat kein eigenes Login (siehe website/README.md)" ;;
            *) info "website/index.php antwortet mit HTTP $index_code" ;;
        esac
        src_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$web/src/Config.php")"
        case "$src_code" in
            403|404|401) pass "website/src/ ist nicht direkt abrufbar ($src_code)" ;;
            *) warn "website/src/Config.php antwortet mit HTTP $src_code - src/.htaccess greift nicht" ;;
        esac
        # If the URL ends in /website, the project root is probably reachable one
        # level up - then config/ (credentials!) must not be.
        case "$web" in
            */website)
                parent="${web%/website}"
                cfg_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$parent/config/nextcloud.yaml")"
                case "$cfg_code" in
                    200) fail "config/nextcloud.yaml ist über $parent/config/ abrufbar - Zugangsdaten öffentlich! Zugriff auf alles außer website/ sperren" ;;
                    000) info "config/ konnte nicht geprüft werden (keine Antwort)" ;;
                    *) pass "config/ ist nicht über das Web erreichbar ($cfg_code)" ;;
                esac
                for leaked in automation/var/state.sqlite3 workflows/; do
                    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$parent/$leaked")"
                    [ "$code" = "200" ] && fail "$leaked ist über $parent/$leaked öffentlich abrufbar"
                done ;;
            *) info "Die Adresse endet nicht auf /website - ob config/ öffentlich ist, bitte selbst prüfen" ;;
        esac
        for public in link.php webhook.php; do
            code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$web/$public")"
            case "$code" in
                401) warn "$public verlangt eine Anmeldung - für Einmal-Links/Webhooks freigeben (website/README.md)" ;;
                404|410|400|403) pass "$public ist ohne Anmeldung erreichbar ($code ohne gültigen Token - erwartet)" ;;
                *) info "$public antwortet mit HTTP $code" ;;
            esac
        done
    fi
fi

# --------------------------------------------------------------------------
section "Ergebnis"

printf '  %d in Ordnung, %d Warnung(en), %d Fehler\n' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
if [ "$FAIL_COUNT" -gt 0 ]; then
    printf '\n  Fehler:\n'
    for item in "${FAILS[@]}"; do printf '   - %s\n' "$item"; done
fi
if [ "$WARN_COUNT" -gt 0 ]; then
    printf '\n  Warnungen:\n'
    for item in "${WARNS[@]}"; do printf '   - %s\n' "$item"; done
fi
[ "$FAIL_COUNT" -eq 0 ]
