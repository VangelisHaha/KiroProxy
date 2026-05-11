"""Token counting module using tiktoken.

Uses tiktoken (OpenAI's Rust-based tokenizer) for approximate token counting.
The cl100k_base encoding is close to Claude tokenization.

A correction factor of 1.15 is applied because Claude tokenizes text
approximately 15% more than GPT-4's cl100k_base encoding.

Replaces the naive len(text)//4 estimation with accurate BPE tokenization.
Inspired by kiro-gateway's tokenizer.py.
"""

import json
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger("tokenizer")

# Lazy loading of tiktoken
_encoding = None

# Claude tokenizes ~15% more than GPT-4 (cl100k_base)
CLAUDE_CORRECTION_FACTOR = 1.15


def _get_encoding():
    """Lazy initialization of tokenizer.

    Uses cl100k_base encoding for GPT-4/ChatGPT,
    which is close enough to Claude tokenization.
    """
    global _encoding
    if _encoding is None:
        try:
            import tiktoken
            _encoding = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            logger.warning(
                "tiktoken not installed; falling back to character-based estimation"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize tiktoken: {e}")
    return _encoding


def count_tokens(text: str) -> int:
    """Count tokens in a text string.

    Uses tiktoken with Claude correction factor when available,
    falls back to character-based estimation.
    """
    if not text:
        return 0

    enc = _get_encoding()
    if enc is not None:
        try:
            base_count = len(enc.encode(text))
            return int(base_count * CLAUDE_CORRECTION_FACTOR)
        except Exception:
            pass

    # Fallback: rough estimation
    # For CJK characters, each char is roughly 1-2 tokens
    # For ASCII, roughly 4 chars per token
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff'
                     or '\u3000' <= c <= '\u303f'
                     or '\uff00' <= c <= '\uffef'
                     or '\u3040' <= c <= '\u309f'
                     or '\u30a0' <= c <= '\u30ff'
                     or '\uac00' <= c <= '\ud7af')
    ascii_count = len(text) - cjk_count
    return int(cjk_count * 1.5 + ascii_count / 4)


def count_message_tokens(messages: List[Dict[str, Any]]) -> int:
    """Count approximate tokens in a list of messages.

    Handles various message formats (OpenAI, Anthropic, Kiro internal).
    """
    total = 0
    for msg in messages:
        # OpenAI/Anthropic format
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text", "")
                    if text:
                        total += count_tokens(text)
                elif isinstance(block, str):
                    total += count_tokens(block)

        # Kiro internal format
        user_msg = msg.get("userInputMessage", {})
        if user_msg:
            user_content = user_msg.get("content", "")
            if isinstance(user_content, str):
                total += count_tokens(user_content)

        assistant_msg = msg.get("assistantResponseMessage", {})
        if assistant_msg:
            asst_content = assistant_msg.get("content", "")
            if isinstance(asst_content, str):
                total += count_tokens(asst_content)

        # Tool-related content
        tool_calls = msg.get("tool_calls", [])
        for tc in tool_calls:
            func = tc.get("function", {})
            total += count_tokens(func.get("name", ""))
            args = func.get("arguments", "")
            if isinstance(args, str):
                total += count_tokens(args)

        # Role and overhead per message (~4 tokens)
        total += 4

    return total


def estimate_tokens(text: str) -> int:
    """Alias for count_tokens, kept for backward compatibility."""
    return count_tokens(text)
