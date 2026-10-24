#!/usr/bin/env bash
#
# Konfiguration von Nextcloud Deck Workflows: liest config/nextcloud.yaml,
# settings.yaml und smtp.yaml und führt Wert für Wert durch den Dialog. Schon
# gesetzte Werte werden zur Übernahme angeboten (Enter), fehlende mit ihrem
# Standardwert vorgeschlagen. Geschrieben wird immer die vollständige Datei
# mit allen Werten und einer Erklärung je Wert.
#
#   ./configure.sh                  alle Dateien durchgehen
#   ./configure.sh settings         nur config/settings.yaml (auch: nextcloud, smtp)
#   ./configure.sh --missing        nur Werte abfragen, die noch fehlen (z. B. nach einem Update)
#   ./configure.sh --get settings.public_url   einen Wert ausgeben
#
# Wird auch von install.sh benutzt. Die Logik steckt in automation/config/configure.py.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Im Upload-Paket liegt dieses Skript im Projekt-Wurzelverzeichnis, im
# Repository in tools/.
if [ -d "$HERE/automation" ]; then
    PROJECT_ROOT="$HERE"
else
    PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
fi
cd "$PROJECT_ROOT" || exit 1

# Derselbe Interpreter wie für die Automation: von install.sh übergeben,
# sonst das venv (automation/.venv oder .venv), sonst python3.
PYTHON_BIN="${NCDW_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
    for candidate in "$PROJECT_ROOT/automation/.venv/bin/python" "$PROJECT_ROOT/.venv/bin/python"; do
        if [ -x "$candidate" ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "FEHLER: Python ('$PYTHON_BIN') nicht gefunden - ohne Python lässt sich die Konfiguration nicht bearbeiten." >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c "import yaml" >/dev/null 2>&1 && [ ! -d "$PROJECT_ROOT/automation/vendor" ]; then
    echo "FEHLER: Python-Paket 'yaml' fehlt - erst die Abhängigkeiten installieren (./install.sh oder pip install -r automation/requirements.txt)." >&2
    exit 1
fi

exec "$PYTHON_BIN" -m automation.config.configure "$@"
