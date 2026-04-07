"""SMS text formatting.

Strips markdown to plain text for SMS delivery. Markdown renders as
literal characters on phones — **bold** shows as **bold** instead of
bold. This module removes all markdown syntax while preserving the
readable content.
"""

from __future__ import annotations

import re


def format_for_sms(text: str) -> str:
    """Convert markdown-formatted text to plain SMS-friendly text.

    Removes bold, italic, underline, code blocks, inline code,
    headers, and markdown links. Collapses excessive whitespace.

    Args:
        text: Agent response, potentially containing markdown.

    Returns:
        Plain text suitable for SMS delivery.
    """
    # Code blocks: remove fences, keep content
    text = re.sub(r"```[a-z]*\n?", "", text)

    # Inline code: remove backticks, keep content
    text = re.sub(r"`(.+?)`", r"\1", text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)

    # Italic: *text* or _text_ (after bold to avoid conflicts)
    text = re.sub(r"\*(.+?)\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text, flags=re.DOTALL)

    # Headers: remove # prefix
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Links: [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Horizontal rules
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Bullet points: normalize to simple dash
    text = re.sub(r"^\s*[*+]\s+", "- ", text, flags=re.MULTILINE)

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
