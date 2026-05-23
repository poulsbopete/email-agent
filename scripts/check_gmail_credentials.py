#!/usr/bin/env python3
"""Validate Gmail OAuth credentials.json structure without printing secrets."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REQUIRED_INSTALLED_KEYS = (
    'client_id',
    'project_id',
    'auth_uri',
    'token_uri',
    'client_secret',
    'redirect_uris',
)

REQUIRED_SCOPES = ('https://www.googleapis.com/auth/gmail.modify',)


def resolve_credentials_path() -> Path:
    script_dir = Path(__file__).resolve().parent.parent
    raw = os.getenv('GMAIL_CREDENTIALS_FILE', 'credentials.json')
    path = Path(raw)
    if not path.is_absolute():
        path = script_dir / path
    return path


def resolve_token_path() -> Path:
    script_dir = Path(__file__).resolve().parent.parent
    raw = os.getenv('GMAIL_TOKEN_FILE', 'token.json')
    path = Path(raw)
    if not path.is_absolute():
        path = script_dir / path
    return path


def mask_client_id(client_id: str) -> str:
    if len(client_id) <= 24:
        return client_id[:8] + '...'
    return client_id[:20] + '...'


def main() -> int:
    creds_path = resolve_credentials_path()
    token_path = resolve_token_path()
    errors: list[str] = []
    warnings: list[str] = []

    print('Gmail OAuth credentials check')
    print('=' * 40)
    print(f'Credentials file: {creds_path}')
    print(f'Token file:       {token_path}')
    print()

    if not creds_path.exists():
        errors.append(f'Missing credentials file: {creds_path}')
        print('FAIL')
        for msg in errors:
            print(f'  - {msg}')
        print()
        print('Download Desktop OAuth JSON from Google Cloud Console → APIs & Services → Credentials.')
        return 1

    try:
        data = json.loads(creds_path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f'Invalid JSON: {exc}')
        print('FAIL')
        for msg in errors:
            print(f'  - {msg}')
        return 1

    if 'installed' not in data:
        if 'web' in data:
            errors.append('Found "web" client — need Desktop app credentials ("installed" key).')
        else:
            errors.append('Missing "installed" key — expected Desktop OAuth client JSON.')
    else:
        installed = data['installed']
        missing = [k for k in REQUIRED_INSTALLED_KEYS if k not in installed]
        if missing:
            errors.append(f'Missing installed fields: {", ".join(missing)}')

        client_id = installed.get('client_id', '')
        project_id = installed.get('project_id', '')
        if client_id and not client_id.endswith('.apps.googleusercontent.com'):
            warnings.append('client_id does not look like a Google OAuth client ID.')
        if not project_id:
            errors.append('project_id is empty — credentials may be from wrong download.')

        print('Credentials structure: OK (Desktop / installed)')
        print(f'  project_id:  {project_id or "(missing)"}')
        print(f'  client_id:   {mask_client_id(client_id) if client_id else "(missing)"}')
        print(f'  has secret:  {bool(installed.get("client_secret"))}')
        print()
        print('Use this project_id in Google Cloud Console (top bar) when configuring test users.')
        print('Google Auth Platform → Audience → Test users → add the Gmail you sign in with.')

    print()
    print('Required Gmail scopes (configure in Google Auth Platform → Data Access):')
    for scope in REQUIRED_SCOPES:
        print(f'  - {scope}')

    print()
    if token_path.exists():
        print('token.json: present (prior auth succeeded)')
    else:
        warnings.append('token.json not found — run: python3 email_agent.py --once')

    if warnings:
        print()
        print('Warnings:')
        for msg in warnings:
            print(f'  - {msg}')

    if errors:
        print()
        print('FAIL')
        for msg in errors:
            print(f'  - {msg}')
        return 1

    print()
    print('PASS — credentials.json format looks valid.')
    if not token_path.exists():
        print('Next: fix test users in Google Auth Platform → Audience, then run email_agent.py --once')
    return 0


if __name__ == '__main__':
    sys.exit(main())
