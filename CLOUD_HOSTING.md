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

**Setup:**

1. Complete Gmail OAuth **on your Mac** (or any machine with a browser):

   ```bash
   python email_agent.py --once
   ```

2. In GitHub: **Settings → Secrets and variables → Actions**, add:

   | Secret | Value |
   |--------|--------|
   | `ANTHROPIC_API_KEY` | Your Anthropic API key |
   | `GMAIL_TOKEN_JSON` | Entire contents of `token.json` (single-line JSON is fine) |
   | `GMAIL_CREDENTIALS_JSON` | Optional — entire `credentials.json` if refresh ever needs client secrets |

3. Push the workflow (or use **Actions → Hourly email agent → Run workflow** to test).

4. Watch **Actions** tab logs for `✓ Done — N action(s) taken`.

To export the token for secrets:

```bash
# macOS — copy token JSON to clipboard
pbcopy < token.json
```

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
