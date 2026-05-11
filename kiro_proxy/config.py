"""Configuration module.

This module provides backward-compatible access to configuration values.
New code should import from env_config directly.
Settings can be overridden via .env file or environment variables.
"""
from pathlib import Path

from .env_config import (
    KIRO_REGION,
    KIRO_API_REGION,
    get_kiro_api_url,
    get_kiro_models_url,
    VPN_PROXY_URL,
    KIRO_MAX_PAYLOAD_BYTES,
    AUTO_TRIM_PAYLOAD,
    TRUNCATION_RECOVERY,
    THINKING_ENABLED,
    THINKING_MAX_TOKENS,
    THINKING_BUDGET_CAP,
    THINKING_HANDLING,
    FIRST_TOKEN_TIMEOUT,
    STREAMING_READ_TIMEOUT,
    FIRST_TOKEN_MAX_RETRIES,
    MODEL_CACHE_TTL,
    MAX_RETRIES,
    BASE_RETRY_DELAY,
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    CIRCUIT_BREAKER_MAX_BACKOFF,
    CIRCUIT_BREAKER_RETRY_CHANCE,
)
from .model_resolver import resolve_model, normalize_model_name, get_model_cache

# Backward-compatible constants
_region = KIRO_API_REGION or KIRO_REGION
KIRO_API_URL = get_kiro_api_url(_region)
MODELS_URL = get_kiro_models_url(_region)
TOKEN_PATH = Path.home() / ".aws/sso/cache/kiro-auth-token.json"

# Quota management
QUOTA_COOLDOWN_SECONDS = 300

# Legacy KIRO_MODELS set (kept for backward compatibility)
KIRO_MODELS = {"auto", "claude-sonnet-4.5", "claude-sonnet-4", "claude-haiku-4.5", "claude-opus-4.5"}

# Legacy MODEL_MAPPING dict (kept for backward compatibility, resolve_model is preferred)
MODEL_MAPPING = {
    # Claude legacy
    "claude-3-5-sonnet-20241022": "claude-sonnet-4",
    "claude-3-5-sonnet-latest": "claude-sonnet-4",
    "claude-3-5-sonnet": "claude-sonnet-4",
    "claude-3-5-haiku-20241022": "claude-haiku-4.5",
    "claude-3-5-haiku-latest": "claude-haiku-4.5",
    "claude-3-opus-20240229": "claude-opus-4.5",
    "claude-3-opus-latest": "claude-opus-4.5",
    "claude-3-sonnet-20240229": "claude-sonnet-4",
    "claude-3-haiku-20240307": "claude-haiku-4.5",
    # Claude 4
    "claude-4-sonnet": "claude-sonnet-4",
    "claude-4-opus": "claude-opus-4.5",
    # OpenAI GPT -> Claude
    "gpt-4o": "claude-sonnet-4",
    "gpt-4o-mini": "claude-haiku-4.5",
    "gpt-4-turbo": "claude-sonnet-4",
    "gpt-4": "claude-sonnet-4",
    "gpt-3.5-turbo": "claude-haiku-4.5",
    # OpenAI o-series -> Claude
    "o1": "claude-opus-4.5",
    "o1-preview": "claude-opus-4.5",
    "o1-mini": "claude-sonnet-4",
    "o3": "claude-opus-4.5",
    "o3-mini": "claude-sonnet-4",
    "o4-mini": "claude-sonnet-4",
    # Gemini -> Claude
    "gemini-2.0-flash": "claude-sonnet-4",
    "gemini-2.0-flash-thinking": "claude-opus-4.5",
    "gemini-1.5-pro": "claude-sonnet-4.5",
    "gemini-1.5-flash": "claude-sonnet-4",
    "gemini-2.5-pro": "claude-sonnet-4.5",
    "gemini-2.5-flash": "claude-sonnet-4",
    # Short aliases
    "sonnet": "claude-sonnet-4",
    "haiku": "claude-haiku-4.5",
    "opus": "claude-opus-4.5",
}


def map_model_name(model: str) -> str:
    """Map external model name to Kiro-supported name.

    Uses the new dynamic model resolver with fallback to static mapping.
    """
    resolution = resolve_model(model or "")
    return resolution.internal_id
