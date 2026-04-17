#!/usr/bin/env python3
"""Kiro Proxy 快速冒烟测试（当前版本接口）"""

import os
import requests

PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:8080")


def _get_json(path: str, timeout: int = 10):
    response = requests.get(f"{PROXY_URL}{path}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def test_root():
    print("1. 检查 Web UI 首页...")
    response = requests.get(f"{PROXY_URL}/", timeout=10)
    response.raise_for_status()
    print(f"   ✅ status={response.status_code}, content-type={response.headers.get('content-type', '')}")


def test_status():
    print("\n2. 检查服务状态...")
    data = _get_json("/api/status")
    print(f"   ✅ ok={data.get('ok')}, has_accounts={data.get('has_accounts')}, port={data.get('port')}")


def test_accounts():
    print("\n3. 检查账号列表...")
    data = _get_json("/api/accounts")
    accounts = data.get("accounts", [])
    print(f"   ✅ 账号数量: {len(accounts)}")


def test_models():
    print("\n4. 检查模型列表接口...")
    data = _get_json("/v1/models", timeout=20)
    models = data.get("data", [])
    print(f"   ✅ 返回模型数: {len(models)}")
    if models:
        print(f"   - 示例模型: {models[0].get('id')}")


def test_logs():
    print("\n5. 检查日志接口...")
    data = _get_json("/api/logs?limit=5")
    print(f"   ✅ recent_logs={len(data.get('logs', []))}, total={data.get('total')}")


if __name__ == "__main__":
    print("=" * 50)
    print(f"Kiro Proxy 冒烟测试: {PROXY_URL}")
    print("=" * 50)

    try:
        test_root()
        test_status()
        test_accounts()
        test_models()
        test_logs()
        print("\n" + "=" * 50)
        print("✅ 冒烟测试完成")
        print("=" * 50)
    except requests.exceptions.ConnectionError:
        print("\n❌ 连接失败，请先启动服务:")
        print("   python run.py serve -p 8080")
    except Exception as exc:
        print(f"\n❌ 测试失败: {exc}")
