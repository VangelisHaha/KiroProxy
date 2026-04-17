#!/usr/bin/env python3
"""Kiro Proxy 协议端点测试（Anthropic/OpenAI/Gemini/Responses）"""

import os
import requests

PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:8080")


def _post(path: str, payload: dict, timeout: int = 30):
    return requests.post(f"{PROXY_URL}{path}", json=payload, timeout=timeout)


def test_status():
    print("1. 服务状态...")
    response = requests.get(f"{PROXY_URL}/api/status", timeout=10)
    response.raise_for_status()
    data = response.json()
    print(f"   ✅ ok={data.get('ok')} available_accounts={data.get('has_available_accounts')}")


def test_anthropic_count_tokens():
    print("\n2. Anthropic count_tokens...")
    payload = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        "system": "test",
    }
    response = _post("/v1/messages/count_tokens", payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    print(f"   ✅ input_tokens={data.get('input_tokens')}")


def test_models():
    print("\n3. 模型列表...")
    response = requests.get(f"{PROXY_URL}/v1/models", timeout=20)
    response.raise_for_status()
    models = response.json().get("data", [])
    print(f"   ✅ models={len(models)}")


def test_openai_chat():
    print("\n4. OpenAI chat/completions...")
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
    }
    response = _post("/v1/chat/completions", payload, timeout=60)
    if response.status_code == 200:
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        print(f"   ✅ 响应成功，内容长度={len(content)}")
    else:
        # 没有可用账号时返回 4xx/5xx 也属于可观察结果
        print(f"   ⚠️ 非 200 响应: {response.status_code} {response.text[:200]}")


def test_responses_endpoint():
    print("\n5. OpenAI /v1/responses...")
    payload = {
        "model": "gpt-4o",
        "stream": False,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Say hello"}],
            }
        ],
    }
    response = _post("/v1/responses", payload, timeout=60)
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ status={data.get('status')} output_items={len(data.get('output', []))}")
    else:
        print(f"   ⚠️ 非 200 响应: {response.status_code} {response.text[:200]}")


if __name__ == "__main__":
    print("=" * 60)
    print(f"Kiro Proxy 协议测试: {PROXY_URL}")
    print("=" * 60)

    try:
        test_status()
        test_anthropic_count_tokens()
        test_models()
        test_openai_chat()
        test_responses_endpoint()
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
    except requests.exceptions.ConnectionError:
        print("\n❌ 连接失败，请先启动服务:")
        print("   ./venv/bin/python run.py serve -p 8080")
    except Exception as exc:
        print(f"\n❌ 测试失败: {exc}")
