# Hourly Scheduling (macOS launchd)

The email agent is designed to run **once per hour** via macOS `launchd`, not as an infinite daemon loop.

## Quick install

```bash
cd ~/email-agent
chmod +x scripts/install_launchd.sh
./scripts/install_launchd.sh
```

This installs `~/Library/LaunchAgents/com.email.agent.plist` to run:

```bash
/path/to/venv/bin/python3 /path/to/email-agent/email_agent.py --once
```

every **3600 seconds** (1 hour).

## Manual run (testing)

```bash
# One cycle, real Gmail
python3 email_agent.py --once

# Preview without Gmail credentials
python3 email_agent.py --once --dry-run

# Test iMessage only
python3 email_agent.py --test-imessage
```

## Prerequisites before scheduling

1. **Gmail OAuth** — `credentials.json` (or `GMAIL_CREDENTIALS_FILE`) and first-run auth to create `token.json`
2. **Anthropic API key** — in `.env` as `ANTHROPIC_API_KEY`
3. **iMessage recipient** — in `.env` as `IMESSAGE_NOTIFY_TO` (your phone or Apple ID email)
4. **Messages app** — signed in on this Mac

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

## launchd management

| Action | Command |
|--------|---------|
| Run immediately | `launchctl kickstart -k gui/$(id -u)/com.email.agent` |
| View stdout log | `tail -f ~/Library/Logs/email-agent/email-agent.log` |
| View errors | `tail -f ~/Library/Logs/email-agent/email-agent-error.log` |
| Uninstall | `launchctl bootout gui/$(id -u)/com.email.agent` |

## Logs

- stdout: `~/Library/Logs/email-agent/email-agent.log`
- stderr: `~/Library/Logs/email-agent/email-agent-error.log`

launchd does not load `.env` automatically, but `email_agent.py` reads `.env` from the project directory on each run.

## iMessage automation permissions

The first time launchd (or Terminal) sends an iMessage, macOS may prompt for **Automation** permission:

**System Settings → Privacy & Security → Automation** → allow Terminal (or `python3`) to control **Messages**.

If iMessage fails silently from launchd, grant automation to the Python binary or run a manual test first:

```bash
python3 email_agent.py --test-imessage
```

## Legacy daemon mode

If you prefer a continuous loop instead of hourly launchd:

```bash
CHECK_INTERVAL=300 python3 email_agent.py --daemon
```

This is not recommended for laptop use — launchd + `--once` is more battery-friendly.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Job not running | `launchctl print gui/$(id -u)/com.email.agent` |
| Gmail auth in launchd | Run `python3 email_agent.py --once` interactively once to create `token.json` |
| iMessage not delivered | Check `IMESSAGE_NOTIFY_TO`, Messages signed in, Automation permission |
| No credentials yet | Use `--dry-run` to preview; complete Gmail setup from SETUP_GUIDE.md |

See also [SETUP_GUIDE.md](SETUP_GUIDE.md) for Gmail and API setup.

## Cloud / interim hosting (no Mac mini yet)

launchd and iMessage require macOS. Until you have a Mac mini, run `email_agent.py --once` on a schedule via GitHub Actions or another cron host — see **[CLOUD_HOSTING.md](CLOUD_HOSTING.md)**.
