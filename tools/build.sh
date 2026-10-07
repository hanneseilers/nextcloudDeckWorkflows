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
# - Copies tools/install.sh to the root of the build output, so it's right
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

# -- PHP-Abhängigkeiten bündeln -------------------------------------------------

if command -v composer >/dev/null 2>&1; then
    log "Installiere PHP-Abhängigkeiten (composer install --no-dev) ..."
    if ! (cd "$TARGET_DIR/website" && composer install --no-dev --optimize-autoloader --no-interaction); then
        warn "composer install ist fehlgeschlagen - website/vendor/ fehlt im Build. install.sh versucht es serverseitig erneut."
    fi
else
    warn "composer ist nicht installiert - website/vendor/ fehlt im Build. install.sh versucht es serverseitig (falls composer dort verfügbar ist), sonst manuell nachholen."
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
