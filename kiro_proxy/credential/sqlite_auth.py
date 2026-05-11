"""SQLite-based authentication for kiro-cli credentials.

Reads credentials directly from kiro-cli's SQLite database
(~/.local/share/kiro-cli/data.sqlite3 on Linux,
 ~/Library/Application Support/kiro-cli/data.sqlite3 on macOS).

This provides a more reliable auth method than reading JSON cache files,
as kiro-cli manages the database directly.

Inspired by kiro-gateway and kirocc implementations.
"""

import os
import json
import platform
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..logger import get_logger
from .types import KiroCredentials

logger = get_logger("sqlite_auth")

# Default DB paths per platform
_DEFAULT_DB_PATHS = {
    "Linux": [
        Path.home() / ".local/share/kiro-cli/data.sqlite3",
        Path.home() / ".local/share/amazon-q/data.sqlite3",
    ],
    "Darwin": [
        Path.home() / "Library/Application Support/kiro-cli/data.sqlite3",
        Path.home() / "Library/Application Support/amazon-q/data.sqlite3",
    ],
    "Windows": [
        Path.home() / "AppData/Roaming/kiro-cli/data.sqlite3",
        Path.home() / "AppData/Roaming/amazon-q/data.sqlite3",
    ],
}


def find_default_db_path() -> Optional[Path]:
    """Find the default kiro-cli SQLite DB path for the current platform."""
    system = platform.system()
    candidates = _DEFAULT_DB_PATHS.get(system, [])

    for path in candidates:
        if path.exists():
            logger.debug(f"Found kiro-cli DB at {path}")
            return path

    return None


def _read_db(db_path: Path) -> Dict[str, Any]:
    """Read credentials from kiro-cli SQLite database.

    Returns a dict with all available credential fields.
    """
    result: Dict[str, Any] = {}

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Read from the state table (kiro-cli stores auth data here)
        cursor.execute("SELECT key, value FROM state")
        rows = cursor.fetchall()

        for row in rows:
            key = row["key"]
            value = row["value"]

            if key == "accessToken":
                result["accessToken"] = value
            elif key == "refreshToken":
                result["refreshToken"] = value
            elif key == "expiresAt":
                result["expiresAt"] = value
            elif key == "profileArn":
                result["profileArn"] = value
                # Extract region from profile ARN
                # arn:aws:codewhisperer:us-east-1:...
                if value and ":codewhisperer:" in value:
                    parts = value.split(":")
                    if len(parts) >= 4:
                        result["region"] = parts[3]
            elif key == "startUrl":
                result["startUrl"] = value
            elif key == "region":
                result["region"] = value
            elif key == "ssoRegion":
                result["idcRegion"] = value

        # Try to read OIDC client credentials
        try:
            cursor.execute(
                "SELECT key, value FROM state WHERE key LIKE 'oidc%' OR key LIKE 'client%'"
            )
            for row in cursor.fetchall():
                key = row["key"]
                value = row["value"]
                if key in ("oidcClientId", "clientId"):
                    result["clientId"] = value
                elif key in ("oidcClientSecret", "clientSecret"):
                    result["clientSecret"] = value
        except sqlite3.OperationalError:
            pass

        conn.close()

    except sqlite3.OperationalError as e:
        logger.warning(f"Failed to read kiro-cli DB: {e}")
    except Exception as e:
        logger.error(f"Unexpected error reading kiro-cli DB: {e}")

    return result


def load_credentials_from_sqlite(
    db_path: Optional[str] = None,
) -> Optional[KiroCredentials]:
    """Load credentials from kiro-cli's SQLite database.

    Args:
        db_path: Path to the SQLite DB. If None, auto-detects.

    Returns:
        KiroCredentials if found, None otherwise.
    """
    if db_path:
        path = Path(db_path)
    else:
        path = find_default_db_path()

    if not path or not path.exists():
        logger.debug("No kiro-cli SQLite DB found")
        return None

    logger.info(f"Loading credentials from kiro-cli DB: {path}")
    data = _read_db(path)

    if not data.get("accessToken"):
        logger.warning("No access token found in kiro-cli DB")
        return None

    # Set auth method based on available credentials
    if data.get("clientId") and data.get("clientSecret"):
        data["authMethod"] = "idc"
    else:
        data["authMethod"] = "social"

    creds = KiroCredentials.from_dict(data)

    if not creds.idc_region:
        creds.idc_region = creds.region or "us-east-1"

    logger.info(
        f"Loaded credentials from kiro-cli DB: "
        f"method={creds.auth_method}, region={creds.region}"
    )
    return creds


def write_token_to_sqlite(
    db_path: str,
    access_token: str,
    expires_at: str,
    refresh_token: Optional[str] = None,
) -> bool:
    """Write refreshed token back to kiro-cli's SQLite database.

    Args:
        db_path: Path to the SQLite DB.
        access_token: New access token.
        expires_at: New expiration time.
        refresh_token: Optionally updated refresh token.

    Returns:
        True if successful.
    """
    from ..env_config import SQLITE_READONLY

    if SQLITE_READONLY:
        logger.debug("SQLite write-back disabled (read-only mode)")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            ("accessToken", access_token),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
            ("expiresAt", expires_at),
        )

        if refresh_token:
            cursor.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                ("refreshToken", refresh_token),
            )

        conn.commit()
        conn.close()
        logger.debug("Token written back to kiro-cli DB")
        return True

    except Exception as e:
        logger.error(f"Failed to write token to kiro-cli DB: {e}")
        return False
