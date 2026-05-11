"""Environment-based configuration module.

Loads settings from .env file and environment variables using python-dotenv.
All configuration is centralized here for easy management.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

# Load .env file
load_dotenv()


# ==============================================================================
# Server Settings
# ==============================================================================

SERVER_HOST: str = os.getenv("KIRO_SERVER_HOST", "0.0.0.0")
SERVER_PORT: int = int(os.getenv("KIRO_SERVER_PORT", "8080"))

# ==============================================================================
# Proxy / VPN Settings
# ==============================================================================

VPN_PROXY_URL: str = os.getenv("KIRO_VPN_PROXY_URL", "")

# ==============================================================================
# Kiro API Settings
# ==============================================================================

KIRO_API_HOST_TEMPLATE: str = "https://q.{region}.amazonaws.com"
KIRO_MODELS_HOST_TEMPLATE: str = "https://q.{region}.amazonaws.com"
KIRO_REFRESH_URL_TEMPLATE: str = "https://prod.{region}.auth.desktop.kiro.dev/refreshToken"
AWS_SSO_OIDC_URL_TEMPLATE: str = "https://oidc.{region}.amazonaws.com/token"

KIRO_REGION: str = os.getenv("KIRO_REGION", "us-east-1")
KIRO_API_REGION: str = os.getenv("KIRO_API_REGION", "")

# ==============================================================================
# Authentication
# ==============================================================================

KIRO_CREDS_FILE: str = os.getenv("KIRO_CREDS_FILE", "")
KIRO_CLI_DB_FILE: str = os.getenv("KIRO_CLI_DB_FILE", "")
SQLITE_READONLY: bool = os.getenv("KIRO_SQLITE_READONLY", "false").lower() in ("true", "1", "yes")

# ==============================================================================
# Token Settings
# ==============================================================================

TOKEN_REFRESH_THRESHOLD: int = int(os.getenv("KIRO_TOKEN_REFRESH_THRESHOLD", "600"))

# ==============================================================================
# Retry Configuration
# ==============================================================================

MAX_RETRIES: int = int(os.getenv("KIRO_MAX_RETRIES", "3"))
BASE_RETRY_DELAY: float = float(os.getenv("KIRO_BASE_RETRY_DELAY", "1.0"))

# ==============================================================================
# Payload Guard Settings
# ==============================================================================

KIRO_MAX_PAYLOAD_BYTES: int = int(os.getenv("KIRO_MAX_PAYLOAD_BYTES", "600000"))
AUTO_TRIM_PAYLOAD: bool = os.getenv("KIRO_AUTO_TRIM_PAYLOAD", "true").lower() in ("true", "1", "yes")

# ==============================================================================
# Truncation Recovery
# ==============================================================================

TRUNCATION_RECOVERY: bool = os.getenv("KIRO_TRUNCATION_RECOVERY", "true").lower() in ("true", "1", "yes")

# ==============================================================================
# Extended Thinking Settings
# ==============================================================================

THINKING_ENABLED: bool = os.getenv("KIRO_THINKING_ENABLED", "true").lower() in ("true", "1", "yes")
THINKING_MAX_TOKENS: int = int(os.getenv("KIRO_THINKING_MAX_TOKENS", "4000"))
THINKING_BUDGET_CAP: int = int(os.getenv("KIRO_THINKING_BUDGET_CAP", "10000"))
THINKING_HANDLING: str = os.getenv("KIRO_THINKING_HANDLING", "as_reasoning_content").lower()
if THINKING_HANDLING not in ("as_reasoning_content", "remove", "pass", "strip_tags"):
    THINKING_HANDLING = "as_reasoning_content"
THINKING_OPEN_TAGS: List[str] = ["<thinking>", "<think>", "<reasoning>", "<thought>"]
THINKING_INITIAL_BUFFER_SIZE: int = int(os.getenv("KIRO_THINKING_INITIAL_BUFFER_SIZE", "20"))

# ==============================================================================
# Streaming Settings
# ==============================================================================

FIRST_TOKEN_TIMEOUT: float = float(os.getenv("KIRO_FIRST_TOKEN_TIMEOUT", "15"))
STREAMING_READ_TIMEOUT: float = float(os.getenv("KIRO_STREAMING_READ_TIMEOUT", "300"))
FIRST_TOKEN_MAX_RETRIES: int = int(os.getenv("KIRO_FIRST_TOKEN_MAX_RETRIES", "3"))

# ==============================================================================
# Model Cache Settings
# ==============================================================================

MODEL_CACHE_TTL: int = int(os.getenv("KIRO_MODEL_CACHE_TTL", "3600"))

# ==============================================================================
# Logging Settings
# ==============================================================================

LOG_LEVEL: str = os.getenv("KIRO_LOG_LEVEL", "INFO").upper()
LOG_FILE: str = os.getenv("KIRO_LOG_FILE", "")
DEBUG_MODE: str = os.getenv("KIRO_DEBUG_MODE", "off").lower()

# ==============================================================================
# Rate Limiting
# ==============================================================================

RATE_LIMIT_MIN_INTERVAL: float = float(os.getenv("KIRO_RATE_LIMIT_MIN_INTERVAL", "0"))
RATE_LIMIT_PER_ACCOUNT_RPM: int = int(os.getenv("KIRO_RATE_LIMIT_PER_ACCOUNT_RPM", "0"))
RATE_LIMIT_GLOBAL_RPM: int = int(os.getenv("KIRO_RATE_LIMIT_GLOBAL_RPM", "0"))

# ==============================================================================
# Circuit Breaker Settings
# ==============================================================================

CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = int(os.getenv("KIRO_CB_RECOVERY_TIMEOUT", "60"))
CIRCUIT_BREAKER_MAX_BACKOFF: float = float(os.getenv("KIRO_CB_MAX_BACKOFF", "1440.0"))
CIRCUIT_BREAKER_RETRY_CHANCE: float = float(os.getenv("KIRO_CB_RETRY_CHANCE", "0.1"))

# ==============================================================================
# Web Search
# ==============================================================================

WEB_SEARCH_ENABLED: bool = os.getenv("KIRO_WEB_SEARCH_ENABLED", "true").lower() in ("true", "1", "yes")

# ==============================================================================
# UI Settings
# ==============================================================================

UI_LANGUAGE: str = os.getenv("KIRO_UI_LANGUAGE", "zh")


def get_kiro_api_url(region: Optional[str] = None) -> str:
    """Get the Kiro generateAssistantResponse API URL."""
    r = region or KIRO_API_REGION or KIRO_REGION
    host = KIRO_API_HOST_TEMPLATE.format(region=r)
    return f"{host}/generateAssistantResponse"


def get_kiro_models_url(region: Optional[str] = None) -> str:
    """Get the Kiro ListAvailableModels API URL."""
    r = region or KIRO_API_REGION or KIRO_REGION
    host = KIRO_MODELS_HOST_TEMPLATE.format(region=r)
    return f"{host}/ListAvailableModels"


def get_kiro_refresh_url(region: Optional[str] = None) -> str:
    """Get the token refresh URL for Kiro Desktop Auth."""
    r = region or KIRO_REGION
    return KIRO_REFRESH_URL_TEMPLATE.format(region=r)


def get_aws_sso_oidc_url(region: Optional[str] = None) -> str:
    """Get the AWS SSO OIDC token URL."""
    r = region or KIRO_REGION
    return AWS_SSO_OIDC_URL_TEMPLATE.format(region=r)
