"""Kiro Provider"""
import json
import re
import uuid
from typing import Dict, Any, List, Optional, Tuple

from .base import BaseProvider
from ..credential import (
    KiroCredentials, TokenRefresher,
    generate_machine_id, get_kiro_version, get_system_info
)


class KiroProvider(BaseProvider):
    """Kiro/CodeWhisperer Provider"""
    
    API_URL = "https://q.us-east-1.amazonaws.com/generateAssistantResponse"
    MODELS_URL = "https://q.us-east-1.amazonaws.com/ListAvailableModels"
    
    def __init__(self, credentials: Optional[KiroCredentials] = None):
        self.credentials = credentials
        self._machine_id: Optional[str] = None
    
    @property
    def name(self) -> str:
        return "kiro"
    
    @property
    def api_url(self) -> str:
        return self.API_URL
    
    def get_machine_id(self) -> str:
        """获取基于凭证的 Machine ID"""
        if self._machine_id:
            return self._machine_id
        
        if self.credentials:
            self._machine_id = generate_machine_id(
                profile_arn=self.credentials.profile_arn,
                client_id=self.credentials.client_id,
                uuid=getattr(self.credentials, "uuid", None),
            )
        else:
            self._machine_id = generate_machine_id()
        
        return self._machine_id
    
    def build_headers(
        self, 
        token: str, 
        agent_mode: str = "vibe",
        **kwargs
    ) -> Dict[str, str]:
        """构建 Kiro API 请求头"""
        machine_id = kwargs.get("machine_id") or self.get_machine_id()
        kiro_version = get_kiro_version()
        os_name, node_version = get_system_info()
        
        return {
            "content-type": "application/json",
            "x-amzn-codewhisperer-optout": "true",
            "x-amzn-kiro-agent-mode": agent_mode,
            "x-amz-user-agent": f"aws-sdk-js/1.0.0 KiroIDE-{kiro_version}-{machine_id}",
            "user-agent": f"aws-sdk-js/1.0.0 ua/2.1 os/{os_name} lang/js md/nodejs#{node_version} api/codewhispererruntime#1.0.0 m/E KiroIDE-{kiro_version}-{machine_id}",
            "amz-sdk-invocation-id": str(uuid.uuid4()),
            "amz-sdk-request": "attempt=1; max=1",
            "Authorization": f"Bearer {token}",
            "Connection": "close",
        }
    
    def build_request(
        self,
        messages: list = None,
        model: str = "claude-sonnet-4",
        user_content: str = "",
        history: List[dict] = None,
        tools: List[dict] = None,
        images: List[dict] = None,
        tool_results: List[dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """构建 Kiro API 请求体"""
        conversation_id = str(uuid.uuid4())
        history = self._normalize_history(history or [], model)
        clean_tools = [t for t in (tools or []) if isinstance(t, dict)]
        clean_tool_results = self._dedupe_tool_results(tool_results or [])
        clean_images = [img for img in (images or []) if isinstance(img, dict)]
        
        # 确保 content 不为空
        if not user_content:
            user_content = "Continue"
        
        user_input_message = {
            "content": user_content,
            "modelId": model,
            "origin": "AI_EDITOR",
        }
        
        if clean_images:
            user_input_message["images"] = clean_images
        
        # 只有在有 tools 或 tool_results 时才添加 userInputMessageContext
        context = {}
        if clean_tools:
            context["tools"] = clean_tools
        if clean_tool_results:
            context["toolResults"] = clean_tool_results
        
        if context:
            user_input_message["userInputMessageContext"] = context
        
        conversation_state = {
            "agentContinuationId": str(uuid.uuid4()),
            "agentTaskType": "vibe",
            "chatTriggerType": "MANUAL",
            "conversationId": conversation_id,
            "currentMessage": {"userInputMessage": user_input_message},
        }
        if history:
            conversation_state["history"] = history
        
        payload = {
            "conversationState": conversation_state
        }
        
        # 新版 Kiro API 要求 profileArn 位于顶层字段。
        # 同时保留 conversationState 内部字段以兼容旧行为。
        if self.credentials and self.credentials.profile_arn:
            conversation_state["profileArn"] = self.credentials.profile_arn
            payload["profileArn"] = self.credentials.profile_arn
        
        return payload

    @staticmethod
    def _dedupe_tool_results(tool_results: List[dict]) -> List[dict]:
        deduped: List[dict] = []
        seen = set()
        for item in tool_results:
            if not isinstance(item, dict):
                continue
            tool_use_id = item.get("toolUseId")
            if not tool_use_id or tool_use_id in seen:
                continue
            seen.add(tool_use_id)
            deduped.append(item)
        return deduped

    @staticmethod
    def _normalize_history(history: List[dict], model: str) -> List[dict]:
        """兜底修正 history，避免上游因结构异常拒绝请求。"""
        fixed: List[dict] = []
        for msg in history:
            if not isinstance(msg, dict):
                continue
            if "userInputMessage" in msg and isinstance(msg["userInputMessage"], dict):
                user_msg = dict(msg["userInputMessage"])
                if not user_msg.get("content"):
                    user_msg["content"] = "Continue"
                user_msg.setdefault("modelId", model)
                user_msg.setdefault("origin", "AI_EDITOR")
                normalized = {"userInputMessage": user_msg}
            elif "assistantResponseMessage" in msg and isinstance(msg["assistantResponseMessage"], dict):
                assistant_msg = dict(msg["assistantResponseMessage"])
                if not assistant_msg.get("content"):
                    assistant_msg["content"] = "I understand."
                normalized = {"assistantResponseMessage": assistant_msg}
            else:
                continue

            # 合并连续同角色消息，降低 Kiro 拒绝概率。
            if fixed:
                last = fixed[-1]
                if "userInputMessage" in last and "userInputMessage" in normalized:
                    prev = last["userInputMessage"]
                    cur = normalized["userInputMessage"]
                    prev["content"] = f"{prev.get('content', '')}\n{cur.get('content', '')}".strip() or "Continue"
                    cur_ctx = cur.get("userInputMessageContext", {})
                    if isinstance(cur_ctx, dict) and cur_ctx.get("toolResults"):
                        prev_ctx = prev.setdefault("userInputMessageContext", {})
                        prev_ctx.setdefault("toolResults", [])
                        prev_ctx["toolResults"].extend(cur_ctx["toolResults"])
                    continue
                if "assistantResponseMessage" in last and "assistantResponseMessage" in normalized:
                    prev = last["assistantResponseMessage"]
                    cur = normalized["assistantResponseMessage"]
                    prev["content"] = f"{prev.get('content', '')}\n{cur.get('content', '')}".strip() or "I understand."
                    if cur.get("toolUses"):
                        prev.setdefault("toolUses", [])
                        prev["toolUses"].extend(cur.get("toolUses") or [])
                    continue

            fixed.append(normalized)
        return fixed

    @staticmethod
    def _iter_json_objects_from_text(raw_text: str):
        decoder = json.JSONDecoder()
        idx = 0
        n = len(raw_text)
        while idx < n:
            start = raw_text.find("{", idx)
            if start < 0:
                break
            try:
                obj, end = decoder.raw_decode(raw_text, start)
                yield obj
                idx = end
            except Exception:
                idx = start + 1
    
    def parse_response(self, raw: bytes) -> Dict[str, Any]:
        """解析 AWS event-stream 格式响应"""
        result = {
            "content": [],
            "tool_uses": [],
            "stop_reason": "end_turn"
        }
        
        tool_input_buffer = {}
        pos = 0
        
        while pos < len(raw):
            if pos + 12 > len(raw):
                break
            
            total_len = int.from_bytes(raw[pos:pos+4], 'big')
            headers_len = int.from_bytes(raw[pos+4:pos+8], 'big')
            
            if total_len == 0 or total_len > len(raw) - pos:
                break
            
            header_start = pos + 12
            header_end = header_start + headers_len
            headers_data = raw[header_start:header_end]
            event_type = None
            
            try:
                headers_str = headers_data.decode('utf-8', errors='ignore')
                if 'toolUseEvent' in headers_str:
                    event_type = 'toolUseEvent'
                elif 'assistantResponseEvent' in headers_str:
                    event_type = 'assistantResponseEvent'
            except:
                pass
            
            payload_start = pos + 12 + headers_len
            payload_end = pos + total_len - 4
            
            if payload_start < payload_end:
                try:
                    payload = json.loads(raw[payload_start:payload_end].decode('utf-8'))
                    
                    if 'assistantResponseEvent' in payload:
                        e = payload['assistantResponseEvent']
                        if 'content' in e:
                            result["content"].append(e['content'])
                    elif 'content' in payload and event_type != 'toolUseEvent':
                        result["content"].append(payload['content'])
                    
                    if event_type == 'toolUseEvent' or 'toolUseId' in payload:
                        tool_id = payload.get('toolUseId', '')
                        tool_name = payload.get('name', '')
                        tool_input = payload.get('input', '')
                        
                        if tool_id:
                            if tool_id not in tool_input_buffer:
                                tool_input_buffer[tool_id] = {
                                    "id": tool_id,
                                    "name": tool_name,
                                    "input_parts": []
                                }
                            if tool_name and not tool_input_buffer[tool_id]["name"]:
                                tool_input_buffer[tool_id]["name"] = tool_name
                            if tool_input:
                                tool_input_buffer[tool_id]["input_parts"].append(tool_input)
                except:
                    pass
            
            pos += total_len

        # 某些代理链路会破坏 AWS event-stream 头；回退为文本 JSON 扫描。
        if not result["content"] and not tool_input_buffer:
            raw_text = raw.decode("utf-8", errors="ignore")
            for payload in self._iter_json_objects_from_text(raw_text):
                if not isinstance(payload, dict):
                    continue
                if "assistantResponseEvent" in payload and isinstance(payload["assistantResponseEvent"], dict):
                    content = payload["assistantResponseEvent"].get("content")
                    if content:
                        result["content"].append(str(content))
                elif "content" in payload and not payload.get("toolUseId"):
                    content = payload.get("content")
                    if content:
                        result["content"].append(str(content))

                if payload.get("toolUseId"):
                    tool_id = payload.get("toolUseId", "")
                    if not tool_id:
                        continue
                    if tool_id not in tool_input_buffer:
                        tool_input_buffer[tool_id] = {"id": tool_id, "name": "", "input_parts": []}
                    if payload.get("name"):
                        tool_input_buffer[tool_id]["name"] = payload["name"]
                    if payload.get("input"):
                        tool_input_buffer[tool_id]["input_parts"].append(str(payload["input"]))
        
        # 组装工具调用
        for tool_id, tool_data in tool_input_buffer.items():
            input_str = "".join(tool_data["input_parts"])
            try:
                input_json = json.loads(input_str)
            except:
                input_json = {"raw": input_str}
            
            result["tool_uses"].append({
                "type": "tool_use",
                "id": tool_data["id"],
                "name": tool_data["name"],
                "input": input_json
            })
        
        if result["tool_uses"]:
            result["stop_reason"] = "tool_use"
        elif result["content"]:
            text = "".join(result["content"])
            if re.search(r"\bmax[_-]?tokens\b", text, flags=re.IGNORECASE):
                result["stop_reason"] = "max_tokens"
        
        return result
    
    def parse_response_text(self, raw: bytes) -> str:
        """解析响应，只返回文本内容"""
        result = self.parse_response(raw)
        return "".join(result["content"]) or "[No response]"
    
    async def refresh_token(self) -> Tuple[bool, str]:
        """刷新 token"""
        if not self.credentials:
            return False, "无凭证信息"
        
        refresher = TokenRefresher(self.credentials)
        return await refresher.refresh()
    
    def is_quota_exceeded(self, status_code: int, error_text: str) -> bool:
        """检查是否为配额超限错误"""
        if status_code in {429, 503, 529}:
            return True
        
        keywords = ["rate limit", "quota", "too many requests", "throttl"]
        error_lower = error_text.lower()
        return any(kw in error_lower for kw in keywords)
