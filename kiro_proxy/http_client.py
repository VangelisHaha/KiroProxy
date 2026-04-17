"""Shared HTTP client settings for outbound requests."""

from __future__ import annotations

import os
from typing import Union

_warned_insecure = False


def get_httpx_verify_setting() -> Union[bool, str]:
    """Return httpx `verify` setting.

    Priority:
    1) `KIRO_PROXY_CA_BUNDLE` -> custom CA bundle path
    2) `KIRO_PROXY_INSECURE_TLS` truthy -> disable TLS verification
    3) default -> enable TLS verification
    """
    ca_bundle = os.getenv("KIRO_PROXY_CA_BUNDLE", "").strip()
    if ca_bundle:
        return ca_bundle

    insecure = os.getenv("KIRO_PROXY_INSECURE_TLS", "").strip().lower()
    if insecure in {"1", "true", "yes", "on"}:
        global _warned_insecure
        if not _warned_insecure:
            print("[HTTP] TLS verification disabled by KIRO_PROXY_INSECURE_TLS")
            _warned_insecure = True
        return False

    return True
