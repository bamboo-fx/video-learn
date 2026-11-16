"""Spotting secrets in text that's about to be stored or shown.

Lessons made from someone's own computer arrive with code already in them. The /lesson
skill checks for secrets before anything leaves the machine; the server checks again, so a
key pasted into a scene by mistake is refused instead of published behind a share link.
"""

import re

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("an Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("an OpenAI key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("a Stripe key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("a JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("a password or key in a URL", re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{6,}@", re.I)),
    (
        "a hard-coded secret",
        re.compile(
            r"""(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d|private[_-]?key|access[_-]?key)\b"""
            r"""\s*[:=]\s*['"][^'"\s]{12,}['"]"""
        ),
    ),
]


def find_secret(text: str) -> str | None:
    """What kind of secret the text seems to contain, or None."""
    for label, pattern in PATTERNS:
        if pattern.search(text or ""):
            return label
    return None
