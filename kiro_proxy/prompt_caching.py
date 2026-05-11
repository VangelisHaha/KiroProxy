"""Prompt caching support.

Converts Anthropic's cache_control directives to Kiro's cachePoint format.
This reduces duplicate token processing for tools and system prompts
that remain unchanged across requests.

Inspired by kirocc's cache_points.go.
"""

from typing import Any, Dict, List

from .logger import get_logger

logger = get_logger("prompt_caching")


def apply_tool_cache_points(
    anthropic_tools: List[Dict[str, Any]],
    kiro_tools: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert cachePoint entries into the Kiro tools array
    after tools that have cache_control set in the Anthropic request.

    Args:
        anthropic_tools: Original Anthropic tool definitions (may have cache_control).
        kiro_tools: Converted Kiro tool entries.

    Returns:
        New list of Kiro tool entries with cachePoint entries inserted.
    """
    if not anthropic_tools:
        return kiro_tools

    result = []
    entry_idx = 0

    for tool in anthropic_tools:
        if entry_idx < len(kiro_tools):
            result.append(kiro_tools[entry_idx])
            entry_idx += 1

        cache_control = tool.get("cache_control")
        if cache_control is not None:
            result.append({"cachePoint": {"type": "default"}})
            logger.debug(f"Added cachePoint after tool '{tool.get('name', '?')}'")

    # Append any remaining entries
    while entry_idx < len(kiro_tools):
        result.append(kiro_tools[entry_idx])
        entry_idx += 1

    return result


def apply_message_cache_points(
    messages: List[Dict[str, Any]],
    kiro_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert cachePoint entries into Kiro history based on message-level
    cache_control in the Anthropic request.

    Checks for cache_control on the last content block of each message.

    Args:
        messages: Original Anthropic messages.
        kiro_history: Converted Kiro history entries.

    Returns:
        Kiro history with cachePoint entries inserted where applicable.
    """
    if not messages or not kiro_history:
        return kiro_history

    result = []
    hist_idx = 0

    for msg in messages:
        if hist_idx >= len(kiro_history):
            break

        result.append(kiro_history[hist_idx])
        hist_idx += 1

        # Check for cache_control on the message content
        content = msg.get("content", "")
        if isinstance(content, list) and content:
            last_block = content[-1]
            if isinstance(last_block, dict) and last_block.get("cache_control"):
                result.append({"cachePoint": {"type": "default"}})

    # Append remaining history entries
    while hist_idx < len(kiro_history):
        result.append(kiro_history[hist_idx])
        hist_idx += 1

    return result


def apply_system_cache_point(
    system: Any,
    kiro_system_text: str,
) -> str:
    """Check if system prompt has cache_control and return marker if so.

    Note: Kiro doesn't have a direct system prompt caching mechanism,
    but we track it for potential future use.

    Args:
        system: Original Anthropic system parameter.
        kiro_system_text: Converted system text for Kiro.

    Returns:
        The system text, unchanged (caching handled at API level).
    """
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("cache_control"):
                logger.debug("System prompt has cache_control (tracked)")
                break

    return kiro_system_text
