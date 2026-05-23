#!/usr/bin/env bash
# Install hourly launchd job for the email agent.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_NAME="com.email.agent.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_DIR="$HOME/Library/Logs/email-agent"
TEMPLATE="$SCRIPT_DIR/launchd/com.email.agent.plist.template"

mkdir -p "$LOG_DIR"
mkdir -p "$HOME/Library/LaunchAgents"

# Prefer project venv Python, fall back to python3 on PATH
if [[ -x "$SCRIPT_DIR/venv/bin/python3" ]]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python3"
else
    PYTHON="$(command -v python3)"
fi

if [[ ! -f "$TEMPLATE" ]]; then
    echo "Error: template not found at $TEMPLATE" >&2
    exit 1
fi

sed \
    -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__SCRIPT__|$SCRIPT_DIR/email_agent.py|g" \
    -e "s|__WORKDIR__|$SCRIPT_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$TEMPLATE" > "$PLIST_DEST"

echo "Installed: $PLIST_DEST"
echo "  Python:  $PYTHON"
echo "  Script:  $SCRIPT_DIR/email_agent.py"
echo "  Logs:    $LOG_DIR/"

# Reload if already loaded
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"
launchctl enable "gui/$(id -u)/$PLIST_NAME"

echo ""
echo "Hourly job loaded. Commands:"
echo "  launchctl kickstart -k gui/$(id -u)/$PLIST_NAME   # run now"
echo "  tail -f $LOG_DIR/email-agent.log                 # watch logs"
echo "  launchctl bootout gui/$(id -u)/$PLIST_NAME       # uninstall"
