"""Payload size guard for Kiro API requests.

The Kiro API rejects payloads exceeding ~615KB with a misleading
"Improperly formed request." (reason: null) error. This module provides:
- Pre-flight size checking
- Auto-trimming of oldest history entries to fit under the limit
- Orphaned toolResult repair after trimming

Inspired by kiro-gateway's payload_guards.py.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .logger import get_logger
from .env_config import KIRO_MAX_PAYLOAD_BYTES, AUTO_TRIM_PAYLOAD

logger = get_logger("payload_guards")


@dataclass
class PayloadTrimStats:
    """Statistics from a payload trim operation."""
    original_bytes: int
    final_bytes: int
    original_entries: int
    final_entries: int
    trimmed: bool


def check_payload_size(payload: Dict[str, Any]) -> int:
    """Return the serialized byte size of the payload as UTF-8 JSON."""
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _strip_empty_tool_uses(history: List[Dict]) -> None:
    """Remove empty toolUses arrays in-place (Kiro quirk)."""
    for entry in history:
        assistant = entry.get("assistantResponseMessage")
        if assistant and "toolUses" in assistant and assistant["toolUses"] == []:
            del assistant["toolUses"]


def _align_to_user_message(history: List[Dict]) -> List[Dict]:
    """Ensure history starts with a userInputMessage entry."""
    while history and "userInputMessage" not in history[0]:
        history.pop(0)
    return history


def _repair_orphaned_tool_results(history: List[Dict]) -> None:
    """Remove orphaned toolResults that reference toolUseIds not present
    in the preceding assistant message."""
    for i, entry in enumerate(history):
        user_msg = entry.get("userInputMessage")
        if not user_msg:
            continue

        ctx = user_msg.get("userInputMessageContext")
        if not ctx or "toolResults" not in ctx:
            continue

        # Find preceding assistant message
        prev_tool_use_ids = set()
        if i > 0:
            prev_assistant = history[i - 1].get("assistantResponseMessage")
            if prev_assistant:
                for tu in prev_assistant.get("toolUses", []):
                    tool_use_id = tu.get("toolUseId")
                    if tool_use_id:
                        prev_tool_use_ids.add(tool_use_id)

        # Filter out orphaned tool results
        if prev_tool_use_ids:
            ctx["toolResults"] = [
                tr for tr in ctx["toolResults"]
                if tr.get("toolUseId") in prev_tool_use_ids
            ]
        else:
            # No preceding assistant with tool uses, remove all tool results
            del ctx["toolResults"]
            if not ctx:
                del user_msg["userInputMessageContext"]


def trim_payload_to_limit(
    payload: Dict[str, Any],
    max_bytes: int = KIRO_MAX_PAYLOAD_BYTES,
) -> PayloadTrimStats:
    """Trim oldest history entries to fit payload under size limit.

    Modifies payload in-place.

    Returns:
        PayloadTrimStats with trimming details.
    """
    history = payload.get("conversationState", {}).get("history", [])
    original_entries = len(history)
    original_bytes = check_payload_size(payload)

    if original_bytes <= max_bytes:
        return PayloadTrimStats(
            original_bytes=original_bytes,
            final_bytes=original_bytes,
            original_entries=original_entries,
            final_entries=original_entries,
            trimmed=False,
        )

    # Strip empty toolUses first
    _strip_empty_tool_uses(history)

    # Trim oldest entries until under limit
    while len(history) > 2 and check_payload_size(payload) > max_bytes:
        history.pop(0)

    # Ensure history starts with user message
    history[:] = _align_to_user_message(history)

    # Repair orphaned tool results after trimming
    _repair_orphaned_tool_results(history)

    final_bytes = check_payload_size(payload)
    final_entries = len(history)

    if original_entries != final_entries:
        logger.info(
            f"Payload trimmed: {original_bytes} -> {final_bytes} bytes, "
            f"{original_entries} -> {final_entries} history entries"
        )

    return PayloadTrimStats(
        original_bytes=original_bytes,
        final_bytes=final_bytes,
        original_entries=original_entries,
        final_entries=final_entries,
        trimmed=original_entries != final_entries,
    )


def guard_payload(payload: Dict[str, Any]) -> Optional[str]:
    """Check payload size and optionally auto-trim.

    Returns:
        None if payload is OK, or an error message string if too large and
        auto-trim is disabled.
    """
    size = check_payload_size(payload)

    if size <= KIRO_MAX_PAYLOAD_BYTES:
        return None

    if AUTO_TRIM_PAYLOAD:
        stats = trim_payload_to_limit(payload)
        if stats.final_bytes > KIRO_MAX_PAYLOAD_BYTES:
            return (
                f"Payload size ({stats.final_bytes} bytes) exceeds Kiro API limit "
                f"({KIRO_MAX_PAYLOAD_BYTES} bytes) even after trimming. "
                f"Try reducing the number of tools or message history."
            )
        return None

    return (
        f"Payload size ({size} bytes) exceeds Kiro API limit "
        f"({KIRO_MAX_PAYLOAD_BYTES} bytes). "
        f"Enable KIRO_AUTO_TRIM_PAYLOAD=true to auto-trim, "
        f"or reduce tools/history manually."
    )
