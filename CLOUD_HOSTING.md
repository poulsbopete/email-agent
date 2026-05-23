# Cloud and interim hosting

The recommended long-term setup is a **Mac mini** with hourly **launchd** ([SCHEDULING.md](SCHEDULING.md)) so you get Gmail triage **and** iMessage notifications. Until that hardware is ready, you can run the same `email_agent.py --once` cycle in the cloud or on any machine you leave on.

## What transfers vs what breaks

| Component | Local Mac (launchd) | Cloud / CI |
|-----------|---------------------|------------|
| Gmail OAuth (`--once`) | Browser auth once → `token.json` | Pre-auth locally; store token in secrets (`GMAIL_TOKEN_JSON`) |
| Claude / Anthropic | `ANTHROPIC_API_KEY` in `.env` | Same — set host secret; no LiteLLM proxy required |
| LiteLLM proxy (`localhost:4001`) | Optional local routing | **Not used** — call Anthropic directly in cloud |
| iMessage alerts | Works via AppleScript | **Does not work** — macOS Messages only |
| `pending_review.json` | Persists on disk | Ephemeral unless you add storage (artifact, S3, etc.) |

Ambiguous emails are still flagged in Gmail and queued in `pending_review.json` for that run; you just will not get an iMessage ping until you move back to a Mac.

## Option comparison (ranked)

| Option | Cost | Feasibility | Gmail | Claude | iMessage | OAuth path |
|--------|------|-------------|-------|--------|----------|------------|
| **GitHub Actions cron** | Free tier | ★★★★★ Best free interim | ✅ | ✅ | ❌ | Local auth once → `GMAIL_TOKEN_JSON` secret |
| **Keep laptop on + launchd** | Free | ★★★★★ If machine available | ✅ | ✅ | ✅ | Same as today |
| **Railway / Render / Fly.io cron** | ~$0–7/mo | ★★★★ | ✅ | ✅ | ❌ | Same secrets pattern as GHA |
| **Cloud Run + Scheduler / Lambda + EventBridge** | Pennies | ★★★ | ✅ | ✅ | ❌ | Same; more setup |
| **Cursor SDK cloud** | API usage | ★ Not for this | ❌ | N/A | ❌ | Wrong tool — see below |

### GitHub Actions (recommended interim)

**Pros:** Free, no server to maintain, matches `--once` + hourly schedule, workflow included at [.github/workflows/hourly-email.yml](.github/workflows/hourly-email.yml).

**Cons:** No iMessage; cron timing is UTC and can be delayed; `pending_review.json` does not persist between runs; public repos should use private repo or encrypted secrets only.

For full setup instructions, see **[GitHub Actions setup](#github-actions-setup-step-by-step)** below.

## GitHub Actions setup (step-by-step)

Use this when you want hourly Gmail triage **before** you have a Mac mini with launchd. The workflow runs the same command as local scheduling: `python email_agent.py --once`.

### What works vs what does not

| Feature | GitHub Actions | Mac + launchd |
|---------|----------------|-----------------|
| Gmail read / archive / draft | ✅ | ✅ |
| Claude classification | ✅ | ✅ |
| iMessage when unsure | ❌ | ✅ |
| `pending_review.json` persists | ❌ (ephemeral each run) | ✅ |
| OAuth browser flow in CI | ❌ (blocked when `CI=true`) | ✅ (first run only) |

Ambiguous emails are still flagged with the **IMPORTANT** label in Gmail. You just will not get an iMessage ping until you move to a Mac.

### Prerequisites

Before you start, confirm you have:

1. **Completed local setup** — dependencies installed, `.env` with `ANTHROPIC_API_KEY`, and `credentials.json` from Google Cloud. See [SETUP_GUIDE.md](SETUP_GUIDE.md) if not.
2. **Run Gmail OAuth once locally** — this creates `token.json` with a refresh token. GitHub Actions cannot open a browser for you.
3. **A GitHub repository** — this project pushed to GitHub (private repo recommended; secrets still apply).

### Step 1: Authorize Gmail locally (one time)

On your Mac, from the project directory:

```bash
cd ~/email-agent
source venv/bin/activate
python email_agent.py --once
```

Complete the browser sign-in. When it succeeds, you should see `token.json` in the project folder:

```bash
ls -la token.json
```

Keep this file private — it grants access to your Gmail.

### Step 2: Push the repo to GitHub

If the repo is not on GitHub yet:

```bash
cd ~/email-agent
git remote add origin git@github.com:YOUR_USERNAME/email-agent.git   # skip if already set
git push -u origin main
```

The workflow file is already in the repo: `.github/workflows/hourly-email.yml`. You do **not** need to copy it separately.

### Step 3: Enable GitHub Actions

1. Open your repo on GitHub (e.g. `https://github.com/YOUR_USERNAME/email-agent`).
2. Click the **Actions** tab.
3. If prompted, click **I understand my workflows, go ahead and enable them**.

You should see **Hourly email agent** in the left sidebar once Actions is enabled.

### Step 4: Create repository secrets

GitHub stores these encrypted. Never commit them to git.

1. Go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret** for each row below.

| Secret name | Required | What to paste | How to get the value |
|-------------|----------|---------------|----------------------|
| `ANTHROPIC_API_KEY` | **Yes** | Your Anthropic API key | [console.anthropic.com](https://console.anthropic.com) → **API Keys** → Create Key |
| `GMAIL_TOKEN_JSON` | **Yes** | Entire contents of `token.json` | See copy commands below |
| `GMAIL_CREDENTIALS_JSON` | Optional | Entire contents of `credentials.json` | Recommended if token refresh fails in CI |

**Copy `token.json` to clipboard (macOS):**

```bash
cd ~/email-agent
pbcopy < token.json
```

Then paste into the **Secret** field for `GMAIL_TOKEN_JSON`. The value should start with `{` and include `"refresh_token"`. Single-line or pretty-printed JSON both work.

**Copy `credentials.json` (optional but recommended):**

```bash
pbcopy < credentials.json
```

Paste into `GMAIL_CREDENTIALS_JSON`. This lets the agent refresh an expired access token in CI without a browser. If you omit it, refresh may still work when the token file alone contains enough metadata — but including credentials avoids some refresh failures.

**Verify secrets (without exposing values):**

```bash
# Confirm files exist locally before copying
test -f token.json && echo "token.json OK"
test -f credentials.json && echo "credentials.json OK"
python3 -c "import json; json.load(open('token.json')); print('token.json is valid JSON')"
```

### Step 5: Anthropic API — use a direct key, not LiteLLM

On your Mac you may route Claude through a local **LiteLLM** proxy (`ANTHROPIC_BASE_URL=http://localhost:4001`). **GitHub Actions cannot reach localhost on your Mac.**

In the `ANTHROPIC_API_KEY` secret, paste a **real Anthropic API key** from [console.anthropic.com](https://console.anthropic.com). Do **not** set `ANTHROPIC_BASE_URL` in the workflow — the agent calls Anthropic directly.

| Environment | Anthropic setup |
|-------------|-----------------|
| Local Mac (optional) | Direct key, or LiteLLM at `localhost:4001` |
| GitHub Actions | Direct `ANTHROPIC_API_KEY` only |

### Step 6: Manual test run (`workflow_dispatch`)

Always test manually before relying on the hourly cron.

1. Open **Actions → Hourly email agent**.
2. Click **Run workflow** (dropdown on the right).
3. Leave branch as `main` (or your default branch) and click the green **Run workflow** button.
4. Click the new run in the list, then open the **triage** job.
5. Expand **Run email agent (once)** and look for:
   - `✓ Gmail API authenticated`
   - `✓ Done — N action(s) taken` (N may be 0 if inbox is empty)

If the job fails, see [Troubleshooting](#troubleshooting-github-actions) below.

### Step 7: Hourly cron schedule

The workflow runs automatically on this schedule (defined in `.github/workflows/hourly-email.yml`):

```yaml
schedule:
  - cron: '5 * * * *'   # minute 5 of every hour, UTC
```

| Topic | Detail |
|-------|--------|
| **Timezone** | GitHub cron uses **UTC only**. `5 * * * *` = :05 past each hour UTC (e.g. 1:05 PM UTC = 6:05 AM Pacific during PST). |
| **Reliability** | Best-effort — runs can slip or be delayed when GitHub is under load. Do not treat it as exact wall-clock timing. |
| **Manual runs** | `workflow_dispatch` (Step 6) works anytime, independent of cron. |

To change the schedule, edit the `cron` line in `.github/workflows/hourly-email.yml` and push. [crontab.guru](https://crontab.guru) helps build cron expressions (remember: UTC).

### Step 8: When the Gmail token expires

Access tokens refresh automatically when possible. If refresh fails (revoked access, expired refresh token, or missing client secrets), the workflow logs:

```
Error: Gmail token missing or expired; interactive OAuth is unavailable here.
  Run locally once: python email_agent.py --once
  Then copy token.json into the GMAIL_TOKEN_JSON repository/CI secret.
```

**Fix:**

1. On your Mac, re-authenticate if needed:
   ```bash
   cd ~/email-agent
   source venv/bin/activate
   # If auth is broken, delete the old token first:
   # rm token.json
   python email_agent.py --once
   ```
2. Copy the new token to GitHub:
   ```bash
   pbcopy < token.json
   ```
3. **Settings → Secrets and variables → Actions → `GMAIL_TOKEN_JSON` → Update secret** → paste and save.
4. Re-run the workflow manually to confirm.

Interactive OAuth is **blocked in CI** (`CI=true` is set automatically by GitHub Actions). You must always refresh tokens locally, then update the secret.

### Step 9: Disable GitHub Actions when Mac mini + launchd is ready

When your always-on Mac is set up ([SCHEDULING.md](SCHEDULING.md)):

1. Install launchd on the Mac mini:
   ```bash
   ./scripts/install_launchd.sh
   ```
2. Verify a local run and iMessage:
   ```bash
   python email_agent.py --once
   python email_agent.py --test-imessage
   ```
3. **Disable** the cloud workflow (pick one):
   - **Recommended:** In GitHub → **Actions → Hourly email agent → ⋯ → Disable workflow**
   - **Or delete the schedule only:** Remove or comment out the `schedule:` block in `.github/workflows/hourly-email.yml` and push (keeps manual `workflow_dispatch` as backup)
   - **Or delete the file:** Remove `.github/workflows/hourly-email.yml` and push

4. Optional: remove `GMAIL_TOKEN_JSON` and other secrets from GitHub if you no longer need cloud runs.

You can leave the workflow disabled as a backup if the Mac mini is offline.

### Troubleshooting (GitHub Actions)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Error: ANTHROPIC_API_KEY is not set` | Secret missing or typo | Add `ANTHROPIC_API_KEY` under **Settings → Secrets → Actions** (exact name, case-sensitive) |
| `401` / `authentication_error` from Anthropic | Invalid or revoked API key; or LiteLLM URL in local `.env` copied by mistake | Use a direct Anthropic key in the secret; do not set `ANTHROPIC_BASE_URL` in the workflow |
| `Error: Gmail OAuth credentials file not found` | No `credentials.json` on disk and no `GMAIL_CREDENTIALS_JSON` secret | Add `GMAIL_CREDENTIALS_JSON` secret with full `credentials.json` contents |
| `Gmail token missing or expired; interactive OAuth is unavailable` | Missing/invalid `GMAIL_TOKEN_JSON`, or refresh failed | Re-run `python email_agent.py --once` locally; update `GMAIL_TOKEN_JSON` secret |
| `403 access_denied` during **local** auth | Google OAuth test user not configured | See [SETUP_GUIDE.md — Error 403](SETUP_GUIDE.md#access-blocked-email-agent-has-not-completed-the-google-verification-process-error-403-access_denied) |
| Workflow never runs on schedule | Actions disabled, repo inactive, or fork without secrets | Enable Actions; confirm secrets on **your** repo (not upstream); note cron is best-effort |
| Job succeeds but no emails processed | Inbox empty or all read | Normal — look for `✓ Done — 0 action(s) taken`; run with unread mail to verify |
| iMessage not received | Expected in CI | iMessage requires macOS Messages — use launchd on a Mac for notifications |

**View logs:** **Actions →** click a run → **triage** job → **Run email agent (once)**.

**Re-run failed job:** Open the run → **Re-run all jobs** (after fixing secrets).

### Railway / Render / Fly.io

Use a **cron job** or **scheduled task** container that runs the same command:

```bash
python email_agent.py --once --max-emails 10
```

Set environment variables (not files): `ANTHROPIC_API_KEY`, `GMAIL_TOKEN_JSON`, optionally `GMAIL_CREDENTIALS_JSON`. The agent writes them to disk on startup via `materialize_gmail_secrets_from_env()`.

**Pros:** More predictable schedule than GitHub Actions; can add Slack/email webhooks later.

**Cons:** Small monthly cost; still no iMessage.

### Google Cloud Run + Cloud Scheduler / AWS Lambda + EventBridge

Same env vars and `--once` command. Good if you already use GCP/AWS. Higher setup cost for a personal inbox agent.

### Cursor SDK cloud

The [Cursor SDK](https://cursor.com/docs/sdk) runs **coding agents** (edit repos, answer prompts) on Cursor-hosted VMs or locally. It is **not** a general Python cron host.

- It does not replace `email_agent.py` as a scheduled Gmail worker.
- Cloud agents target git repos, not long-lived OAuth + Gmail polling.
- OAuth browser flow still needs a local first auth.

Use the SDK for automation around the repo (e.g. “fix this PR”), not for hourly inbox triage.

### Keep your laptop running

When your Mac is available, `./scripts/install_launchd.sh` remains the best experience: iMessage works, token stays on disk, no secret rotation in GitHub.

## Environment variables for CI/cloud

In addition to [.env.example](.env.example), these support headless runs:

| Variable | Purpose |
|----------|---------|
| `GMAIL_TOKEN_JSON` | Full OAuth token JSON (same as `token.json`) |
| `GMAIL_CREDENTIALS_JSON` | Full client secrets JSON (same as `credentials.json`) |
| `GMAIL_TOKEN_FILE` / `GMAIL_CREDENTIALS_FILE` | Optional paths after materialization (defaults unchanged) |

If the token expires and refresh fails in CI, re-run local `python email_agent.py --once` and update `GMAIL_TOKEN_JSON`.

Interactive OAuth is blocked when `CI=true` (set automatically in GitHub Actions).

## Notifications without iMessage (future)

Until you have a Mac mini, consider:

- Checking Gmail for **IMPORTANT** labels the agent applies
- Adding a Slack/Discord webhook (not implemented yet)
- Running workflow with `workflow_dispatch` when you want a manual check

## Moving to Mac mini

1. Copy `.env`, `credentials.json`, and `token.json` to the mini (or re-auth once).
2. `./scripts/install_launchd.sh`
3. Disable or delete the GitHub Actions workflow (or leave it as backup).
4. Set `IMESSAGE_NOTIFY_TO` and run `python email_agent.py --test-imessage`.

See [SCHEDULING.md](SCHEDULING.md) for launchd details.
