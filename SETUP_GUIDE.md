# Autonomous Email Agent Setup Guide

An AI-powered agent that checks your Gmail inbox **every hour** (via macOS launchd) to:
- ✅ Archive promotional/marketing emails
- ✅ Respond to general emails (send or draft, configurable)
- ✅ Mark newsletters and service notifications as read
- ✅ iMessage you when unsure how to respond (needs your input)

## Prerequisites

- Python 3.8+ installed on your laptop
- An active Gmail account
- An Anthropic API key (from https://console.anthropic.com)
- A Google Cloud project with Gmail API enabled

## Step 1: Get Your Anthropic API Key

1. Go to https://console.anthropic.com
2. Sign in or create an account
3. Navigate to **API Keys** in the left sidebar
4. Click **Create Key** and copy it
5. Save it somewhere safe - you'll need it next

## Step 2: Set Up Google Cloud Project and Gmail API

### 2a. Create a Google Cloud Project
1. Go to https://console.cloud.google.com
2. Click the project dropdown at the top
3. Click **NEW PROJECT**
4. Name it "Email Agent" and click **CREATE**
5. Wait a moment for the project to be created

### 2b. Enable Gmail API
1. In Google Cloud Console, go to **APIs & Services** > **Library**
2. Search for "Gmail API"
3. Click on **Gmail API**
4. Click the **ENABLE** button
5. You'll be redirected to the Gmail API page

### 2c. Configure Google Auth Platform (OAuth consent)

Google moved OAuth consent settings from **APIs & Services → OAuth consent screen** to **Google Auth Platform**. Use this path — the old wizard is easy to miss or configure incompletely.

**Required Gmail scope for this app:** `https://www.googleapis.com/auth/gmail.modify` (read, send, and modify mail).

1. Open [Google Cloud Console](https://console.cloud.google.com) and select your **Email Agent** project (top bar project picker — must match the project where you create credentials in step 2d).
2. In the left navigation, open **Google Auth Platform** (hamburger menu ☰ if collapsed).
   - If you do not see it, search the top search bar for **Google Auth Platform** or go to **APIs & Services → OAuth consent screen** and click **Get started** / **Configure consent screen** — Google redirects to the new UI.
3. **Branding** (Google Auth Platform → **Branding**):
   - App name: `Email Agent`
   - User support email: your Gmail address
   - Developer contact email: your Gmail address
   - Click **Save** at the bottom if you changed anything.
   - *What you should see:* App name "Email Agent" on the consent screen when you sign in.
4. **Audience** (Google Auth Platform → **Audience**) — **this is the step that fixes Error 403**:
   - **User type:** External (required for personal Gmail accounts).
   - **Publishing status:** must be **Testing** (not **In production**). Personal use stays in Testing; you do not need Google verification.
   - Scroll to **Test users** → click **Add users** (or **+ ADD USERS**).
   - Enter the **exact** Google account you will use in the browser, e.g. `poulsbopete@gmail.com`.
   - Click **Save** on the test-user dialog, then **Save** again on the Audience page if shown.
   - *What you should see:* Your email listed under Test users; Publishing status = Testing.
5. **Data Access** (Google Auth Platform → **Data Access**):
   - Click **Add or remove scopes**.
   - Filter for **Gmail API** and add **`.../auth/gmail.modify`** (full scope name: `https://www.googleapis.com/auth/gmail.modify`).
   - Save scopes, then **Save** on the Data Access page.
   - *What you should see:* `gmail.modify` listed under your app's scopes.

Wait ~1 minute after saving test users before running the agent.

### 2d. Create OAuth 2.0 Desktop credentials

1. Go to **APIs & Services** → **Credentials** (same **Email Agent** project as above).
2. Click **+ CREATE CREDENTIALS** → **OAuth client ID**.
3. Application type: **Desktop app** (shown as "Desktop application" in some views).
4. Name: `Email Agent Desktop` → **Create**.
5. Download the JSON (download icon on the credential row).
   - Google names the file `client_secret_….json` — that is fine.
   - Save it as `credentials.json` in the project directory, **or** set `GMAIL_CREDENTIALS_FILE` in `.env` to its path.
   - See `credentials.example.json` for the expected structure (`"installed"` key with `client_id`, `project_id`, etc.).
   - **Keep this file private!** Do not commit it to git.

Validate locally (no secrets printed):

```bash
python3 scripts/check_gmail_credentials.py
```

## Step 3: Install the Email Agent

### 3a. Clone or download the agent files
```bash
# Create a directory for the agent
mkdir email-agent
cd email-agent

# Copy these files into the directory:
# - email_agent.py
# - requirements.txt
# - credentials.json (from Step 2c)
```

### 3b. Install Python dependencies
```bash
# Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 3c. Set your API key
```bash
# Linux/Mac
export ANTHROPIC_API_KEY="your-api-key-here"

# Windows (PowerShell)
$env:ANTHROPIC_API_KEY="your-api-key-here"
```

Or create a `.env` file (see `.env.example`):
```
ANTHROPIC_API_KEY=your-api-key-here
IMESSAGE_NOTIFY_TO=+15551234567
# AUTO_SEND_RESPONSES=false   # create drafts instead of sending
# GMAIL_CREDENTIALS_FILE=credentials.json
# GMAIL_TOKEN_FILE=token.json
```

## Step 4: Run the Agent

### First Run - Gmail Authorization
On first run, the agent will open a browser window asking you to authorize access to your Gmail:

```bash
python3 email_agent.py --once
```

1. A browser will open (may take a moment)
2. Select your personal Gmail account
3. Review the permissions and click **Allow**
4. The browser will show "The authentication flow has completed"
5. Close the browser and return to your terminal

The agent will save your credentials in `token.json` for future runs.

### Subsequent Runs
Run one inbox check manually:
```bash
python3 email_agent.py --once
```

Preview without Gmail credentials:
```bash
python3 email_agent.py --once --dry-run
```

Test iMessage notifications:
```bash
python3 email_agent.py --test-imessage
```

Each run will:
1. ✅ Fetch unread primary inbox emails
2. ✅ Classify each with Claude
3. ✅ Archive promotions, respond to general mail, or iMessage you when unsure

## Step 5: Hourly Scheduling (Recommended — macOS)

Install the hourly launchd job:

```bash
chmod +x scripts/install_launchd.sh
./scripts/install_launchd.sh
```

See **[SCHEDULING.md](SCHEDULING.md)** for full details, logs, and troubleshooting.

### Legacy: Continuous daemon mode
```bash
CHECK_INTERVAL=300 python3 email_agent.py --daemon
```

### Windows Task Scheduler
1. Open **Task Scheduler**
2. Click **Create Basic Task**
3. Name: "Email Agent"
4. Trigger: "At startup" or "On a schedule"
5. Action: Start a program
   - Program: `C:\Python310\python.exe` (your Python path)
   - Arguments: `C:\path\to\email_agent.py`
6. Click **Finish**

## Configuration

### Email Response Rules

| Classification | Agent Action | What Happens |
|---|---|---|
| **Promotion/Marketing** | Archive | Removed from inbox |
| **Newsletter/Digest** | Mark Read | Stays in inbox, marked read |
| **Service Notification** | Mark Read | No reply needed |
| **General** | Respond | Sends reply or creates draft (`AUTO_SEND_RESPONSES`) |
| **Needs user input** | Queue + iMessage | Flags IMPORTANT, saves to `pending_review.json`, texts you |

### Auto-Response Examples

**Personal Email:**
```
Thanks for reaching out! I'll get back to you soon.
```

**Recruiter Email:**
```
Thanks for your interest! Please contact my work email for professional inquiries.
```

**o11ybot Support:**
```
Thanks for reporting this! We're looking into [the issue] and will follow up soon.
```

### Auto-send vs drafts
By default, general email replies are saved as **Gmail drafts** for your review:

```bash
AUTO_SEND_RESPONSES=true   # in .env — send replies automatically
```

### iMessage notifications
Set `IMESSAGE_NOTIFY_TO` in `.env` to your phone number or Apple ID email. The Messages app must be signed in on this Mac.

### Email Categories Handled

The agent recognizes and handles:
- **promotion** - Sales pitches, ads, marketing → Auto-archived
- **newsletter** - Newsletters, digests, roundups → Auto-marked read
- **service_notification** - Confirmations, alerts, resets → Auto-marked read
- **personal** - Friends, family, acquaintances → Auto-responds (friendly) + Flags
- **recruiter** - Job offers, recruiters, hiring → Auto-responds (polite) + Flags
- **o11ybot_support** - Bug reports, feature requests, support for o11ybot → Auto-responds (helpful) + Notifies you
- **other_support** - General support requests, inquiries → Flags for review (waits for you)
- **other** - Anything unclassified → Flags for review

## Troubleshooting

### "ModuleNotFoundError: No module named 'anthropic'"
You haven't installed the requirements:
```bash
pip install -r requirements.txt
```

### "Gmail OAuth credentials file not found" / FileNotFoundError: credentials.json
- Download OAuth client secrets from Google Cloud Console (Desktop application)
- Save as `credentials.json` in the project directory, or set `GMAIL_CREDENTIALS_FILE` in `.env` to the downloaded path (Google often names the file `client_secret_….json` — no need to rename if you set the env var)
- See `credentials.example.json` and Step 2c above

### "Access blocked: Email Agent has not completed the Google verification process" (Error 403: access_denied)

This is **not a code bug**. Google blocked sign-in because your account is not allowed to use the app yet.

Typical messages:
- *Access blocked: Email Agent has not completed the Google verification process*
- *Error 403: access_denied*
- *App is in testing mode, can only be accessed by developer-approved testers*

**Fix checklist (do in order):**

1. **Same Google Cloud project as `credentials.json`**
   - Run `python3 scripts/check_gmail_credentials.py` and note the **project_id** (e.g. `email-agent-497113`).
   - In [Cloud Console](https://console.cloud.google.com), confirm the top-bar project is **Email Agent** / that same project ID — not a different project where you only created credentials.

2. **Google Auth Platform → Audience**
   - **Publishing status:** **Testing** (if **In production** and unverified, everyone gets blocked — switch back to Testing for personal use).
   - **Test users:** must include the **exact** account you pick in the browser (e.g. `poulsbopete@gmail.com`).
   - Click **Save** after adding users (easy to add an email but forget to save).

3. **Google Auth Platform → Data Access**
   - Scope **`https://www.googleapis.com/auth/gmail.modify`** must be listed (Gmail API → gmail.modify).

4. **Google Auth Platform → Branding**
   - App name should match what you see on the error screen ("Email Agent").

5. **Browser account**
   - When the auth URL opens, choose the same Gmail listed as a test user — not a Workspace account or another personal account.

6. **Retry auth** (creates `token.json` on success):
   ```bash
   cd /Users/psimkins/email-agent
   source venv/bin/activate
   python3 email_agent.py --once
   ```
   Complete the browser flow; do not Ctrl+C the terminal while waiting. You should see "The authentication flow has completed" in the browser.

7. **Confirm success:** `token.json` appears in the project directory (gitignored).

**Common mistakes**

| Mistake | What happens |
|--------|----------------|
| Wrong GCP project selected in console | Test user added to a different project than `credentials.json` |
| Added test user but did not click **Save** | Google never stores the test user |
| Signed in with a different Google account than the test user | 403 access_denied |
| App set to **In production** without verification | Blocked for all non-verified users |
| Used **Web application** OAuth client instead of **Desktop** | Auth flow may fail or behave oddly |
| Interrupted first auth (Ctrl+C) before browser finished | No `token.json`; must run `--once` again after fixing test users |

**For personal use:** Keep **Testing** + test users. You do **not** need Google verification unless unrelated people will sign in (Production for the public).

### "Gmail API authentication failed"
- Delete `token.json` and run again to re-authenticate
- Ensure your Google Cloud project has Gmail API enabled
- Verify `credentials.json` is in the correct directory

### Agent not responding to emails
The agent is designed to be conservative - it only auto-responds to obvious marketing and digest emails. Personal emails are flagged for your review.

Check the logs for why an email was classified as "flag_for_review"

### Running multiple agents
You can run separate agent instances for different email accounts:
```bash
# Agent 1 - personal email
ANTHROPIC_API_KEY=key1 python3 email_agent.py --config personal.env

# Agent 2 - work email (in separate terminal)
ANTHROPIC_API_KEY=key2 python3 email_agent.py --config work.env
```

## Privacy & Security

⚠️ **Important Security Notes:**

1. **credentials.json** - This file grants API access to your Gmail
   - Keep it private
   - Don't commit to public repos
   - Delete if you stop using the agent

2. **token.json** - Auto-generated refresh token
   - Also sensitive
   - Keep it private

3. **API Key** - Your Anthropic key
   - Keep it secret
   - Use environment variables, not hardcoded values
   - Never commit to version control

4. **Email Content** - Claude API sees email content
   - Anthropic doesn't store conversations by default
   - Review Anthropic's privacy policy at https://www.anthropic.com/privacy

## Support & Customization

The agent is fully customizable. You can modify:
- Email analysis criteria (in `analyze_and_act_on_email()`)
- Actions (add custom responses, create filters, forward emails, etc.)
- Claude model used (currently Opus, but can use Sonnet for cost savings)

For advanced features, check the Claude API documentation:
https://docs.claude.com/en/docs_site_map.md

## Stopping the Agent

Press **Ctrl+C** in the terminal where it's running.

If running via launchctl (Mac), use:
```bash
launchctl bootout gui/$(id -u)/com.email.agent
```

---

**Questions?** Check the Claude documentation or ask in the Anthropic community forum.
