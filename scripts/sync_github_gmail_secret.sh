#!/usr/bin/env bash
# Copy token.json to clipboard for pasting into GitHub Actions secret GMAIL_TOKEN_JSON.
# Run after: python email_agent.py --once  (or whenever you re-authenticate Gmail)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOKEN="$ROOT/token.json"

if [[ ! -f "$TOKEN" ]]; then
  echo "Error: $TOKEN not found." >&2
  echo "Run locally first: venv/bin/python3 email_agent.py --once" >&2
  exit 1
fi

python3 -c "import json; json.load(open('$TOKEN'))" || {
  echo "Error: token.json is not valid JSON" >&2
  exit 1
}

if command -v pbcopy >/dev/null 2>&1; then
  pbcopy < "$TOKEN"
  echo "✓ token.json copied to clipboard."
else
  echo "pbcopy not found — paste this file manually:"
  echo "  $TOKEN"
fi

echo ""
echo "Update GitHub secret:"
echo "  1. https://github.com/poulsbopete/email-agent/settings/secrets/actions"
echo "  2. GMAIL_TOKEN_JSON → Update secret → paste → Save"
echo ""
echo "Optional (helps token refresh in CI):"
echo "  GMAIL_CREDENTIALS_JSON ← full contents of credentials.json"
echo ""
echo "Then: Actions → Hourly email agent → Run workflow"
echo "Check logs for: Gmail API authenticated as poulsbopete@gmail.com"
