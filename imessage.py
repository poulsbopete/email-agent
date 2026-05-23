"""Send iMessage notifications via AppleScript (macOS Messages app)."""

import os
import subprocess
import sys
from typing import Optional


def get_notify_recipient() -> Optional[str]:
    """Return IMESSAGE_NOTIFY_TO from environment, or None if unset."""
    recipient = os.getenv('IMESSAGE_NOTIFY_TO', '').strip()
    return recipient or None


def _escape_applescript(value: str) -> str:
    """Escape a string for use inside AppleScript double quotes."""
    return value.replace('\\', '\\\\').replace('"', '\\"')


def send_imessage(message: str, recipient: Optional[str] = None, dry_run: bool = False) -> bool:
    """
    Send an iMessage to the configured recipient using osascript.

    Requires Messages app signed in on macOS. Set IMESSAGE_NOTIFY_TO to a phone
    number (e.g. +15551234567) or Apple ID email of an existing conversation buddy.
    """
    if sys.platform != 'darwin':
        print('  ⚠ iMessage skipped: only supported on macOS')
        return False

    to = (recipient or get_notify_recipient() or '').strip()
    if not to:
        print('  ⚠ iMessage skipped: set IMESSAGE_NOTIFY_TO in .env')
        return False

    if dry_run:
        preview = message.replace('\n', ' ')[:200]
        print(f'  [dry-run] Would iMessage {to}: {preview}...')
        return True

    escaped_message = _escape_applescript(message)
    escaped_recipient = _escape_applescript(to)

    script = f'''
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "{escaped_recipient}" of targetService
    send "{escaped_message}" to targetBuddy
end tell
'''

    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or 'unknown error').strip()
            print(f'  ⚠ iMessage failed: {err}')
            return False
        print(f'  ✓ iMessage sent to {to}')
        return True
    except subprocess.TimeoutExpired:
        print('  ⚠ iMessage timed out')
        return False
    except FileNotFoundError:
        print('  ⚠ osascript not found')
        return False
    except OSError as exc:
        print(f'  ⚠ iMessage error: {exc}')
        return False


def format_review_notification(email: dict, question: str) -> str:
    """Format a concise iMessage for emails needing user input."""
    sender = email.get('from', 'Unknown')[:60]
    subject = email.get('subject', 'No subject')[:80]
    email_id = email.get('id', '')

    lines = [
        '📧 Email Agent needs your input',
        '',
        f'From: {sender}',
        f'Subject: {subject}',
        '',
        f'Question: {question}',
    ]
    if email_id:
        lines.extend(['', f'Gmail ID: {email_id}'])
    lines.extend(['', 'Reply in Gmail or tell the agent how to respond.'])
    return '\n'.join(lines)
