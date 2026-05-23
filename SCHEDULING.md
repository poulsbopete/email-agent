# Hourly Scheduling (macOS launchd)

The email agent is designed to run **once per hour** via macOS `launchd`, not as an infinite daemon loop.

**Recommended runtime:** GitHub Actions (see [CLOUD_HOSTING.md](CLOUD_HOSTING.md)). Use launchd when you want local scheduling on a Mac.

## Quick install

```bash
cd ~/email-agent
chmod +x scripts/install_launchd.sh
./scripts/install_launchd.sh
```

This installs `~/Library/LaunchAgents/com.email.agent.plist` to run:

**launchctl service name:** use the plist **Label** `com.email.agent`, not the filename `com.email.agent.plist`.

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
```

## Prerequisites before scheduling

1. **Gmail OAuth** — `credentials.json` (or `GMAIL_CREDENTIALS_FILE`) and first-run auth to create `token.json`
2. **Anthropic API key** — in `.env` as `ANTHROPIC_API_KEY`

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

When the agent needs your input, look for `NEEDS USER INPUT` blocks in these logs. Emails are also flagged with the Gmail **IMPORTANT** label.

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
| No credentials yet | Use `--dry-run` to preview; complete Gmail setup from SETUP_GUIDE.md |

See also [SETUP_GUIDE.md](SETUP_GUIDE.md) for Gmail and API setup.

## Cloud / interim hosting (recommended)

For hourly triage without a Mac mini, use **GitHub Actions** — see **[CLOUD_HOSTING.md](CLOUD_HOSTING.md)**. Review items appear in the Actions run summary and job logs.
