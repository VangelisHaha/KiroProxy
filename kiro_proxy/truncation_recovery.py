"""Truncation recovery system for handling upstream Kiro API limitations.

Generates synthetic messages to inform the model about truncation.
Only activates when truncation is actually detected.

When Kiro API truncates a large tool call payload or content mid-stream,
we inject a synthetic message so the model knows its output was cut off
and can adapt its approach instead of repeating the same operation.

Inspired by kiro-gateway's truncation_recovery.py.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .logger import get_logger
from .env_config import TRUNCATION_RECOVERY

logger = get_logger("truncation_recovery")


@dataclass
class TruncationState:
    """Tracks truncation state across a conversation."""
    was_truncated: bool = False
    truncated_tool_name: Optional[str] = None
    truncated_tool_use_id: Optional[str] = None
    truncation_info: Dict[str, Any] = field(default_factory=dict)

    def mark_truncated(
        self,
        tool_name: Optional[str] = None,
        tool_use_id: Optional[str] = None,
        info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark that truncation was detected."""
        self.was_truncated = True
        self.truncated_tool_name = tool_name
        self.truncated_tool_use_id = tool_use_id
        self.truncation_info = info or {}
        logger.warning(
            f"Truncation detected: tool={tool_name}, id={tool_use_id}"
        )

    def clear(self) -> None:
        """Clear truncation state after recovery message is injected."""
        self.was_truncated = False
        self.truncated_tool_name = None
        self.truncated_tool_use_id = None
        self.truncation_info = {}


def should_inject_recovery() -> bool:
    """Check if truncation recovery is enabled."""
    return TRUNCATION_RECOVERY


def detect_truncation(response_text: str, tool_calls: list) -> bool:
    """Detect if a response was truncated.

    Heuristics:
    - Response ends mid-JSON (unbalanced braces/brackets)
    - Tool call arguments are invalid JSON
    - Response ends with incomplete markdown code block
    """
    if not response_text and not tool_calls:
        return False

    # Check for unbalanced JSON in response
    if response_text:
        open_braces = response_text.count("{") - response_text.count("}")
        open_brackets = response_text.count("[") - response_text.count("]")
        if open_braces > 2 or open_brackets > 2:
            return True

        # Check for unclosed markdown code blocks
        backtick_count = response_text.count("```")
        if backtick_count % 2 != 0:
            return True

    # Check tool call arguments
    import json
    for tc in tool_calls:
        args = tc.get("arguments") or tc.get("input") or ""
        if isinstance(args, str) and args.strip():
            try:
                json.loads(args)
            except json.JSONDecodeError:
                return True

    return False


def generate_truncation_tool_result(
    tool_name: str,
    tool_use_id: str,
    truncation_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate synthetic tool_result for a truncated tool call.

    The message is carefully worded to:
    - Acknowledge the API limitation (not the model's fault)
    - Warn against repeating the same operation
    - Not give overly specific instructions
    """
    content = (
        "[API Limitation] Your tool call was truncated by the upstream API "
        "due to output size limits.\n\n"
        "If the tool result below shows an error or unexpected behavior, "
        "this is likely a CONSEQUENCE of the truncation, not the root cause. "
        "The tool call itself was cut off before it could be fully transmitted.\n\n"
        "Repeating the exact same operation will be truncated again. "
        "Consider adapting your approach."
    )

    logger.debug(
        f"Generated synthetic tool_result for truncated tool '{tool_name}' "
        f"(id={tool_use_id})"
    )

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": True,
    }


def generate_truncation_notice() -> str:
    """Generate a notice message about content truncation.

    Used when the model's text content (not tool call) was truncated.
    """
    return (
        "[System Notice] Your previous response was truncated by the upstream API "
        "due to output size limits. The content was cut off before completion. "
        "Please be aware of this limitation and consider shorter responses "
        "or breaking your output into smaller parts."
    )


def inject_truncation_recovery(
    messages: list,
    truncation_state: TruncationState,
) -> list:
    """Inject truncation recovery messages into the conversation if needed.

    Modifies messages in-place and clears the truncation state.

    Returns:
        The modified messages list.
    """
    if not should_inject_recovery():
        return messages

    if not truncation_state.was_truncated:
        return messages

    if truncation_state.truncated_tool_use_id:
        recovery = generate_truncation_tool_result(
            tool_name=truncation_state.truncated_tool_name or "unknown",
            tool_use_id=truncation_state.truncated_tool_use_id,
        )
        # Add as a tool_result in the next user message
        messages.append({
            "role": "user",
            "content": [recovery],
        })
    else:
        # Content truncation - add as system notice
        notice = generate_truncation_notice()
        messages.append({
            "role": "user",
            "content": notice,
        })

    truncation_state.clear()
    return messages
