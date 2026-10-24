#!/usr/bin/env bash
#
# Builds an upload-ready copy of the project into build/upload/.
#
# Usage: tools/build.sh [git-ref]   (default: HEAD)
#
# - Exports exactly the committed state of the given ref (git archive) - no
#   untracked/uncommitted files leak into the build.
# - Strips developer-only paths that aren't needed at runtime (tests,
#   dev-requirements, this tools/ folder itself, .gitignore files).
# - Bundles website/vendor/ via `composer install` - symfony/yaml is pure
#   PHP, so a vendor/ built here is safe to ship as-is; the target server
#   doesn't need Composer at all unless this step is skipped.
# - Does NOT bundle a Python venv - automation/requirements.txt ships
#   instead, installed by tools/install.sh on the server. A venv built on
#   this machine often doesn't work on a different host (OS/arch/paths are
#   baked into it), so shipping one would be actively misleading.
# - DOES try to bundle automation/vendor/ (pure-Python sources only, see
#   below) - unlike a venv this is portable, and it means a shared host
#   with no working pip doesn't block the whole thing; install.sh falls
#   back to installing on the server itself if this step didn't run.
# - Copies tools/install.sh and tools/configure.sh to the root of the build output, so it's right
#   there after upload.
#
# Never aborts the whole build over a missing *optional* tool (composer,
# zip) - it warns and continues. Only genuinely fatal problems (no git, no
# tar, an unknown ref) stop the script.

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

REF="${1:-HEAD}"
PROJECT_NAME="nextcloudDeckWorkflows"

log()  { printf '==> %s\n' "$1"; }
warn() { printf 'WARNUNG: %s\n' "$1" >&2; }
die()  { printf 'FEHLER: %s\n' "$1" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git wird benötigt, ist aber nicht installiert."
command -v tar >/dev/null 2>&1 || die "tar wird benötigt, ist aber nicht installiert."

git rev-parse --verify "$REF" >/dev/null 2>&1 || die "Unbekannte Git-Referenz: $REF"

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    warn "Uncommittete Änderungen im Arbeitsverzeichnis - diese landen NICHT im Build (es wird exakt der Commit '$REF' exportiert)."
fi

# -- Version bestimmen --------------------------------------------------------

CURRENT_BRANCH="$(git rev-parse --abbrev-ref "$REF" 2>/dev/null || true)"
if [[ "$CURRENT_BRANCH" == versions/v* ]]; then
    VERSION="${CURRENT_BRANCH#versions/}"
else
    VERSION="$(git describe --tags --always --dirty 2>/dev/null || true)"
    [ -n "$VERSION" ] || VERSION="$(date +%Y%m%d-%H%M%S)"
fi

BUILD_NAME="${PROJECT_NAME}-${VERSION}"
UPLOAD_DIR="$REPO_ROOT/build/upload"
TARGET_DIR="$UPLOAD_DIR/$BUILD_NAME"

log "Baue Version '$VERSION' aus '$REF' nach $TARGET_DIR"

mkdir -p "$UPLOAD_DIR" || die "Konnte $UPLOAD_DIR nicht anlegen."
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"

# -- Exakten Commit-Stand exportieren -----------------------------------------

git archive "$REF" | tar -x -C "$TARGET_DIR" || die "git archive/tar fehlgeschlagen."

# -- Entwickler-only-Pfade entfernen ------------------------------------------

log "Entferne Entwickler-only-Dateien (Tests, Dev-Requirements, tools/, .gitignore-Dateien)"
rm -rf \
    "$TARGET_DIR/automation/tests" \
    "$TARGET_DIR/automation/requirements-dev.txt" \
    "$TARGET_DIR/pyproject.toml" \
    "$TARGET_DIR/tools" \
    "$TARGET_DIR/.gitignore" \
    "$TARGET_DIR/website/.gitignore"

# -- install.sh mit ausliefern -------------------------------------------------

cp "$SCRIPT_DIR/install.sh" "$TARGET_DIR/install.sh"
chmod +x "$TARGET_DIR/install.sh"
# Konfigurations-Dialog (install.sh ruft ihn auf; später erneut aufrufbar).
cp "$SCRIPT_DIR/configure.sh" "$TARGET_DIR/configure.sh"
chmod +x "$TARGET_DIR/configure.sh"
# Voraussetzungs-Check für den Webspace (per SSH vor/nach der Installation).
cp "$SCRIPT_DIR/check_server.sh" "$TARGET_DIR/check_server.sh"
chmod +x "$TARGET_DIR/check_server.sh"

# -- PHP-Abhängigkeiten bündeln -------------------------------------------------
# (vendor/ bekommt danach ein .htaccess, das direkten HTTP-Zugriff sperrt.)

if command -v composer >/dev/null 2>&1; then
    log "Installiere PHP-Abhängigkeiten (composer install --no-dev) ..."
    if ! (cd "$TARGET_DIR/website" && composer install --no-dev --optimize-autoloader --no-interaction); then
        warn "composer install ist fehlgeschlagen - website/vendor/ fehlt im Build. install.sh versucht es serverseitig erneut."
    fi
else
    warn "composer ist nicht installiert - website/vendor/ fehlt im Build. install.sh versucht es serverseitig (falls composer dort verfügbar ist), sonst manuell nachholen."
fi
if [ -d "$TARGET_DIR/website/vendor" ]; then
    cp "$TARGET_DIR/website/src/.htaccess" "$TARGET_DIR/website/vendor/.htaccess"
fi

# -- Python-Abhängigkeiten als portablen Vendor-Ordner bündeln -----------------
#
# PyYAML/requests/icalendar/python-dateutil sind reiner Python-Code - anders
# als ein venv (siehe oben) ist ein daraus gebauter automation/vendor/-Ordner
# deshalb plattformunabhängig und sicher mitlieferbar. "--no-binary=:all:"
# erzwingt die Sdist/Source-Variante statt eines evtl. plattformspezifischen
# Wheels; einzige Ausnahme ist PyYAMLs rein optionale libyaml-C-Erweiterung,
# die trotzdem mitkompiliert würde, FALLS auf dieser Build-Maschine die
# libyaml-Dev-Header installiert sind (PyYAML funktioniert ohne sie genauso,
# nur etwas langsamer) - im Zweifel also auf einer Maschine ohne libyaml-dev
# bauen, oder einen automation/vendor/_yaml*.so-Fund danach einfach löschen.
# automation/__init__.py setzt automation/vendor/ (falls vorhanden) vorn auf
# sys.path, genau wie website/index.php es für website/vendor/ tut.
if command -v python3 >/dev/null 2>&1; then
    log "Installiere Python-Abhängigkeiten nach automation/vendor/ (pip install --target) ..."
    # requirements-vendor.txt pins the exact set (resolved on the oldest
    # supported Python, 3.9) and --no-deps keeps pip from re-resolving it for
    # this build machine's Python - otherwise the bundle would only run on
    # Python versions as new as the one that built it.
    if python3 -m pip install -q --no-binary=:all: --no-deps \
        --target "$TARGET_DIR/automation/vendor" -r "$TARGET_DIR/automation/requirements-vendor.txt"; then
        find "$TARGET_DIR/automation/vendor" -name "__pycache__" -exec rm -rf {} + 2>/dev/null
        # Compiled extensions only fit this machine's Python; PyYAML falls back
        # to its pure-Python implementation without them.
        find "$TARGET_DIR/automation/vendor" -name "*.so" -delete 2>/dev/null
        log "automation/vendor/ erfolgreich befüllt."
    else
        warn "pip install --target automation/vendor ist fehlgeschlagen - automation/vendor/ fehlt im Build. install.sh installiert die Abhängigkeiten dann serverseitig (venv/pip)."
        rm -rf "$TARGET_DIR/automation/vendor"
    fi
else
    warn "python3 ist auf dieser Build-Maschine nicht verfügbar - automation/vendor/ fehlt im Build. install.sh installiert die Abhängigkeiten serverseitig."
fi

# -- Build-Info -----------------------------------------------------------------

{
    echo "project: $PROJECT_NAME"
    echo "version: $VERSION"
    echo "ref: $REF"
    echo "commit: $(git rev-parse "$REF")"
    echo "built_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$TARGET_DIR/BUILD_INFO.txt"

# -- Archive erzeugen -------------------------------------------------------------

(
    cd "$UPLOAD_DIR"

    if command -v zip >/dev/null 2>&1; then
        log "Erzeuge $BUILD_NAME.zip"
        rm -f "$BUILD_NAME.zip"
        zip -rq "$BUILD_NAME.zip" "$BUILD_NAME"
    else
        warn "zip ist nicht installiert - kein .zip-Archiv erzeugt (der Ordner selbst ist trotzdem direkt nutzbar)."
    fi

    log "Erzeuge $BUILD_NAME.tar.gz"
    rm -f "$BUILD_NAME.tar.gz"
    tar -czf "$BUILD_NAME.tar.gz" "$BUILD_NAME"
)

log "Fertig: $TARGET_DIR"
log "Hochladen: entweder den Ordner direkt (FTP/rsync) oder eines der Archive aus $UPLOAD_DIR verwenden."
log "Danach auf dem Server im hochgeladenen Verzeichnis ausführen: ./install.sh"
