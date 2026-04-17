"""凭证数据类型"""
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class CredentialStatus(Enum):
    """凭证状态"""
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"
    SUSPENDED = "suspended"  # 账号被封禁


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _repair_json(raw: str) -> str:
    """尝试修复常见 JSON 语法错误。"""
    repaired = raw
    # 去掉尾逗号
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    # 为裸 key 加引号
    repaired = re.sub(r'([{,]\s*)([A-Za-z0-9_]+)\s*:', r'\1"\2":', repaired)
    return repaired


def _extract_credentials_from_corrupted_json(raw: str) -> Dict[str, Any]:
    """从损坏 JSON 文本里提取关键字段。"""
    patterns = {
        "accessToken": r'"accessToken"\s*:\s*"([^"]+)"',
        "refreshToken": r'"refreshToken"\s*:\s*"([^"]+)"',
        "clientId": r'"clientId"\s*:\s*"([^"]+)"',
        "clientSecret": r'"clientSecret"\s*:\s*"([^"]+)"',
        "clientIdHash": r'"clientIdHash"\s*:\s*"([^"]+)"',
        "profileArn": r'"profileArn"\s*:\s*"([^"]+)"',
        "region": r'"region"\s*:\s*"([^"]+)"',
        "idcRegion": r'"idcRegion"\s*:\s*"([^"]+)"',
        "authMethod": r'"authMethod"\s*:\s*"([^"]+)"',
        "expiresAt": r'"expiresAt"\s*:\s*"([^"]+)"',
        "expire": r'"expire"\s*:\s*"([^"]+)"',
        "startUrl": r'"startUrl"\s*:\s*"([^"]+)"',
        "uuid": r'"uuid"\s*:\s*"([^"]+)"',
    }

    extracted: Dict[str, Any] = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, raw)
        if match and match.group(1):
            extracted[field] = match.group(1)
    return extracted


def _load_json_with_recovery(path: Path) -> Dict[str, Any]:
    """读取 JSON 并做容错恢复。"""
    raw = path.read_text(encoding="utf-8", errors="ignore")

    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    try:
        repaired = _repair_json(raw)
        data = json.loads(repaired)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass

    return _extract_credentials_from_corrupted_json(raw)


def _pick(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _normalize_auth_method(auth_method: Optional[str], client_id: Optional[str], client_secret: Optional[str]) -> str:
    method = _as_text(auth_method).lower()
    if method in {"social", "idc", "builder-id", "builder_id"}:
        if method in {"builder-id", "builder_id"}:
            return "idc"
        return method
    if client_id and client_secret:
        return "idc"
    return "social"


@dataclass
class KiroCredentials:
    """Kiro 凭证信息"""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    profile_arn: Optional[str] = None
    expires_at: Optional[str] = None
    region: str = "us-east-1"
    idc_region: Optional[str] = None
    auth_method: str = "social"
    client_id_hash: Optional[str] = None
    uuid: Optional[str] = None
    start_url: Optional[str] = None
    last_refresh: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KiroCredentials":
        """从字典加载凭证（支持 snake/camel key）。"""
        access_token = _pick(data, "accessToken", "access_token")
        refresh_token = _pick(data, "refreshToken", "refresh_token")
        client_id = _pick(data, "clientId", "client_id")
        client_secret = _pick(data, "clientSecret", "client_secret")
        profile_arn = _pick(data, "profileArn", "profile_arn")
        expires_at = _pick(data, "expiresAt", "expires_at", "expire")
        region = _pick(data, "region")
        idc_region = _pick(data, "idcRegion", "idc_region")
        auth_method = _pick(data, "authMethod", "auth_method")
        client_id_hash = _pick(data, "clientIdHash", "client_id_hash")
        last_refresh = _pick(data, "lastRefresh", "last_refresh")
        start_url = _pick(data, "startUrl", "start_url")
        uuid = _pick(data, "uuid")

        return cls(
            access_token=_as_text(access_token) or None,
            refresh_token=_as_text(refresh_token) or None,
            client_id=_as_text(client_id) or None,
            client_secret=_as_text(client_secret) or None,
            profile_arn=_as_text(profile_arn) or None,
            expires_at=_as_text(expires_at) or None,
            region=_as_text(region) or "us-east-1",
            idc_region=_as_text(idc_region) or None,
            auth_method=_normalize_auth_method(_as_text(auth_method) or None, _as_text(client_id) or None, _as_text(client_secret) or None),
            client_id_hash=_as_text(client_id_hash) or None,
            uuid=_as_text(uuid) or None,
            start_url=_as_text(start_url) or None,
            last_refresh=_as_text(last_refresh) or None,
        )

    @classmethod
    def load_merged_from_cache(cls, token_path: str) -> "KiroCredentials":
        """加载主 token 并自动合并同目录其它 JSON 补全字段。"""
        path = Path(token_path)
        if not path.exists():
            raise FileNotFoundError(f"Credential file not found: {token_path}")

        merged = _load_json_with_recovery(path)

        cache_dir = path.parent
        if cache_dir.exists():
            for item in sorted(cache_dir.glob("*.json")):
                if item == path:
                    continue
                try:
                    extra = _load_json_with_recovery(item)
                except Exception:
                    continue

                if not isinstance(extra, dict) or not extra:
                    continue

                # 仅补空字段，避免其它缓存覆盖主 token 最新值。
                for key, value in extra.items():
                    if value is None:
                        continue
                    existing = merged.get(key)
                    if existing is None or _as_text(existing) == "":
                        merged[key] = value

        creds = cls.from_dict(merged)
        if not creds.idc_region:
            creds.idc_region = creds.region or "us-east-1"
        return creds
    
    @classmethod
    def from_file(cls, path: str) -> "KiroCredentials":
        """从文件加载凭证"""
        path_obj = Path(path)
        data = _load_json_with_recovery(path_obj)
        if not data:
            raise ValueError(f"Credential file is empty or unreadable: {path}")
        return cls.from_dict(data)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "accessToken": self.access_token,
            "refreshToken": self.refresh_token,
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "profileArn": self.profile_arn,
            "expiresAt": self.expires_at,
            "region": self.region,
            "idcRegion": self.idc_region,
            "authMethod": self.auth_method,
            "clientIdHash": self.client_id_hash,
            "uuid": self.uuid,
            "startUrl": self.start_url,
            "lastRefresh": self.last_refresh,
        }
    
    def save_to_file(self, path: str):
        """保存凭证到文件"""
        existing = {}
        if Path(path).exists():
            try:
                with open(path) as f:
                    existing = json.load(f)
            except Exception:
                pass
        
        existing.update({k: v for k, v in self.to_dict().items() if v is not None})
        
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)
    
    def is_expired(self) -> bool:
        """检查 token 是否已过期"""
        if not self.expires_at:
            return True
        
        try:
            if "T" in self.expires_at:
                expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                return expires <= now + timedelta(minutes=5)
            
            expires_ts = int(self.expires_at)
            now_ts = int(time.time())
            return now_ts >= (expires_ts - 300)
        except Exception:
            return True
    
    def is_expiring_soon(self, minutes: int = 10) -> bool:
        """检查 token 是否即将过期"""
        if not self.expires_at:
            return False
        
        try:
            if "T" in self.expires_at:
                expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                return expires < now + timedelta(minutes=minutes)
            
            expires_ts = int(self.expires_at)
            now_ts = int(time.time())
            return now_ts >= (expires_ts - minutes * 60)
        except Exception:
            return False
