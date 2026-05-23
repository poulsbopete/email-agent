# Email Agent

An AI-powered Gmail triage agent that checks your inbox **every hour** and handles routine email automatically. It archives promotions, drafts or sends replies to general mail, marks newsletters and notifications as read, and texts you via iMessage when it needs your input.

Built for macOS with Python, the [Gmail API](https://developers.google.com/gmail/api), [Claude](https://www.anthropic.com/) for classification, and Apple Messages for notifications.

## Features

- **Archive promotions** — Marketing, sales, and bulk mail are removed from your inbox
- **Respond to general email** — Creates Gmail drafts by default, or sends replies automatically when configured
- **Mark read** — Newsletters and service notifications stay in the inbox but are marked read
- **iMessage when unsure** — Ambiguous or sensitive emails are flagged, queued in `pending_review.json`, and summarized in an iMessage
- **Hourly scheduling** — Runs once per hour via macOS `launchd` (recommended), or manually on demand

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.10+** | Virtual environment recommended |
| **Gmail API OAuth** | Google Cloud project with Desktop OAuth credentials |
| **Anthropic API key** | From [console.anthropic.com](https://console.anthropic.com) |
| **macOS** | Required for iMessage notifications (Gmail triage works on any OS, but iMessage does not) |

## Quick start

### 1. Install dependencies

```bash
cd email-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Use the venv when you run the agent.** Either keep the shell where you ran `source venv/bin/activate`, or call the interpreter explicitly: `venv/bin/python3 email_agent.py ...`. Plain `python3` without the venv (common on macOS: `/usr/bin/python3` 3.9) does not have project packages such as `anthropic`.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `ANTHROPIC_API_KEY` — your Anthropic API key
- `IMESSAGE_NOTIFY_TO` — your phone number or Apple ID email (macOS only)

See [Configuration](#configuration) for all options.

### 3. Add Gmail OAuth credentials

Download OAuth 2.0 client secrets from Google Cloud Console (Desktop application) and save as `credentials.json` in the project directory. See [Gmail OAuth setup](#gmail-oauth-setup) or [SETUP_GUIDE.md](SETUP_GUIDE.md) for step-by-step instructions.

### 4. First run (Gmail authorization)

```bash
python3 email_agent.py --once
```

On first run, a browser window opens for Gmail authorization. After you approve access, the agent saves a refresh token to `token.json` for future runs.

### 5. Test

```bash
# Preview classification without touching Gmail
python3 email_agent.py --once --dry-run

# Verify iMessage notifications (macOS)
python3 email_agent.py --test-imessage
```

### 6. Install hourly scheduling (macOS)

```bash
chmod +x scripts/install_launchd.sh
./scripts/install_launchd.sh
```

This installs a `launchd` job that runs `email_agent.py --once` every hour. See [Scheduling](#scheduling) and [SCHEDULING.md](SCHEDULING.md) for logs and troubleshooting.

## Configuration

The agent reads `.env` from the project directory on each run. Copy [.env.example](.env.example) to get started.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for email classification and reply drafting |
| `IMESSAGE_NOTIFY_TO` | For iMessage | — | Phone number (`+15551234567`) or Apple ID email of an existing Messages contact |
| `AUTO_SEND_RESPONSES` | No | `false` | `true` to send replies automatically; `false` to create Gmail drafts |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-20250514` | Claude model used for analysis |
| `MAX_EMAILS_PER_RUN` | No | `10` | Maximum unread emails processed per run |
| `GMAIL_CREDENTIALS_FILE` | No | `credentials.json` | Path to Gmail OAuth client secrets JSON |
| `GMAIL_TOKEN_FILE` | No | `token.json` | Path to saved OAuth refresh token (created on first auth) |
| `GMAIL_CREDENTIALS_JSON` | No | — | Full client secrets JSON string (CI/cloud; written to `GMAIL_CREDENTIALS_FILE` path) |
| `GMAIL_TOKEN_JSON` | No | — | Full token JSON string (CI/cloud; written to `GMAIL_TOKEN_FILE` path) |
| `CHECK_INTERVAL` | No | `300` | Seconds between checks in legacy `--daemon` mode only |

## Usage

```bash
# One inbox check (default; used by launchd)
python3 email_agent.py --once

# Preview actions with mock emails (no Gmail changes)
python3 email_agent.py --once --dry-run

# Send a test iMessage and exit
python3 email_agent.py --test-imessage

# Legacy: run continuously in a loop (prefer launchd + --once)
python3 email_agent.py --daemon

# Process fewer/more emails per run
python3 email_agent.py --once --max-emails 5
```

### How emails are handled

| Classification | Action |
|----------------|--------|
| Promotion / marketing | Archive (removed from inbox) |
| Newsletter / digest | Mark read |
| Service notification | Mark read |
| General personal or professional | Draft or send a reply |
| Unclear or sensitive | Flag IMPORTANT, queue in `pending_review.json`, iMessage you |

By default, the agent is conservative: when unsure how to reply, it asks you rather than guessing.

## Gmail OAuth setup

You need a Google Cloud project with the Gmail API enabled and OAuth 2.0 credentials for a **Desktop application**.

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project and enable the **Gmail API**
3. Configure the OAuth consent screen (External; add yourself as a test user)
4. Create **OAuth 2.0 credentials** → Desktop application
5. Download the JSON file — Google may name it `client_secret_….json`. Save it as `credentials.json` in the project directory, or set `GMAIL_CREDENTIALS_FILE` in `.env` to point at the downloaded file

The expected file format is shown in [credentials.example.json](credentials.example.json).

On first run, the agent opens a browser for authorization and writes `token.json`. If auth fails later, delete `token.json` and run `--once` again.

### OAuth troubleshooting

| Error | Fix |
|-------|-----|
| **403 access_denied** — "Access blocked" / "App is in testing mode" | Add your Google account under **OAuth consent screen → Test users** (or **Google Auth Platform → Audience**). Use the exact account you sign in with. See [SETUP_GUIDE.md — Error 403](SETUP_GUIDE.md#access-blocked-email-agent-has-not-completed-the-google-verification-process-error-403-access_denied). |
| **credentials.json not found** | Rename the downloaded client secret to `credentials.json`, or set `GMAIL_CREDENTIALS_FILE` in `.env` |
| **Auth expired / invalid** | Delete `token.json` and run `venv/bin/python3 email_agent.py --once` again |

For personal use, **Testing** mode with test users is sufficient — no Google verification required unless you publish the app publicly.

For detailed screenshots and troubleshooting, see **[SETUP_GUIDE.md](SETUP_GUIDE.md)**.

## iMessage setup and limitations

Notifications are sent through the macOS **Messages** app via AppleScript (`imessage.py`).

**Setup:**

1. Set `IMESSAGE_NOTIFY_TO` in `.env` to a phone number or Apple ID email that already has an iMessage conversation on this Mac
2. Sign in to Messages on the Mac running the agent
3. Run `python3 email_agent.py --test-imessage` to verify delivery
4. Grant **Automation** permission if prompted: **System Settings → Privacy & Security → Automation** → allow Terminal or Python to control **Messages**

**Limitations:**

- macOS only — iMessage is skipped on other platforms
- Requires Messages signed in and an existing contact/conversation for the recipient
- launchd runs may fail silently without Automation permission; test interactively first
- The agent sends a summary and question; you reply in Gmail or tell the agent how to respond

## Scheduling

The recommended setup is **hourly `launchd` + `--once`**, not a long-running daemon. This is more battery-friendly on a laptop.

```bash
chmod +x scripts/install_launchd.sh
./scripts/install_launchd.sh
```

The installer:

- Writes `~/Library/LaunchAgents/com.email.agent.plist`
- Runs every **3600 seconds** (1 hour) and once at load
- Logs to `~/Library/Logs/email-agent/`

Useful commands:

```bash
launchctl kickstart -k gui/$(id -u)/com.email.agent   # run now
tail -f ~/Library/Logs/email-agent/email-agent.log    # watch logs
launchctl bootout gui/$(id -u)/com.email.agent        # uninstall
```

Complete details, prerequisites, and troubleshooting: **[SCHEDULING.md](SCHEDULING.md)**.

### Running before you have a Mac mini (GitHub Actions)

If you do not have always-on Mac hardware yet, use the included **GitHub Actions** workflow for hourly Gmail triage:

1. Complete Gmail OAuth once locally (`python email_agent.py --once`) to create `token.json`
2. Push the repo to GitHub and enable **Actions**
3. Add secrets: `ANTHROPIC_API_KEY`, `GMAIL_TOKEN_JSON`, and optionally `GMAIL_CREDENTIALS_JSON`
4. Test with **Actions → Hourly email agent → Run workflow**

Gmail and Claude work in CI; **iMessage does not**. Use a direct Anthropic API key in GitHub (not a local LiteLLM proxy). Full step-by-step instructions, cron details, token refresh, and troubleshooting: **[CLOUD_HOSTING.md — GitHub Actions setup](CLOUD_HOSTING.md#github-actions-setup-step-by-step)**.

## Security

Never commit secrets to version control. Keep these files private:

| File | Purpose |
|------|---------|
| `.env` | API keys and configuration |
| `credentials.json` / `client_secret.json` | Gmail OAuth client secrets |
| `token.json` | Gmail OAuth refresh token (auto-generated) |

These paths are listed in `.gitignore`. Email content is sent to the Anthropic API for classification; review [Anthropic's privacy policy](https://www.anthropic.com/privacy) if that matters for your use case.

## Project structure

```
email-agent/
├── email_agent.py              # Main CLI and Gmail agent
├── imessage.py                 # iMessage notifications via AppleScript
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
├── credentials.example.json    # Gmail OAuth file format reference
├── scripts/
│   └── install_launchd.sh      # Install hourly launchd job
├── launchd/
│   └── com.email.agent.plist.template
├── SETUP_GUIDE.md              # Full Gmail and API setup
├── QUICK_START.md              # Minimal install reference
└── SCHEDULING.md               # launchd scheduling details
```

Runtime files (not in git): `.env`, `credentials.json`, `token.json`, `pending_review.json`.

## Documentation

| Doc | Description |
|-----|-------------|
| [QUICK_START.md](QUICK_START.md) | Minimal 5-minute install checklist |
| [SETUP_GUIDE.md](SETUP_GUIDE.md) | Full Gmail OAuth, API keys, and troubleshooting |
| [SCHEDULING.md](SCHEDULING.md) | Hourly launchd setup, logs, and management |
| [CLOUD_HOSTING.md](CLOUD_HOSTING.md) | GitHub Actions setup (step-by-step), cloud cron, Mac mini migration |

## License

Private project — use and modify for your own inbox.
