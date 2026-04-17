"""认证前置校验"""
import os
import re
from pathlib import Path
from typing import Optional, Tuple


_PROFILE_ARN_RE = re.compile(r'profileArn":"(arn:aws:codewhisperer:[^"]+)"')


def _looks_like_profile_arn(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return value.startswith("arn:aws:codewhisperer:")


def _find_profile_arn_from_kiro_logs() -> Optional[str]:
    """从本机 Kiro 日志中提取最近使用的 profileArn。"""
    logs_root = Path.home() / "Library" / "Application Support" / "Kiro" / "logs"
    if not logs_root.exists():
        return None

    log_files = sorted(logs_root.rglob("q-client.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for log_file in log_files[:12]:
        try:
            text = log_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        matches = _PROFILE_ARN_RE.findall(text)
        if matches:
            return matches[-1]
    return None


def _apply_profile_arn(account, profile_arn: str) -> bool:
    if not _looks_like_profile_arn(profile_arn):
        return False

    creds = account.get_credentials()
    if not creds:
        return False

    creds.profile_arn = profile_arn
    try:
        creds.save_to_file(account.token_path)
    except Exception:
        # 在受限环境下可能无法写入 token 文件；保留内存中的 profileArn 继续服务。
        pass

    # profileArn 变化后，machine_id 需要重新计算
    if hasattr(account, "_machine_id"):
        account._machine_id = None
    return True


def _try_backfill_profile_arn(account) -> Optional[str]:
    """尝试从环境变量或本机日志回填 profileArn。"""
    env_arn = os.getenv("KIRO_PROFILE_ARN", "").strip()
    if _looks_like_profile_arn(env_arn) and _apply_profile_arn(account, env_arn):
        return env_arn

    log_arn = _find_profile_arn_from_kiro_logs()
    if _looks_like_profile_arn(log_arn or "") and _apply_profile_arn(account, log_arn):
        return log_arn

    return None


async def ensure_profile_arn_ready(account) -> Tuple[bool, str]:
    """确保账号具备调用 Kiro API 所需的 profileArn。

    返回:
        (ok, message)
    """
    creds = account.get_credentials()
    if not creds:
        return False, "无法加载账号凭证，请重新登录。"
    
    if getattr(creds, "profile_arn", None):
        return True, ""

    recovered = _try_backfill_profile_arn(account)
    if recovered:
        return True, ""
    
    # 尝试自动刷新，某些认证模式会在刷新时下发 profileArn
    if getattr(creds, "refresh_token", None):
        success, msg = await account.refresh_token()
        if success:
            refreshed = account.get_credentials()
            if refreshed and getattr(refreshed, "profile_arn", None):
                return True, ""
            recovered = _try_backfill_profile_arn(account)
            if recovered:
                return True, ""
            return False, (
                "当前凭证缺少 profileArn，且刷新后仍未获取。"
                "请在 Web UI 重新登录（建议 Google/GitHub），或设置环境变量 KIRO_PROFILE_ARN。"
            )
        return False, f"当前凭证缺少 profileArn，自动刷新失败：{msg}"
    
    return False, "当前凭证缺少 profileArn 且无 refreshToken，请重新登录或设置 KIRO_PROFILE_ARN。"
