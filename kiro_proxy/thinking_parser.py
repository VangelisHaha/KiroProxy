"""Thinking block parser for streaming responses.

Implements a finite state machine (FSM) for reliable parsing of thinking blocks
(<thinking>, <think>, <reasoning>, etc.) that may be split across multiple
network chunks.

Key features:
- Tag detection ONLY at the start of response
- "Cautious" sending - buffers potential tag fragments to avoid splitting tags
- After closing tag - all content is treated as regular content
- Support for multiple tag formats
- Multiple output handling modes

Inspired by kiro-gateway's thinking_parser.py.
"""

from enum import IntEnum
from dataclasses import dataclass, field
from typing import List, Optional

from .logger import get_logger
from .env_config import (
    THINKING_HANDLING,
    THINKING_OPEN_TAGS,
    THINKING_INITIAL_BUFFER_SIZE,
)

logger = get_logger("thinking_parser")


class ParserState(IntEnum):
    """States of the thinking block parser FSM.

    PRE_CONTENT: Initial state, buffering to detect opening tag
    IN_THINKING: Inside thinking block, buffering until closing tag
    STREAMING: Regular streaming, no more thinking block detection
    """
    PRE_CONTENT = 0
    IN_THINKING = 1
    STREAMING = 2


@dataclass
class ThinkingResult:
    """Result of processing a text chunk through the parser."""
    thinking_content: Optional[str] = None
    regular_content: Optional[str] = None
    is_thinking_complete: bool = False


@dataclass
class ThinkingParser:
    """FSM-based parser for thinking blocks in streaming responses.

    Usage:
        parser = ThinkingParser()
        for chunk in stream:
            result = parser.process(chunk)
            if result.thinking_content:
                # Handle thinking content
            if result.regular_content:
                # Handle regular content
    """
    state: ParserState = ParserState.PRE_CONTENT
    buffer: str = ""
    thinking_buffer: str = ""
    matched_open_tag: Optional[str] = None
    handling_mode: str = field(default_factory=lambda: THINKING_HANDLING)

    def _get_close_tag(self) -> Optional[str]:
        """Get the closing tag matching the detected opening tag."""
        if not self.matched_open_tag:
            return None
        return self.matched_open_tag.replace("<", "</")

    def process(self, chunk: str) -> ThinkingResult:
        """Process a text chunk through the FSM.

        Returns:
            ThinkingResult with thinking and/or regular content.
        """
        if not chunk:
            return ThinkingResult()

        if self.state == ParserState.PRE_CONTENT:
            return self._handle_pre_content(chunk)
        elif self.state == ParserState.IN_THINKING:
            return self._handle_in_thinking(chunk)
        else:
            return ThinkingResult(regular_content=chunk)

    def _handle_pre_content(self, chunk: str) -> ThinkingResult:
        """Handle initial buffering to detect opening thinking tag."""
        self.buffer += chunk

        # Skip leading whitespace for tag detection
        stripped = self.buffer.lstrip()

        # Check if we have enough data to decide
        if len(stripped) < THINKING_INITIAL_BUFFER_SIZE:
            # Not enough data yet, check if any tag prefix matches
            for tag in THINKING_OPEN_TAGS:
                if tag.startswith(stripped) or stripped.startswith(tag):
                    return ThinkingResult()  # Keep buffering
            # No tag prefix match, switch to streaming
            self.state = ParserState.STREAMING
            content = self.buffer
            self.buffer = ""
            return ThinkingResult(regular_content=content)

        # Check for opening tag match
        for tag in THINKING_OPEN_TAGS:
            if stripped.startswith(tag):
                self.matched_open_tag = tag
                self.state = ParserState.IN_THINKING
                # Content after the opening tag goes to thinking buffer
                after_tag = stripped[len(tag):]
                self.thinking_buffer = after_tag
                self.buffer = ""
                return ThinkingResult()

        # No tag found, switch to streaming
        self.state = ParserState.STREAMING
        content = self.buffer
        self.buffer = ""
        return ThinkingResult(regular_content=content)

    def _handle_in_thinking(self, chunk: str) -> ThinkingResult:
        """Handle content inside a thinking block."""
        self.thinking_buffer += chunk

        close_tag = self._get_close_tag()
        if not close_tag:
            self.state = ParserState.STREAMING
            return ThinkingResult(regular_content=self.thinking_buffer)

        # Check for closing tag
        close_pos = self.thinking_buffer.find(close_tag)
        if close_pos == -1:
            # Check if buffer ends with partial closing tag
            for i in range(1, len(close_tag)):
                if self.thinking_buffer.endswith(close_tag[:i]):
                    return ThinkingResult()  # Keep buffering
            return ThinkingResult()

        # Found closing tag
        thinking_content = self.thinking_buffer[:close_pos]
        after_close = self.thinking_buffer[close_pos + len(close_tag):]

        self.thinking_buffer = ""
        self.state = ParserState.STREAMING

        result = ThinkingResult(is_thinking_complete=True)

        # Handle thinking content based on mode
        if self.handling_mode == "as_reasoning_content":
            result.thinking_content = thinking_content
            if after_close.strip():
                result.regular_content = after_close
        elif self.handling_mode == "remove":
            # Discard thinking content
            if after_close.strip():
                result.regular_content = after_close
        elif self.handling_mode == "pass":
            # Keep with original tags
            full = f"{self.matched_open_tag}{thinking_content}{close_tag}"
            if after_close:
                full += after_close
            result.regular_content = full
        elif self.handling_mode == "strip_tags":
            # Keep content but remove tags
            content = thinking_content
            if after_close:
                content += after_close
            result.regular_content = content

        return result

    def flush(self) -> ThinkingResult:
        """Flush any remaining buffered content.

        Call this when the stream ends.
        """
        result = ThinkingResult()

        if self.state == ParserState.PRE_CONTENT and self.buffer:
            result.regular_content = self.buffer
            self.buffer = ""

        elif self.state == ParserState.IN_THINKING and self.thinking_buffer:
            if self.handling_mode == "as_reasoning_content":
                result.thinking_content = self.thinking_buffer
            elif self.handling_mode == "remove":
                pass  # Discard
            elif self.handling_mode == "pass":
                result.regular_content = (
                    f"{self.matched_open_tag}{self.thinking_buffer}"
                )
            elif self.handling_mode == "strip_tags":
                result.regular_content = self.thinking_buffer
            self.thinking_buffer = ""
            result.is_thinking_complete = True

        self.state = ParserState.STREAMING
        return result
