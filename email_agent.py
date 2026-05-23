#!/usr/bin/env python3
"""
Autonomous Email Agent for Gmail
Archives promotions, responds to general emails, flags ambiguous mail for review.
"""

import argparse
import base64
import email.utils
import json
import os
import re
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
SCRIPT_DIR = Path(__file__).resolve().parent
PENDING_REVIEW_FILE = SCRIPT_DIR / 'pending_review.json'
REVIEW_INSTRUCTIONS_FILE = SCRIPT_DIR / 'review_instructions.json'
AGENT_INSTRUCTION_PREFIX = re.compile(r'^\s*\[agent\]\s*(.+)', re.IGNORECASE | re.DOTALL)

MOCK_EMAILS = [
    {
        'id': 'mock-promo-1',
        'subject': 'Flash Sale: 50% off everything today only!',
        'from': 'deals@store.example.com',
        'to': 'you@gmail.com',
        'body': 'Limited time offer. Shop now and save big on all items.',
        'full_body': 'Limited time offer. Shop now and save big on all items.',
        'timestamp': '0',
        'thread_id': 'mock-thread-1',
    },
    {
        'id': 'mock-general-1',
        'subject': 'Coffee this weekend?',
        'from': 'friend@example.com',
        'to': 'you@gmail.com',
        'body': 'Hey! Are you free Saturday afternoon for coffee?',
        'full_body': 'Hey! Are you free Saturday afternoon for coffee?',
        'timestamp': '0',
        'thread_id': 'mock-thread-2',
    },
    {
        'id': 'mock-ambiguous-1',
        'subject': 'Contract terms follow-up',
        'from': 'client@example.com',
        'to': 'you@gmail.com',
        'body': 'Can we discuss the liability clause before signing?',
        'full_body': 'Can we discuss the liability clause before signing?',
        'timestamp': '0',
        'thread_id': 'mock-thread-3',
    },
    {
        'id': 'mock-response-request-1',
        'subject': 'Are you looking for emails?',
        'from': 'Peter Simkins <poulsbopete@gmail.com>',
        'to': 'you@gmail.com',
        'body': 'Please respond if you get this. Thanks, me',
        'full_body': 'Please respond if you get this. Thanks, me',
        'timestamp': '0',
        'thread_id': 'mock-thread-4',
    },
]

# Heuristic patterns — applied after Claude to prevent mis-archiving personal mail.
RESPONSE_REQUEST_PATTERNS = [
    r'\bplease respond\b',
    r'\bplease reply\b',
    r'\blet me know\b',
    r'\bget back to me\b',
    r'\bwrite back\b',
    r'\breply (if|when|to)\b',
    r'\brespond (if|when|to)\b',
    r'\bwaiting for (your|a) (reply|response)\b',
    r'\bcan you (reply|respond)\b',
    r'\bdo you get this\b',
    r'\bdid you get (this|my)\b',
]

PROMOTION_INDICATORS = [
    r'\bunsubscribe\b',
    r'\bopt[- ]?out\b',
    r'\bmanage (your )?preferences\b',
    r'\bview in browser\b',
    r'\bflash sale\b',
    r'\blimited time offer\b',
    r'\b\d+% off\b',
    r'\bfree shipping\b',
    r'\bshop now\b',
    r'\bact now\b',
    r'\bexclusive deal\b',
    r'\bnewsletter\b',
    r'\bmarketing email\b',
]

PROMOTION_SENDER_PATTERNS = [
    r'^(noreply|no-reply|donotreply|do-not-reply)@',
    r'^(marketing|promo|promotions|deals|newsletter|news|notifications|info)@',
    r'@mail\.(chimp|jet|erlite|gun)\.',
    r'@email\.',
    r'@e\.',
    r'@mg\.',
]


def email_combined_text(email: dict) -> str:
    """Subject + body for heuristic scans."""
    body = email.get('full_body') or email.get('body') or ''
    return f"{email.get('subject', '')}\n{body}"


def requests_response(email: dict) -> bool:
    """True when the sender clearly expects a reply."""
    subject = email.get('subject', '')
    text = email_combined_text(email).lower()
    for pattern in RESPONSE_REQUEST_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    if '?' in subject:
        return True
    return False


def looks_like_clear_promotion(email: dict) -> bool:
    """True only for mail with strong promotional signals."""
    text = email_combined_text(email).lower()
    sender = parse_sender_address(email.get('from', '')).lower()
    for pattern in PROMOTION_SENDER_PATTERNS:
        if re.search(pattern, sender, re.IGNORECASE):
            return True
    for pattern in PROMOTION_INDICATORS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def is_own_sender(email: dict, own_email: str) -> bool:
    """True when the message appears to come from the inbox owner."""
    if not own_email:
        return False
    sender = parse_sender_address(email.get('from', '')).lower()
    return sender == own_email.lower()


def load_personal_senders() -> set[str]:
    """Optional comma-separated trusted personal addresses from env."""
    raw = os.getenv('PERSONAL_SENDERS', '').strip()
    if not raw:
        return set()
    return {addr.strip().lower() for addr in raw.split(',') if addr.strip()}


def is_personal_sender(email: dict, personal_senders: set[str]) -> bool:
    """True when sender is in PERSONAL_SENDERS."""
    if not personal_senders:
        return False
    sender = parse_sender_address(email.get('from', '')).lower()
    return sender in personal_senders


def apply_classification_safeguards(
    email: dict,
    analysis: dict,
    own_email: str = '',
    personal_senders: Optional[set[str]] = None,
) -> dict:
    """
    Override unsafe archive decisions. Never archive mail that asks for a reply,
    comes from the user, or lacks clear promotional signals.
    """
    personal_senders = personal_senders or set()
    action = analysis.get('action', 'needs_user_input')

    if action != 'archive':
        return analysis

    override_reason = None
    if requests_response(email):
        override_reason = 'response_requested'
    elif is_own_sender(email, own_email):
        override_reason = 'from_own_address'
    elif is_personal_sender(email, personal_senders):
        override_reason = 'personal_sender'
    elif not looks_like_clear_promotion(email):
        override_reason = 'not_clear_promotion'

    if not override_reason:
        return analysis

    original_reason = analysis.get('reason', '')
    safeguard_note = f'Safeguard blocked archive ({override_reason})'

    if override_reason in ('response_requested', 'personal_sender'):
        return {
            **analysis,
            'action': 'respond',
            'email_type': 'general',
            'suggested_response': analysis.get('suggested_response') or (
                "Got your message — thanks for reaching out!"
            ),
            'user_question': None,
            'reason': f'{safeguard_note}. {original_reason}'.strip(),
        }

    if override_reason == 'from_own_address':
        return {
            **analysis,
            'action': 'needs_user_input',
            'email_type': 'needs_user_input',
            'suggested_response': None,
            'user_question': (
                'This message appears to come from your own address. '
                'How should I respond?'
            ),
            'reason': f'{safeguard_note}. {original_reason}'.strip(),
        }

    return {
        **analysis,
        'action': 'needs_user_input',
        'email_type': 'needs_user_input',
        'suggested_response': None,
        'user_question': analysis.get('user_question') or (
            'This email may need a response rather than archiving. How should I handle it?'
        ),
        'reason': f'{safeguard_note}. {original_reason}'.strip(),
    }


def build_analysis_prompt(email: dict, own_email: str = '', personal_senders: Optional[set[str]] = None) -> str:
    """Prompt for Claude email classification."""
    personal_senders = personal_senders or set()
    sender = parse_sender_address(email.get('from', ''))
    context_lines = []
    if own_email and sender.lower() == own_email.lower():
        context_lines.append(
            f'- Sender {sender!r} is the inbox owner\'s own address — NEVER archive; use respond or needs_user_input.'
        )
    if personal_senders and sender.lower() in personal_senders:
        context_lines.append(
            f'- Sender {sender!r} is a known personal contact — NEVER archive.'
        )
    context_block = '\n'.join(context_lines)
    if context_block:
        context_block = f'\nSENDER CONTEXT:\n{context_block}\n'

    return f"""
Analyze this email and choose exactly one action.

From: {email['from']}
Subject: {email['subject']}
To: {email['to']}
Body (first 500 chars): {email['body']}
{context_block}
CLASSIFICATION RULES (follow strictly):

NEVER archive when ANY of these apply:
- Subject or body asks for a reply ("please respond", "please reply", "let me know", questions ending with ?)
- Sender is a real person writing directly (not bulk/marketing)
- Sender is the inbox owner or a personal contact
- You are unsure — default to needs_user_input, NOT archive

ONLY archive CLEAR promotional/marketing mail with signals like:
- Unsubscribe / opt-out / manage preferences links
- Sales language (percent off, flash sale, limited time, shop now)
- Bulk sender addresses (noreply@, marketing@, deals@, newsletter@)

ACTIONS:
1. PROMOTIONAL/MARKETING (clear ads, sales, unsolicited bulk mail only)
   - action: "archive"

2. GENERAL (personal or professional mail expecting a reply)
   - action: "respond"
   - Include suggested_response (friendly, concise, max 200 chars)

3. NEEDS USER INPUT (ambiguous, sensitive, legal/financial, or unsure)
   - action: "needs_user_input"
   - Include user_question: a specific question for the inbox owner

Also handle without user input:
- Service notifications with no reply needed → action: "mark_read"
- Google/security login alerts, password resets, 2FA notices → action: "mark_read"
- Newsletters/digests the user likely wants to keep → action: "mark_read"

Respond with ONLY a JSON object (no markdown):
{{
    "email_type": "promotion|general|newsletter|service_notification|needs_user_input|other",
    "action": "archive|respond|mark_read|needs_user_input",
    "suggested_response": null or "reply text",
    "user_question": null or "specific question for the user",
    "reason": "brief explanation"
}}

Be conservative: when in doubt, use needs_user_input — never archive personal or conversational mail.
"""


def load_dotenv(env_path: Optional[Path] = None) -> None:
    """Load KEY=VALUE pairs from .env into os.environ (without overwriting)."""
    path = env_path or SCRIPT_DIR / '.env'
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            if re.match(r'^[A-Z_][A-Z0-9_]*\s+\S', line):
                key = line.split()[0]
                print(f'Warning: ignored .env entry (use KEY=VALUE): {key}', file=sys.stderr)
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_path(filename: str) -> Path:
    """Resolve config files relative to the script directory."""
    path = Path(filename)
    if path.is_absolute():
        return path
    return SCRIPT_DIR / path


def get_credentials_path() -> Path:
    """Path to Gmail OAuth client secrets (Desktop app JSON from Google Cloud)."""
    return resolve_path(os.getenv('GMAIL_CREDENTIALS_FILE', 'credentials.json'))


def get_token_path() -> Path:
    """Path to saved OAuth token (created automatically on first successful auth)."""
    return resolve_path(os.getenv('GMAIL_TOKEN_FILE', 'token.json'))


def is_ci_environment() -> bool:
    """True when running in CI (GitHub Actions, etc.) — no interactive OAuth."""
    return os.getenv('CI', '').lower() in ('1', 'true', 'yes')


def _github_workflow_escape(text: str) -> str:
    """Escape text for GitHub Actions workflow commands (::warning:: etc.)."""
    return text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def append_github_step_summary(markdown: str) -> None:
    """Append markdown to GITHUB_STEP_SUMMARY when running in GitHub Actions."""
    summary_path = os.getenv('GITHUB_STEP_SUMMARY', '').strip()
    if not summary_path:
        return
    try:
        with open(summary_path, 'a', encoding='utf-8') as handle:
            handle.write(markdown)
    except OSError as exc:
        print(f'  ⚠ Could not write GitHub step summary: {exc}', file=sys.stderr)


def materialize_gmail_secrets_from_env() -> None:
    """Write GMAIL_*_JSON env vars to disk for OAuth libraries (CI/cloud hosting)."""
    force_write = is_ci_environment()

    creds_json = os.getenv('GMAIL_CREDENTIALS_JSON', '').strip()
    if creds_json:
        path = get_credentials_path()
        if force_write or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(creds_json)

    token_json = os.getenv('GMAIL_TOKEN_JSON', '').strip()
    if token_json:
        path = get_token_path()
        if force_write or not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token_json)


def has_gmail_credentials() -> bool:
    """True when OAuth client secrets are available from file or env."""
    if os.getenv('GMAIL_CREDENTIALS_JSON', '').strip():
        return True
    return get_credentials_path().exists()


def is_interactive_auth_available() -> bool:
    """Whether the Desktop OAuth browser flow can run (local terminal, not CI)."""
    if is_ci_environment():
        return False
    return sys.stdin.isatty()


def exit_if_credentials_missing(credentials_path: Optional[Path] = None) -> None:
    """Exit with setup instructions when the OAuth client secrets file is missing."""
    if has_gmail_credentials():
        return
    path = credentials_path or get_credentials_path()

    env_override = os.getenv('GMAIL_CREDENTIALS_FILE')
    print('Error: Gmail OAuth credentials file not found.')
    print(f'  Expected: {path}')
    if env_override:
        print(f'  (from GMAIL_CREDENTIALS_FILE={env_override!r})')
    print()
    print('To set up Gmail API access:')
    print('  1. Go to https://console.cloud.google.com')
    print('  2. Create a project and enable the Gmail API')
    print('  3. Configure the OAuth consent screen (External, add yourself as a test user)')
    print('  4. Create OAuth 2.0 credentials (Desktop application)')
    print('  5. Download the JSON file and save it as:')
    print(f'     {path}')
    print()
    print('Optional: set a custom path in .env:')
    print('  GMAIL_CREDENTIALS_FILE=/path/to/your/client_secret.json')
    print()
    print('See credentials.example.json for the expected file format.')
    print('See SETUP_GUIDE.md for step-by-step instructions.')
    print()
    print('Tip: run with --dry-run to preview behavior without credentials.')
    sys.exit(1)


def parse_sender_address(from_header: str) -> str:
    """Extract email address from a From header."""
    _, addr = email.utils.parseaddr(from_header)
    return addr or from_header


def load_pending_review() -> list:
    """Load queued emails awaiting user input."""
    if not PENDING_REVIEW_FILE.exists():
        return []
    try:
        return json.loads(PENDING_REVIEW_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def save_pending_review(items: list) -> None:
    """Persist queued emails awaiting user input."""
    PENDING_REVIEW_FILE.write_text(json.dumps(items, indent=2))


def load_review_instructions() -> dict:
    """Load message_id -> instruction mappings committed for CI/cloud runs."""
    if not REVIEW_INSTRUCTIONS_FILE.exists():
        return {}
    try:
        data = json.loads(REVIEW_INSTRUCTIONS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items() if value}
    return {}


def save_review_instructions(instructions: dict) -> None:
    """Persist review instructions (processed entries are removed)."""
    if instructions:
        REVIEW_INSTRUCTIONS_FILE.write_text(json.dumps(instructions, indent=2) + '\n')
    elif REVIEW_INSTRUCTIONS_FILE.exists():
        REVIEW_INSTRUCTIONS_FILE.unlink()


def collect_review_instructions() -> dict:
    """Merge repo instructions with optional per-entry instructions in pending_review.json."""
    instructions = load_review_instructions()
    for item in load_pending_review():
        message_id = item.get('id')
        instruction = item.get('instruction', '').strip()
        if message_id and instruction:
            instructions[str(message_id)] = instruction
    return instructions


def queue_for_review(email: dict, question: str, analysis: dict, dry_run: bool = False) -> None:
    """Add an email to the pending review queue."""
    if dry_run:
        return
    pending = load_pending_review()
    entry = {
        'id': email['id'],
        'thread_id': email.get('thread_id'),
        'from': email['from'],
        'subject': email['subject'],
        'question': question,
        'email_type': analysis.get('email_type', 'unknown'),
        'queued_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    if not any(item['id'] == entry['id'] for item in pending):
        pending.append(entry)
        save_pending_review(pending)


class EmailAgent:
    def __init__(self, dry_run: bool = False, max_emails: int = 10):
        self.client = Anthropic()
        self.dry_run = dry_run
        self.max_emails = max_emails
        self.gmail_service = None
        self.auto_send = os.getenv('AUTO_SEND_RESPONSES', 'true').lower() in ('1', 'true', 'yes')
        self.model = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
        self._own_email: Optional[str] = None

        if not dry_run:
            self.setup_gmail_api()

    def setup_gmail_api(self):
        """Authenticate with Gmail API."""
        creds = None
        token_path = get_token_path()

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError:
                    self.authenticate_gmail()
                    return
            else:
                self.authenticate_gmail()
                return

        self.gmail_service = build('gmail', 'v1', credentials=creds)
        self._log_gmail_identity()

    def _log_gmail_identity(self) -> None:
        """Print authenticated mailbox (helps verify CI secrets match the intended account)."""
        try:
            profile = self.gmail_service.users().getProfile(userId='me').execute()
            email = profile.get('emailAddress', 'unknown')
            print(f'✓ Gmail API authenticated as {email}')
        except HttpError as error:
            print(f'✓ Gmail API authenticated (profile lookup failed: {error})')

    def authenticate_gmail(self):
        """Handle Gmail OAuth flow."""
        credentials_path = get_credentials_path()
        token_path = get_token_path()
        exit_if_credentials_missing(credentials_path)

        if not is_interactive_auth_available():
            print('Error: Gmail token missing or expired; interactive OAuth is unavailable here.')
            print('  Run locally once: python email_agent.py --once')
            print('  Then copy token.json into the GMAIL_TOKEN_JSON repository/CI secret.')
            print('  See CLOUD_HOSTING.md for GitHub Actions and other interim hosting.')
            sys.exit(1)

        print(
            'First-time Gmail sign-in: open the URL below in your browser '
            '(test user on your Google Cloud OAuth app). '
            f'Credentials file: {credentials_path.name}'
        )
        print(f'  Waiting for authorization; token will be saved to {token_path.name}')
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)

        with open(token_path, 'w') as token:
            token.write(creds.to_json())

        self.gmail_service = build('gmail', 'v1', credentials=creds)
        self._log_gmail_identity()

    def get_unread_emails(self, max_results: Optional[int] = None) -> list:
        """Fetch unread emails from inbox."""
        limit = max_results or self.max_emails
        if self.dry_run:
            return MOCK_EMAILS[:limit]

        # in:inbox — all inbox tabs (Primary, Updates, etc.). Avoid category:primary;
        # Gmail often routes security alerts and some personal mail to Updates.
        query = os.getenv('GMAIL_UNREAD_QUERY', 'is:unread in:inbox')

        try:
            results = self.gmail_service.users().messages().list(
                userId='me',
                q=query,
                maxResults=limit,
            ).execute()

            messages = results.get('messages', [])
            email_data = []

            for msg in messages:
                email_detail = self.get_email_details(msg['id'])
                if email_detail:
                    email_data.append(email_detail)

            return email_data
        except HttpError as error:
            print(f'An error occurred: {error}')
            return []

    def get_email_details(self, message_id: str) -> Optional[dict]:
        """Get full details of an email."""
        try:
            message = self.gmail_service.users().messages().get(
                userId='me',
                id=message_id,
                format='full',
            ).execute()

            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            to = next((h['value'] for h in headers if h['name'] == 'To'), '')

            body = self.get_email_body(message)

            return {
                'id': message_id,
                'subject': subject,
                'from': sender,
                'to': to,
                'body': body[:500],
                'full_body': body,
                'timestamp': message['internalDate'],
                'thread_id': message.get('threadId'),
            }
        except HttpError as error:
            print(f'Error getting email details: {error}')
            return None

    def get_email_body(self, message: dict) -> str:
        """Extract email body from message."""
        try:
            if 'parts' in message['payload']:
                parts = message['payload']['parts']
                data = parts[0]['body'].get('data', '')
            else:
                data = message['payload']['body'].get('data', '')

            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8')
            return 'No body content'
        except Exception as exc:
            return f'Could not parse body: {exc}'

    def get_own_email(self) -> str:
        """Cached mailbox address for detecting user-authored thread instructions."""
        if self._own_email:
            return self._own_email
        if self.dry_run:
            self._own_email = 'you@gmail.com'
            return self._own_email
        profile = self.gmail_service.users().getProfile(userId='me').execute()
        self._own_email = profile.get('emailAddress', '')
        return self._own_email

    def get_important_emails(self, max_results: int = 20) -> list:
        """Fetch inbox emails flagged IMPORTANT (awaiting user review)."""
        if self.dry_run:
            return []

        try:
            results = self.gmail_service.users().messages().list(
                userId='me',
                q='label:important in:inbox',
                maxResults=max_results,
            ).execute()
            emails = []
            for msg in results.get('messages', []):
                email_detail = self.get_email_details(msg['id'])
                if email_detail:
                    emails.append(email_detail)
            return emails
        except HttpError as error:
            print(f'Error listing IMPORTANT emails: {error}')
            return []

    def find_thread_agent_instruction(self, email: dict) -> Optional[str]:
        """Return instruction text if the user replied in-thread with [agent] ..."""
        thread_id = email.get('thread_id')
        if not thread_id or self.dry_run:
            return None

        own_email = self.get_own_email().lower()
        original_ts = int(email.get('timestamp') or 0)

        try:
            thread = self.gmail_service.users().threads().get(
                userId='me',
                id=thread_id,
                format='full',
            ).execute()
        except HttpError as error:
            print(f'Error reading thread {thread_id}: {error}')
            return None

        for message in thread.get('messages', []):
            if message.get('id') == email.get('id'):
                continue
            if int(message.get('internalDate', 0)) <= original_ts:
                continue

            headers = message.get('payload', {}).get('headers', [])
            sender = next((h['value'] for h in headers if h['name'] == 'From'), '')
            if parse_sender_address(sender).lower() != own_email:
                continue

            body = self.get_email_body(message)
            match = AGENT_INSTRUCTION_PREFIX.search(body.strip())
            if match:
                return match.group(1).strip()
        return None

    def compose_reply_from_instruction(self, email: dict, instruction: str) -> Optional[str]:
        """Turn a user instruction into reply text, or None for dismiss-only actions."""
        instruction = instruction.strip()
        if not instruction:
            return None

        lowered = instruction.lower()
        if lowered in ('skip', 'dismiss', 'ignore', 'no reply', 'no-reply'):
            return None
        if lowered == 'archive':
            return None

        reply_match = re.match(r'^reply:\s*(.+)$', instruction, re.IGNORECASE | re.DOTALL)
        if reply_match:
            return reply_match.group(1).strip()

        prompt = f"""
Write a concise email reply based on the user's instruction.

Original email:
From: {email['from']}
Subject: {email['subject']}
Body:
{email.get('full_body', email.get('body', ''))[:1500]}

User instruction: {instruction}

Respond with ONLY the reply body text (no subject, no markdown).
Keep it friendly and under 300 words.
"""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}],
        )
        return response.content[0].text.strip()

    def clear_review_state(self, message_id: str) -> None:
        """Remove review markers after an instruction has been handled."""
        if self.dry_run:
            return

        try:
            self.gmail_service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['IMPORTANT']},
            ).execute()
        except HttpError as error:
            print(f'Error clearing IMPORTANT label: {error}')

        pending = [item for item in load_pending_review() if item.get('id') != message_id]
        save_pending_review(pending)

        instructions = load_review_instructions()
        if message_id in instructions:
            del instructions[message_id]
            save_review_instructions(instructions)

    def apply_review_instruction(self, email: dict, instruction: str) -> bool:
        """Execute a user-provided instruction for a flagged email."""
        lowered = instruction.strip().lower()
        subject = email.get('subject', 'No subject')[:50]

        if lowered == 'archive':
            if not self.dry_run:
                self.gmail_service.users().messages().modify(
                    userId='me',
                    id=email['id'],
                    body={'removeLabelIds': ['INBOX', 'UNREAD', 'IMPORTANT']},
                ).execute()
            print(f'  ✓ Archived from review instruction: {subject}')
            self.clear_review_state(email['id'])
            return True

        if lowered in ('skip', 'dismiss', 'ignore', 'no reply', 'no-reply'):
            if not self.dry_run:
                self.gmail_service.users().messages().modify(
                    userId='me',
                    id=email['id'],
                    body={'removeLabelIds': ['IMPORTANT']},
                ).execute()
            print(f'  ✓ Dismissed review item: {subject}')
            self.clear_review_state(email['id'])
            return True

        reply_text = self.compose_reply_from_instruction(email, instruction)
        if not reply_text:
            print(f'  ⚠ Empty reply for review instruction: {subject}')
            return False

        if self.auto_send:
            ok = self.send_reply(email, reply_text)
        else:
            ok = self.create_draft(email, reply_text)

        if ok:
            if not self.dry_run:
                self.gmail_service.users().messages().modify(
                    userId='me',
                    id=email['id'],
                    body={'removeLabelIds': ['UNREAD']},
                ).execute()
            self.clear_review_state(email['id'])
            action = 'Sent reply' if self.auto_send else 'Created draft'
            print(f'  ✓ {action} from review instruction: {subject}')
        return ok

    def process_review_responses(self) -> int:
        """Apply queued instructions before processing new unread mail."""
        instructions = collect_review_instructions()
        important_emails = self.get_important_emails()

        work: dict[str, tuple[dict, str]] = {}
        for message_id, instruction in instructions.items():
            email = self.get_email_details(message_id)
            if email:
                work[message_id] = (email, instruction)
            else:
                print(f'  ⚠ Review instruction references unknown Gmail ID: {message_id}')

        for email in important_emails:
            message_id = email['id']
            if message_id in work:
                continue
            thread_instruction = self.find_thread_agent_instruction(email)
            if thread_instruction:
                work[message_id] = (email, thread_instruction)

        if not work:
            return 0

        print(f'\n📋 Processing {len(work)} review instruction(s)...')
        processed = 0
        for message_id, (email, instruction) in work.items():
            print(f"  Instruction for: {email['subject'][:50]}...")
            if self.apply_review_instruction(email, instruction):
                processed += 1
        return processed

    def analyze_and_act_on_email(self, email: dict) -> dict:
        """Use Claude to analyze email and determine action."""
        own_email = self.get_own_email()
        personal_senders = load_personal_senders()
        analysis_prompt = build_analysis_prompt(email, own_email, personal_senders)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{'role': 'user', 'content': analysis_prompt}],
        )

        assistant_message = response.content[0].text

        try:
            json_match = re.search(r'\{.*\}', assistant_message, re.DOTALL)
            if json_match:
                analysis = json.loads(json_match.group())
                return apply_classification_safeguards(
                    email, analysis, own_email, personal_senders,
                )
        except json.JSONDecodeError:
            print(f'Could not parse Claude response: {assistant_message}')

        return {
            'action': 'needs_user_input',
            'user_question': 'Could not classify this email automatically. How should I respond?',
            'reason': 'Could not parse analysis',
        }

    def send_reply(self, email: dict, response_text: str) -> bool:
        """Send a reply email in the same thread."""
        if self.dry_run:
            print(f'  [dry-run] Would send reply to {email["from"]}: {response_text[:80]}...')
            return True

        try:
            reply = MIMEText(response_text)
            reply['to'] = parse_sender_address(email['from'])
            reply['subject'] = email['subject']
            if not reply['subject'].lower().startswith('re:'):
                reply['subject'] = f"Re: {reply['subject']}"

            raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
            body = {'raw': raw}
            if email.get('thread_id'):
                body['threadId'] = email['thread_id']

            self.gmail_service.users().messages().send(userId='me', body=body).execute()
            print(f'  ✓ Sent reply to {email["from"][:40]}')
            return True
        except HttpError as error:
            print(f'Error sending reply: {error}')
            return False

    def create_draft(self, email: dict, response_text: str) -> bool:
        """Create a draft reply for user review."""
        if self.dry_run:
            print(f'  [dry-run] Would create draft for {email["from"]}: {response_text[:80]}...')
            return True

        try:
            draft_body = MIMEText(response_text)
            draft_body['to'] = parse_sender_address(email['from'])
            draft_body['subject'] = email['subject']
            if not draft_body['subject'].lower().startswith('re:'):
                draft_body['subject'] = f"Re: {draft_body['subject']}"

            raw = base64.urlsafe_b64encode(draft_body.as_bytes()).decode()
            message = {'raw': raw}
            if email.get('thread_id'):
                message['threadId'] = email['thread_id']

            self.gmail_service.users().drafts().create(
                userId='me',
                body={'message': message},
            ).execute()
            print(f'  ✓ Draft created for {email["from"][:40]}')
            return True
        except HttpError as error:
            print(f'Error creating draft: {error}')
            return False

    def report_needs_user_input(self, email: dict, question: str) -> None:
        """Log emails needing user input; in CI, also write GitHub summary and annotations."""
        sender = email.get('from', 'Unknown')
        subject = email.get('subject', 'No subject')
        email_id = email.get('id', '')

        print('')
        print('=' * 60)
        print('NEEDS USER INPUT')
        print(f'  From: {sender}')
        print(f'  Subject: {subject}')
        print(f'  Question: {question}')
        if email_id:
            print(f'  Gmail ID: {email_id}')
        print('=' * 60)

        if is_ci_environment():
            title = 'Email needs your input'
            body = _github_workflow_escape(f'From: {sender} — {subject}')
            print(f'::warning title={title}::{body}')

            summary_lines = [
                '### ⚠️ Email needs your input',
                '',
                f'- **From:** {sender}',
                f'- **Subject:** {subject}',
                f'- **Question:** {question}',
            ]
            if email_id:
                summary_lines.append(f'- **Gmail ID:** `{email_id}`')
            summary_lines.extend([
                '',
                '**How to respond:** add an entry to `review_instructions.json` and push, '
                'or reply in the Gmail thread with `[agent] your instruction` '
                '(see CLOUD_HOSTING.md).',
            ])
            summary_lines.append('')
            append_github_step_summary('\n'.join(summary_lines))

    def execute_action(self, email: dict, analysis: dict) -> bool:
        """Execute the determined action on the email."""
        action = analysis.get('action', 'needs_user_input')
        email_id = email['id']

        try:
            if action == 'archive':
                if not self.dry_run:
                    self.gmail_service.users().messages().modify(
                        userId='me',
                        id=email_id,
                        body={'removeLabelIds': ['INBOX', 'UNREAD']},
                    ).execute()
                print(f"  ✓ Archived: {email['subject'][:50]}")
                return True

            if action == 'mark_read':
                if not self.dry_run:
                    self.gmail_service.users().messages().modify(
                        userId='me',
                        id=email_id,
                        body={'removeLabelIds': ['UNREAD']},
                    ).execute()
                print(f"  ✓ Marked read: {email['subject'][:50]}")
                return True

            if action == 'respond':
                response_text = analysis.get('suggested_response') or "Thanks for your email — I'll get back to you soon."
                if self.auto_send:
                    ok = self.send_reply(email, response_text)
                else:
                    ok = self.create_draft(email, response_text)

                if ok and not self.dry_run:
                    self.gmail_service.users().messages().modify(
                        userId='me',
                        id=email_id,
                        body={'removeLabelIds': ['UNREAD']},
                    ).execute()
                return ok

            if action == 'needs_user_input':
                question = analysis.get('user_question') or 'How should I respond to this email?'
                if not self.dry_run:
                    self.gmail_service.users().messages().modify(
                        userId='me',
                        id=email_id,
                        body={
                            'addLabelIds': ['IMPORTANT'],
                            'removeLabelIds': ['UNREAD'],
                        },
                    ).execute()
                queue_for_review(email, question, analysis, dry_run=self.dry_run)
                self.report_needs_user_input(email, question)
                email_type = analysis.get('email_type', 'unknown')
                print(f"  ⚠ Queued for review [{email_type}]: {email['subject'][:50]}")
                return True

        except HttpError as error:
            print(f'Error executing action: {error}')
            return False

        return False

    def run_once(self) -> int:
        """Run one complete cycle of email processing."""
        mode = '[dry-run] ' if self.dry_run else ''
        query = os.getenv('GMAIL_UNREAD_QUERY', 'is:unread in:inbox')
        print(f"\n{mode}📧 Checking inbox at {time.strftime('%Y-%m-%d %H:%M:%S')}")

        review_processed = self.process_review_responses()
        if review_processed:
            print(f'  ✓ Handled {review_processed} review instruction(s)')

        print(f'  Gmail query: {query!r} (max {self.max_emails})')

        emails = self.get_unread_emails()

        if not emails:
            print('  No unread emails matched the query')
            if query != 'is:unread in:inbox':
                print('  Tip: try GMAIL_UNREAD_QUERY=is:unread in:inbox (default) if mail is in Updates/Promotions')
            elif 'category:primary' in query:
                print('  Tip: category:primary skips Updates/Promotions tabs — use is:unread in:inbox')
            return 0

        print(f'  Found {len(emails)} unread emails')

        actions_taken = 0
        review_count = 0
        for email in emails:
            print(f"\n  Processing: {email['subject'][:50]}... from {email['from'][:30]}")

            analysis = self.analyze_and_act_on_email(email)
            print(f"    Type: {analysis.get('email_type', 'unknown')}")
            print(f"    Action: {analysis.get('action', 'unknown')}")
            if analysis.get('reason'):
                print(f"    Reason: {analysis.get('reason')[:80]}")

            if self.execute_action(email, analysis):
                actions_taken += 1
                if analysis.get('action') == 'needs_user_input':
                    review_count += 1

        if review_count and is_ci_environment():
            print('')
            print(f'::notice title=Review required::{review_count} email(s) flagged IMPORTANT in Gmail — see step summary above')
            append_github_step_summary(
                f'\n**{review_count} email(s)** flagged with the Gmail **IMPORTANT** label. '
                'Check your inbox or re-run after you decide how to respond.\n'
            )

        return actions_taken

    def start_daemon(self, check_interval: int):
        """Run continuously (legacy mode; prefer hourly launchd + --once)."""
        print('🤖 Email Agent Starting (daemon mode)...')
        print(f'Check interval: {check_interval} seconds')
        print('Press Ctrl+C to stop\n')

        try:
            cycle = 0
            while True:
                cycle += 1
                print(f"\n{'=' * 60}")
                print(f'CYCLE {cycle}')
                print(f"{'=' * 60}")

                actions = self.run_once()

                if actions > 0:
                    print(f'\n✓ Completed {actions} actions this cycle')

                print(f'\nNext check in {check_interval} seconds...')
                time.sleep(check_interval)

        except KeyboardInterrupt:
            print('\n\n👋 Email Agent stopped by user')
        except Exception as exc:
            print(f'\n❌ Agent error: {exc}')
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Gmail agent: archive promotions, respond to general mail, flag ambiguous mail for review.',
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Run one inbox check and exit (use with launchd/cron for hourly runs)',
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run continuously with CHECK_INTERVAL between checks (legacy mode)',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview actions without Gmail changes; uses mock emails if Gmail unavailable',
    )
    parser.add_argument(
        '--max-emails',
        type=int,
        default=int(os.getenv('MAX_EMAILS_PER_RUN', '10')),
        help='Maximum unread emails to process per run (default: 10)',
    )
    return parser


def main():
    load_dotenv()
    materialize_gmail_secrets_from_env()
    parser = build_parser()
    args = parser.parse_args()

    if args.dry_run:
        print('Dry-run mode: no Gmail modifications will be made.')
        if not get_credentials_path().exists():
            print('  (No credentials.json — using mock emails for preview)')
        if not os.getenv('ANTHROPIC_API_KEY'):
            print('Error: ANTHROPIC_API_KEY is not set (required even in dry-run for classification).')
            print(f'Set it in {SCRIPT_DIR / ".env"}')
            sys.exit(1)
    else:
        exit_if_credentials_missing()
        if not os.getenv('ANTHROPIC_API_KEY'):
            print('Error: ANTHROPIC_API_KEY is not set.')
            print(f'Set it in {SCRIPT_DIR / ".env"}')
            sys.exit(1)

    agent = EmailAgent(dry_run=args.dry_run, max_emails=args.max_emails)

    if args.daemon:
        check_interval = int(os.getenv('CHECK_INTERVAL', '300'))
        agent.start_daemon(check_interval)
    else:
        # Default and --once: single run (intended for hourly launchd)
        actions = agent.run_once()
        print(f'\n✓ Done — {actions} action(s) taken')
        sys.exit(0)


if __name__ == '__main__':
    main()
