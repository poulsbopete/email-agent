#!/usr/bin/env python3
"""
Extract writing-style samples from a local OpenAI chat export (mined by MemPalace).

Reads conversations-*.json from an OpenAI data export directory, keeps user-authored
text only, anonymizes obvious PII, and writes voice_examples.txt for EMAIL_VOICE.

Does not require the MemPalace MCP server. The Chroma index at ~/.mempalace/palace
stores whole JSON files as chunks, so this script reads the source export directly.

Usage:
  python3 scripts/export_voice_from_mempalace.py
  python3 scripts/export_voice_from_mempalace.py --source-dir ~/openai-history --output voice_examples.txt
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_SOURCE = Path.home() / 'openai-history'
DEFAULT_OUTPUT = Path('voice_examples.txt')

EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
PHONE_RE = re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
URL_RE = re.compile(r'https?://\S+|www\.\S+')
PROMPT_PREFIX_RE = re.compile(
    r'^(can you|please |write |help me|i need you to|generate |create |draft '
    r'|what is|how do|explain |summarize |translate |fix this|rewrite )',
    re.IGNORECASE,
)

EMAIL_STYLE_MARKERS = (
    'subject:',
    'dear ',
    'hi ',
    'hello ',
    'thanks,',
    'thank you,',
    'best,',
    'regards,',
    'cheers,',
    'sincerely,',
    'looking forward',
)


def anonymize(text: str) -> str:
    text = EMAIL_RE.sub('[email]', text)
    text = PHONE_RE.sub('[phone]', text)
    text = URL_RE.sub('[url]', text)
    return text.strip()


def score_sample(text: str) -> int:
    """Higher score = more likely useful as an email voice example."""
    low = text.lower()
    score = 0
    if any(marker in low for marker in EMAIL_STYLE_MARKERS):
        score += 4
    if re.search(r'\b(thanks|best|regards|cheers),?\s+\w', low):
        score += 3
    if 120 <= len(text) <= 800:
        score += 2
    elif 80 <= len(text) <= 1200:
        score += 1
    if text.count('\n') >= 1:
        score += 1
    if PROMPT_PREFIX_RE.match(text[:80]):
        score -= 5
    if text.startswith('```') or 'import ' in text[:120]:
        score -= 4
    return score


def iter_user_messages(conversations_path: Path):
    with conversations_path.open(encoding='utf-8') as handle:
        conversations = json.load(handle)
    if not isinstance(conversations, list):
        return
    for conversation in conversations:
        mapping = conversation.get('mapping') or {}
        for node in mapping.values():
            message = node.get('message')
            if not message:
                continue
            author = message.get('author') or {}
            if author.get('role') != 'user':
                continue
            content = message.get('content') or {}
            if content.get('content_type') != 'text':
                continue
            parts = content.get('parts') or []
            text = ''.join(part if isinstance(part, str) else '' for part in parts).strip()
            if text:
                yield text


def collect_samples(source_dir: Path, max_samples: int, min_score: int) -> list[str]:
    pattern = str(source_dir / 'conversations-*.json')
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise FileNotFoundError(
            f'No conversations-*.json files under {source_dir}. '
            'Export OpenAI history or pass --source-dir.'
        )

    seen_hashes: set[str] = set()
    ranked: list[tuple[int, str]] = []

    for path_str in paths:
        for raw in iter_user_messages(Path(path_str)):
            if len(raw) < 80 or len(raw) > 2500:
                continue
            if PROMPT_PREFIX_RE.match(raw[:80]):
                continue
            score = score_sample(raw)
            if score < min_score:
                continue
            digest = hashlib.sha256(raw[:240].encode('utf-8')).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            ranked.append((score, anonymize(raw)))

    ranked.sort(key=lambda item: (-item[0], -len(item[1])))
    return [text for _, text in ranked[:max_samples]]


def format_output(samples: list[str], source_dir: Path) -> str:
    header = (
        '# Voice examples for EMAIL_VOICE / VOICE_EXAMPLES_FILE\n'
        '# Generated from local OpenAI chat export (user messages only, anonymized).\n'
        f'# Source: {source_dir}\n'
        '# Do not commit this file.\n'
    )
    blocks = []
    for index, sample in enumerate(samples, start=1):
        blocks.append(f'--- Example {index} ---\n{sample}')
    return header + '\n' + '\n\n'.join(blocks) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Export anonymized writing samples from OpenAI chat history.',
    )
    parser.add_argument(
        '--source-dir',
        type=Path,
        default=Path(os.getenv('OPENAI_HISTORY_DIR', DEFAULT_SOURCE)),
        help='Directory with conversations-*.json (default: ~/openai-history)',
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path(os.getenv('VOICE_EXAMPLES_FILE', DEFAULT_OUTPUT)),
        help='Output file path (default: voice_examples.txt)',
    )
    parser.add_argument(
        '--max-samples',
        type=int,
        default=int(os.getenv('VOICE_EXAMPLES_MAX', '25')),
        help='Maximum examples to write (default: 25)',
    )
    parser.add_argument(
        '--min-score',
        type=int,
        default=1,
        help='Minimum relevance score (default: 1)',
    )
    args = parser.parse_args()

    source_dir = args.source_dir.expanduser().resolve()
    if not source_dir.is_dir():
        print(f'Error: source directory not found: {source_dir}', file=sys.stderr)
        return 1

    try:
        samples = collect_samples(source_dir, args.max_samples, args.min_score)
    except FileNotFoundError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    if not samples:
        print(
            'No suitable user messages found. Try lowering --min-score or '
            'add manual examples to the output file.',
            file=sys.stderr,
        )
        return 1

    output_path = args.output.expanduser()
    output_path.write_text(format_output(samples, source_dir), encoding='utf-8')
    print(
        f'Wrote {len(samples)} anonymized samples ({output_path.stat().st_size} bytes) '
        f'to {output_path}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
