"""Pydantic models for request/response validation.

Provides typed models for:
- Anthropic Messages API
- OpenAI Chat Completions API
- Internal configuration

These models serve as documentation and optional validation.
Handlers can use them for stricter input checking.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ==============================================================================
# Anthropic Models
# ==============================================================================

class AnthropicThinking(BaseModel):
    """Anthropic thinking configuration."""
    type: Literal["enabled", "adaptive"] = "enabled"
    budget_tokens: Optional[int] = None
    effort: Optional[Literal["low", "medium", "high"]] = None


class AnthropicToolInputSchema(BaseModel):
    """Tool input schema definition."""
    type: str = "object"
    properties: Dict[str, Any] = Field(default_factory=dict)
    required: Optional[List[str]] = None


class AnthropicTool(BaseModel):
    """Anthropic tool definition."""
    name: str
    description: Optional[str] = None
    input_schema: AnthropicToolInputSchema = Field(default_factory=AnthropicToolInputSchema)
    cache_control: Optional[Dict[str, str]] = None


class AnthropicMessagesRequest(BaseModel):
    """Anthropic /v1/messages request body."""
    model: str = "claude-sonnet-4"
    messages: List[Dict[str, Any]]
    system: Optional[Any] = None
    max_tokens: int = 8192
    stream: bool = False
    tools: Optional[List[AnthropicTool]] = None
    tool_choice: Optional[Dict[str, Any]] = None
    thinking: Optional[AnthropicThinking] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class AnthropicContentBlock(BaseModel):
    """Content block in Anthropic response."""
    type: str
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    thinking: Optional[str] = None


class AnthropicUsage(BaseModel):
    """Token usage in Anthropic response."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None


class AnthropicMessagesResponse(BaseModel):
    """Anthropic /v1/messages response body."""
    id: str
    type: str = "message"
    role: str = "assistant"
    content: List[AnthropicContentBlock]
    model: str
    stop_reason: Optional[str] = None
    stop_sequence: Optional[str] = None
    usage: AnthropicUsage


# ==============================================================================
# OpenAI Models
# ==============================================================================

class OpenAIFunctionDef(BaseModel):
    """OpenAI function definition."""
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class OpenAIToolDef(BaseModel):
    """OpenAI tool definition."""
    type: str = "function"
    function: OpenAIFunctionDef


class OpenAIChatRequest(BaseModel):
    """OpenAI /v1/chat/completions request body."""
    model: str = "gpt-4o"
    messages: List[Dict[str, Any]]
    stream: bool = False
    tools: Optional[List[OpenAIToolDef]] = None
    tool_choice: Optional[Any] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    n: int = 1
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None


class OpenAIFunctionCall(BaseModel):
    """Function call in OpenAI response."""
    name: str
    arguments: str


class OpenAIToolCall(BaseModel):
    """Tool call in OpenAI response."""
    id: str
    type: str = "function"
    function: OpenAIFunctionCall


class OpenAIChoiceMessage(BaseModel):
    """Message in OpenAI choice."""
    role: str = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[OpenAIToolCall]] = None
    refusal: Optional[str] = None


class OpenAIChoice(BaseModel):
    """Choice in OpenAI response."""
    index: int = 0
    message: OpenAIChoiceMessage
    finish_reason: Optional[str] = None


class OpenAIUsage(BaseModel):
    """Token usage in OpenAI response."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatResponse(BaseModel):
    """OpenAI /v1/chat/completions response body."""
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[OpenAIChoice]
    usage: OpenAIUsage
    system_fingerprint: Optional[str] = None


# ==============================================================================
# Internal Models
# ==============================================================================

class ModelResolutionInfo(BaseModel):
    """Information about how a model name was resolved."""
    internal_id: str
    source: str
    original_request: str
    normalized: str
    is_verified: bool


class PayloadTrimInfo(BaseModel):
    """Information about payload trimming."""
    original_bytes: int
    final_bytes: int
    original_entries: int
    final_entries: int
    trimmed: bool


class AccountStatus(BaseModel):
    """Account status information."""
    id: str
    name: str
    enabled: bool
    status: str
    available: bool
    request_count: int
    error_count: int
    cooldown_remaining: Optional[float] = None
    token_expired: Optional[bool] = None
    token_expiring_soon: Optional[bool] = None
    auth_method: Optional[str] = None
    has_refresh_token: Optional[bool] = None
