#!/usr/bin/env bash
#
# Guided installer - run this ON THE SERVER, inside the uploaded project
# directory (where automation/, website/, config/, workflows/ are siblings
# of this script).
#
# Walks through: environment checks, PHP/Python dependencies, the config
# dialog (configure.sh, which writes config/*.yaml), optional
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

# Echoes a working "pip" command prefix ("pip3" or "python3 -m pip"), or
# nothing if neither is available. Some shared hosts ship python3 without a
# standalone pip3 binary (Debian/Ubuntu split pip out of the base install) -
# `-m pip` still works there if the pip module itself is present.
pip_invocation() {
    if command -v pip3 >/dev/null 2>&1; then
        echo "pip3"
    elif command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then
        echo "python3 -m pip"
    fi
}

# Some python3 installs have neither pip3 nor a working `-m pip`, but do
# ship `ensurepip` in the stdlib (it bundles its own pip wheel, no network
# install step needed) - try that once before concluding pip just isn't
# available. Harmless no-op if ensurepip isn't present either.
ensure_pip_bootstrap() {
    if [ -z "$(pip_invocation)" ] && command -v python3 >/dev/null 2>&1; then
        python3 -m ensurepip --user >/dev/null 2>&1 || true
    fi
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
        # Not `php -r` - some hardened shared-hosting PHP CLI builds disable
        # the -r flag entirely (arbitrary-code-from-the-command-line is a
        # common thing to lock down), which just prints the usage text
        # instead of the version. `-v` is always available.
        info "PHP: $(php -v 2>/dev/null | head -n 1)"
        local php_version
        php_version="$(php -v 2>/dev/null | head -n 1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)"
        if [ -n "$php_version" ] && [ "$(printf '%s\n%s\n' "8.4.27" "$php_version" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" != "8.4.27" ]; then
            warn "PHP $php_version ist zu alt - die Website braucht mindestens PHP 8.4.27 (PHP-Version im Kunden-Login umstellen; die Kommandozeile kann eine andere Version als der Webserver haben)."
        fi
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

    local pip_found
    pip_found="$(pip_invocation)"
    if [ -n "$pip_found" ]; then
        info "pip: vorhanden ($pip_found)"
    else
        warn "Kein pip gefunden (weder pip3 noch 'python3 -m pip')."
    fi

    if command -v crontab >/dev/null 2>&1; then
        info "crontab: vorhanden"
    else
        info "crontab: nicht gefunden (Cron-Job über die Hosting-Verwaltung einrichten, z.B. eine 'Cron Jobs'-Seite im Control Panel)"
    fi
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

    if [ -d "$AUTOMATION_DIR/vendor" ]; then
        info "automation/vendor/ ist bereits gebündelt (von tools/build.sh) - nichts zu installieren."
        return
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        warn "python3 fehlt - Schritt übersprungen."
        note_todo "python3 installieren, dann 'pip3 install -r automation/requirements.txt' ausführen."
        return
    fi

    ensure_pip_bootstrap

    local made_venv="n"
    if [ -x "$AUTOMATION_DIR/.venv/bin/python" ]; then
        info "automation/.venv existiert bereits."
        made_venv="j"
    elif confirm "Virtuelle Umgebung (automation/.venv) anlegen? (empfohlen)" "j"; then
        if python3 -m venv "$AUTOMATION_DIR/.venv" 2>/dev/null; then
            info "venv angelegt."
            made_venv="j"
        else
            warn "venv konnte nicht angelegt werden (python3-venv/ensurepip evtl. nicht installiert) - installiere stattdessen für den aktuellen Nutzer."
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
        return
    fi

    local pip_found
    pip_found="$(pip_invocation)"
    if [ -n "$pip_found" ]; then
        info "Installiere Pakete für den aktuellen Nutzer ($pip_found install --user) ..."
        if $pip_found install -q --user -r "$AUTOMATION_DIR/requirements.txt"; then
            info "Erfolgreich installiert."
        else
            warn "$pip_found install --user ist fehlgeschlagen."
            note_todo "Python-Abhängigkeiten manuell installieren: $pip_found install --user -r automation/requirements.txt"
        fi
    else
        warn "Kein pip verfügbar (weder pip3 noch 'python3 -m pip', auch nicht nach ensurepip-Versuch)."
        note_todo "Python-Abhängigkeiten konnten nicht installiert werden, da kein pip verfügbar ist. Auf Shared Hosting meist nicht per 'apt install' lösbar - in der Hosting-Verwaltung nach einer anderen/neueren Python-Version suchen (oft mit eigenem, vollständigem pip) oder den Support fragen."
    fi
}

# Konfiguration: configure.sh führt durch alle config/*.yaml - vorhandene
# Werte werden zur Übernahme angeboten, fehlende mit Standardwert vorgeschlagen
# (beim ersten Mal also alle). Dasselbe Skript später erneut aufrufen, um
# einzelne Werte zu ändern oder neue zu ergänzen.
section_config() {
    local script="$PROJECT_ROOT/configure.sh"
    [ -x "$script" ] || script="$PROJECT_ROOT/tools/configure.sh"
    if [ ! -f "$script" ]; then
        warn "configure.sh nicht gefunden - config/*.yaml müssen von Hand aus den *.example.yaml angelegt werden."
        note_todo "config/nextcloud.yaml, settings.yaml (und optional smtp.yaml) aus den *.example.yaml anlegen."
        return
    fi
    NCDW_PYTHON="$PYTHON_BIN" bash "$script"
    if [ ! -f "$CONFIG_DIR/nextcloud.yaml" ] || [ ! -f "$CONFIG_DIR/settings.yaml" ]; then
        warn "config/nextcloud.yaml oder settings.yaml fehlt noch."
        note_todo "./configure.sh ausführen, um die Konfiguration abzuschließen."
    fi
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
    # 644, nicht 600: auf vielen Shared-Hosting-Setups läuft der Webserver-
    # Prozess unter einem anderen Systembenutzer als die SSH-Session - mit
    # 600 kann er die Datei dann nicht lesen. Das führt nicht zur erwarteten
    # Login-Abfrage, sondern zu einem harten 500 (so beobachtet auf einem
    # Strato-Webspace). Der apr1-Hash plus der Schutzblock gegen ".ht*"-
    # Dateien weiter unten machen 644 hier vertretbar.
    chmod 644 "$htpasswd_path"

    cat > "$WEBSITE_DIR/.htaccess" <<EOF
# Erzeugt von tools/install.sh - HTTP Basic Auth für dieses Verzeichnis.
Options -Indexes

AuthType Basic
AuthName "Nextcloud Deck Workflows"
AuthUserFile $htpasswd_path

<IfModule mod_authz_core.c>
    Require valid-user
    AuthMerging Off
</IfModule>
<IfModule !mod_authz_core.c>
    require valid-user
</IfModule>

# Reicht den Authorization-Header an PHP weiter, falls PHP über CGI/FastCGI
# läuft (dort kommt er sonst nicht automatisch an). Harmlos, falls
# mod_rewrite fehlt.
<IfModule mod_rewrite.c>
    RewriteEngine On
    RewriteCond %{HTTP:Authorization} ^(.+)\$
    RewriteRule .* - [E=HTTP_AUTHORIZATION:%1]
</IfModule>

# Einmal-Links und Webhooks ohne Login erreichbar machen - ihr Token bzw.
# secret in der URL ist der Zugangsschutz (siehe website/README.md).
<IfModule mod_authz_core.c>
    <FilesMatch "^(link|webhook)\.php\$">
        Require all granted
    </FilesMatch>
</IfModule>

# .htpasswd (und jede andere .ht*-Datei) nie direkt ausliefern.
<IfModule mod_authz_core.c>
    <FilesMatch "^\.ht">
        Require all denied
    </FilesMatch>
</IfModule>
<IfModule !mod_authz_core.c>
    <FilesMatch "^\.ht">
        Order allow,deny
        Deny from all
    </FilesMatch>
</IfModule>
EOF

    info "website/.htaccess + .htpasswd angelegt (Benutzer: $user)."

    local test_url public_url
    public_url="$("$PYTHON_BIN" -m automation.config.configure --get settings.public_url 2>/dev/null)"
    test_url="$(ask "Öffentliche URL der Website zum Testen (z.B. https://example.com/website/) - leer = überspringen" "$public_url")"
    if [ -n "$test_url" ] && command -v curl >/dev/null 2>&1; then
        info "Prüfe, ob der Schutz funktioniert (ohne Login sollte HTTP 401 kommen) ..."
        local code
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$test_url" 2>/dev/null)"
        case "$code" in
            401)
                info "OK (HTTP 401 - Login wird korrekt verlangt)."
                local link_code
                link_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${test_url%/}/link.php" 2>/dev/null)"
                if [ "$link_code" = "401" ]; then
                    warn "link.php verlangt ebenfalls ein Login - Einmal-Links und Webhooks funktionieren so nicht (Ausnahme in website/.htaccess greift nicht, siehe website/README.md)."
                else
                    info "OK (link.php ohne Login erreichbar - HTTP ${link_code:-?} ohne gültigen Token)."
                fi
                ;;
            500)
                warn "HTTP 500 statt 401 - diese .htaccess funktioniert auf diesem Server nicht. Entferne sie wieder, um die Website nicht zu blockieren."
                rm -f "$WEBSITE_DIR/.htaccess" "$htpasswd_path"
                note_todo "website/ stattdessen über die Hosting-Verwaltung schützen (z.B. 'Verzeichnis per Passwort schützen') - das erzeugt eine serverseitig garantiert passende Konfiguration."
                ;;
            *)
                warn "Unerwarteter Status HTTP ${code:-?} beim Testaufruf - bitte manuell im Browser prüfen. Falls die Seite nicht mehr erreichbar ist: rm '$WEBSITE_DIR/.htaccess' '$htpasswd_path'"
                ;;
        esac
    else
        note_todo "Bitte die Website jetzt im Browser testen. Bei HTTP 500 statt einer Login-Abfrage: rm '$WEBSITE_DIR/.htaccess' '$htpasswd_path' ausführen und den Schutz stattdessen über die Hosting-Verwaltung einrichten."
    fi

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
    info "Hinweis STRATO: Cron-Jobs gibt es dort nur über die Hosting-Verwaltung (Legacy-Plattform ab Hosting Plus),"
    info "  mit höchstens 15 Minuten Laufzeit und nur den Intervallen einmalig/täglich/wöchentlich/monatlich"
    info "  (laut Nutzerberichten teils stündlich). Dann in config/settings.yaml 'max_run_seconds' unter 900"
    info "  lassen (Standard 600) und 'health_stale_minutes' an das Intervall anpassen (siehe automation/README.md)."

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
    section_config

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
