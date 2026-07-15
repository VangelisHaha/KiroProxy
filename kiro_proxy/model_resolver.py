"""Dynamic model resolution system.

Implements a 4-layer resolution pipeline:
1. Normalize Name - Convert client formats to Kiro format (dashes to dots, strip dates)
2. Check Dynamic Cache - Models from /ListAvailableModels API
3. Check Static Aliases - Known model name mappings
4. Pass-through - Unknown models sent to Kiro (let Kiro decide)

Inspired by kiro-gateway's model_resolver.py architecture.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .logger import get_logger
from .env_config import EXTRA_MODELS

logger = get_logger("model_resolver")

# Fallback model list when API is unreachable
FALLBACK_MODELS: List[Dict[str, str]] = [
    {"modelId": "auto"},
    {"modelId": "claude-sonnet-4"},
    {"modelId": "claude-sonnet-4.5"},
    {"modelId": "claude-haiku-4.5"},
    {"modelId": "claude-opus-4.5"},
]

# Hidden models that work but are not advertised by Kiro API
HIDDEN_MODELS: Dict[str, str] = {
    "claude-3.7-sonnet": "CLAUDE_3_7_SONNET_20250219_V1_0",
}

# Static model aliases for common client model names
MODEL_ALIASES: Dict[str, str] = {
    # Claude legacy names
    "claude-3-5-sonnet-20241022": "claude-sonnet-4",
    "claude-3-5-sonnet-latest": "claude-sonnet-4",
    "claude-3-5-sonnet": "claude-sonnet-4",
    "claude-3-5-haiku-20241022": "claude-haiku-4.5",
    "claude-3-5-haiku-latest": "claude-haiku-4.5",
    "claude-3-opus-20240229": "claude-opus-4.5",
    "claude-3-opus-latest": "claude-opus-4.5",
    "claude-3-sonnet-20240229": "claude-sonnet-4",
    "claude-3-haiku-20240307": "claude-haiku-4.5",
    # Claude 4 aliases
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
    # Cursor compatibility
    "auto-kiro": "auto",
}


@dataclass(frozen=True)
class ModelResolution:
    """Result of model resolution."""
    internal_id: str
    source: str  # "cache", "alias", "hidden", "passthrough"
    original_request: str
    normalized: str
    is_verified: bool


@dataclass
class ModelCache:
    """Cache for models retrieved from /ListAvailableModels API."""
    models: Dict[str, str] = field(default_factory=dict)
    last_updated: float = 0.0
    ttl: int = 3600  # 1 hour default

    def is_expired(self) -> bool:
        return time.time() - self.last_updated > self.ttl

    def update(self, models_data: List[Dict[str, str]]) -> None:
        self.models = {m["modelId"]: m.get("modelName", m["modelId"]) for m in models_data}
        self.last_updated = time.time()
        logger.info(f"Model cache updated with {len(self.models)} models")

    def get(self, model_id: str) -> Optional[str]:
        return self.models.get(model_id)

    def list_all(self) -> List[Dict[str, str]]:
        return [{"modelId": k, "modelName": v} for k, v in self.models.items()]


# Singleton model cache
_model_cache = ModelCache()


def get_model_cache() -> ModelCache:
    """Get the global model cache instance."""
    return _model_cache


def merge_advertised_models(
    models_data: List[Dict[str, str]],
    extra_models: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """合并模型接口返回值与本机已验证的隐藏模型，并保持顺序去重。"""
    merged = [dict(model) for model in models_data]
    known_ids = {model.get("modelId") for model in merged}
    for model_id in EXTRA_MODELS if extra_models is None else extra_models:
        if model_id and model_id not in known_ids:
            merged.append({"modelId": model_id, "modelName": model_id})
            known_ids.add(model_id)
    return merged


def normalize_model_name(name: str) -> str:
    """Normalize client model name to Kiro format.

    Transformations:
    1. claude-haiku-4-5 -> claude-haiku-4.5 (dash to dot for minor version)
    2. claude-haiku-4-5-20251001 -> claude-haiku-4.5 (strip date suffix)
    3. claude-haiku-4-5-latest -> claude-haiku-4.5 (strip 'latest' suffix)
    4. claude-sonnet-4-20250514 -> claude-sonnet-4 (strip date, no minor)
    5. claude-3-7-sonnet -> claude-3.7-sonnet (legacy format)
    6. claude-4.5-opus-high -> claude-opus-4.5 (inverted format with suffix)
    """
    if not name:
        return "claude-sonnet-4"

    # Strip whitespace
    name = name.strip()

    # Legacy 3.x format: claude-3-7-sonnet -> claude-3.7-sonnet
    legacy_match = re.match(r'^claude-(\d+)-(\d+)-(\w+)(?:-\d{8}|-latest)?$', name)
    if legacy_match:
        major, minor, variant = legacy_match.groups()
        return f"claude-{major}.{minor}-{variant}"

    # Inverted format: claude-4.5-opus-high -> claude-opus-4.5
    inverted_match = re.match(r'^claude-(\d+(?:\.\d+)?)-(\w+?)(?:-\w+)?$', name)
    if inverted_match:
        version, variant = inverted_match.groups()
        if variant in ("sonnet", "haiku", "opus"):
            return f"claude-{variant}-{version}"

    # Standard format with minor version dash: claude-haiku-4-5 -> claude-haiku-4.5
    standard_match = re.match(r'^(claude-\w+)-(\d+)-(\d+)(?:-\d{8}|-latest)?$', name)
    if standard_match:
        prefix, major, minor = standard_match.groups()
        return f"{prefix}-{major}.{minor}"

    # Strip date suffix: claude-sonnet-4-20250514 -> claude-sonnet-4
    date_match = re.match(r'^(claude-\w+-\d+(?:\.\d+)?)-\d{8}$', name)
    if date_match:
        return date_match.group(1)

    # Strip -latest suffix
    if name.endswith("-latest"):
        return name[:-7]

    return name


def resolve_model(name: str) -> ModelResolution:
    """Resolve a model name through the 4-layer pipeline.

    Returns:
        ModelResolution with the resolved model ID and metadata.
    """
    original = name
    normalized = normalize_model_name(name)

    # Layer 1: Check dynamic cache
    cache = get_model_cache()
    cached = cache.get(normalized)
    if cached is not None:
        return ModelResolution(
            internal_id=normalized,
            source="cache",
            original_request=original,
            normalized=normalized,
            is_verified=True,
        )

    # Also check if original name is in cache (e.g., "auto")
    if original != normalized:
        cached_orig = cache.get(original)
        if cached_orig is not None:
            return ModelResolution(
                internal_id=original,
                source="cache",
                original_request=original,
                normalized=normalized,
                is_verified=True,
            )

    # Layer 2: Check static aliases
    alias_target = MODEL_ALIASES.get(original) or MODEL_ALIASES.get(normalized)
    if alias_target:
        return ModelResolution(
            internal_id=alias_target,
            source="alias",
            original_request=original,
            normalized=normalized,
            is_verified=True,
        )

    if normalized in EXTRA_MODELS:
        return ModelResolution(
            internal_id=normalized,
            source="hidden",
            original_request=original,
            normalized=normalized,
            is_verified=True,
        )

    # Layer 3: Check hidden models
    hidden_target = HIDDEN_MODELS.get(normalized)
    if hidden_target:
        return ModelResolution(
            internal_id=hidden_target,
            source="hidden",
            original_request=original,
            normalized=normalized,
            is_verified=True,
        )

    # Layer 4: Fuzzy matching by keyword
    lower = normalized.lower()
    if "opus" in lower:
        return ModelResolution(
            internal_id="claude-opus-4.5",
            source="alias",
            original_request=original,
            normalized=normalized,
            is_verified=True,
        )
    if "haiku" in lower:
        return ModelResolution(
            internal_id="claude-haiku-4.5",
            source="alias",
            original_request=original,
            normalized=normalized,
            is_verified=True,
        )
    if "sonnet" in lower:
        target = "claude-sonnet-4.5" if "4.5" in lower else "claude-sonnet-4"
        return ModelResolution(
            internal_id=target,
            source="alias",
            original_request=original,
            normalized=normalized,
            is_verified=True,
        )

    # Layer 5: Pass-through (let Kiro decide)
    logger.debug(f"Model '{original}' not found in cache/aliases, passing through as '{normalized}'")
    return ModelResolution(
        internal_id=normalized,
        source="passthrough",
        original_request=original,
        normalized=normalized,
        is_verified=False,
    )
