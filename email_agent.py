#!/usr/bin/env python3
"""
Autonomous Email Agent for Gmail
Archives promotions, responds to general emails, notifies via iMessage when unsure.
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

from imessage import format_review_notification, send_imessage

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
SCRIPT_DIR = Path(__file__).resolve().parent
PENDING_REVIEW_FILE = SCRIPT_DIR / 'pending_review.json'

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
]


def load_dotenv(env_path: Optional[Path] = None) -> None:
    """Load KEY=VALUE pairs from .env into os.environ (without overwriting)."""
    path = env_path or SCRIPT_DIR / '.env'
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
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


def exit_if_credentials_missing(credentials_path: Optional[Path] = None) -> None:
    """Exit with setup instructions when the OAuth client secrets file is missing."""
    path = credentials_path or get_credentials_path()
    if path.exists():
        return

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


def queue_for_review(email: dict, question: str, analysis: dict, dry_run: bool = False) -> None:
    """Add an email to the pending review queue."""
    if dry_run:
        return
    pending = load_pending_review()
    entry = {
        'id': email['id'],
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
        self.auto_send = os.getenv('AUTO_SEND_RESPONSES', 'false').lower() in ('1', 'true', 'yes')
        self.model = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514')

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
        print('✓ Gmail API authenticated')

    def authenticate_gmail(self):
        """Handle Gmail OAuth flow."""
        credentials_path = get_credentials_path()
        token_path = get_token_path()
        exit_if_credentials_missing(credentials_path)

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
        print('✓ Gmail API authenticated successfully')

    def get_unread_emails(self, max_results: Optional[int] = None) -> list:
        """Fetch unread emails from inbox."""
        limit = max_results or self.max_emails
        if self.dry_run:
            return MOCK_EMAILS[:limit]

        try:
            results = self.gmail_service.users().messages().list(
                userId='me',
                q='is:unread category:primary',
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

    def analyze_and_act_on_email(self, email: dict) -> dict:
        """Use Claude to analyze email and determine action."""
        analysis_prompt = f"""
Analyze this email and choose exactly one action.

From: {email['from']}
Subject: {email['subject']}
To: {email['to']}
Body (first 500 chars): {email['body']}

CLASSIFICATION RULES:
1. PROMOTIONAL/MARKETING (sales, ads, newsletters you did not ask for, bulk mail)
   - action: "archive"

2. GENERAL (clear personal or professional emails where a polite reply is appropriate)
   - action: "respond"
   - Include suggested_response (friendly, concise, max 200 chars)

3. NEEDS USER INPUT (ambiguous, sensitive, legal/financial, or you are unsure how to reply)
   - action: "needs_user_input"
   - Include user_question: a specific question for the inbox owner

Also handle these as general unless sensitive:
- Service notifications with no reply needed → action: "mark_read"
- Newsletters/digests the user likely wants to keep → action: "mark_read"

Respond with ONLY a JSON object (no markdown):
{{
    "email_type": "promotion|general|newsletter|service_notification|needs_user_input|other",
    "action": "archive|respond|mark_read|needs_user_input",
    "suggested_response": null or "reply text",
    "user_question": null or "specific question for the user",
    "reason": "brief explanation"
}}

Be conservative: if unsure how to respond, use needs_user_input.
"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{'role': 'user', 'content': analysis_prompt}],
        )

        assistant_message = response.content[0].text

        try:
            json_match = re.search(r'\{.*\}', assistant_message, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
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

    def notify_user(self, email: dict, question: str) -> bool:
        """Send iMessage notification when user input is needed."""
        message = format_review_notification(email, question)
        return send_imessage(message, dry_run=self.dry_run)

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
                        body={'addLabelIds': ['IMPORTANT']},
                    ).execute()
                queue_for_review(email, question, analysis, dry_run=self.dry_run)
                self.notify_user(email, question)
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
        print(f"\n{mode}📧 Checking inbox at {time.strftime('%Y-%m-%d %H:%M:%S')}")

        emails = self.get_unread_emails()

        if not emails:
            print('  No unread emails found')
            return 0

        print(f'  Found {len(emails)} unread emails')

        actions_taken = 0
        for email in emails:
            print(f"\n  Processing: {email['subject'][:50]}... from {email['from'][:30]}")

            analysis = self.analyze_and_act_on_email(email)
            print(f"    Type: {analysis.get('email_type', 'unknown')}")
            print(f"    Action: {analysis.get('action', 'unknown')}")
            if analysis.get('reason'):
                print(f"    Reason: {analysis.get('reason')[:80]}")

            if self.execute_action(email, analysis):
                actions_taken += 1

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
        description='Gmail agent: archive promotions, respond to general mail, iMessage when unsure.',
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
        '--test-imessage',
        action='store_true',
        help='Send a test iMessage to IMESSAGE_NOTIFY_TO and exit',
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
    parser = build_parser()
    args = parser.parse_args()

    if args.test_imessage:
        load_dotenv()
        ok = send_imessage(
            '📧 Email Agent test\n\nIf you received this, iMessage notifications are working.',
            dry_run=args.dry_run,
        )
        sys.exit(0 if ok else 1)

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
