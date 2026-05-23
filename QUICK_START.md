# Email Agent - Quick Start

## What This Does
An AI agent checks your Gmail **every hour** and:
- 🚫 Archives promotional/marketing emails
- 💬 Responds to general emails (draft or send)
- 📱 iMessages you when it needs your input on how to reply
- 📰 Marks newsletters and notifications as read

## Installation (5 minutes)

### 1. Get Your Anthropic API Key
```
Visit: https://console.anthropic.com
Click: API Keys → Create Key
Copy: Your key
```

### 2. Set Up Gmail API
```
Visit: https://console.cloud.google.com
Create a new project → Enable Gmail API
Create OAuth 2.0 credentials (Desktop app)
Download as credentials.json (or client_secret.json)
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, IMESSAGE_NOTIFY_TO
pip install -r requirements.txt
```

### 4. First run (Gmail authorization)
```bash
python3 email_agent.py --once
```

## Hourly scheduling (macOS)

```bash
chmod +x scripts/install_launchd.sh
./scripts/install_launchd.sh
```

See **SCHEDULING.md** for logs and troubleshooting.

## Commands

| Command | Purpose |
|---------|---------|
| `python3 email_agent.py --once` | One inbox check |
| `python3 email_agent.py --once --dry-run` | Preview with mock emails |
| `python3 email_agent.py --test-imessage` | Test iMessage notification |
| `python3 email_agent.py --daemon` | Legacy continuous loop |

## How It Works

```
Promotion          → Archive
Newsletter         → Mark read
Service alert      → Mark read
General email      → Reply (draft or send)
Unclear/sensitive  → iMessage you + queue in pending_review.json
```

## File Structure
```
email-agent/
├── email_agent.py          ← Main agent
├── imessage.py             ← iMessage via AppleScript
├── scripts/install_launchd.sh
├── launchd/com.email.agent.plist.template
├── SCHEDULING.md           ← Hourly launchd setup
├── SETUP_GUIDE.md          ← Full setup
├── .env.example
├── credentials.json        ← Gmail OAuth (keep secret)
└── pending_review.json     ← Queued emails needing input
```

## Security

🔒 Keep private: `credentials.json`, `token.json`, `.env`, `client_secret.json`

Never commit these to git!
