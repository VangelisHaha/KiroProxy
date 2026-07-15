"""协议转换模块 - Anthropic/OpenAI/Gemini <-> Kiro

增强版：参考 proxycast 实现
- 完整保留客户端提供的工具定义
- 工具描述截断（提升至 9216 字符，兼容 Claude Code/Codex 长描述）
- 历史消息交替修复
- OpenAI tool 角色消息处理
- tool_choice: required 支持
- web_search 特殊工具支持
- tool_results 去重
"""
import json
import hashlib
import re
from collections import deque
from typing import List, Dict, Any, Tuple, Optional

# 常量
MAX_TOOL_DESCRIPTION_LENGTH = 9216
THINKING_MIN_BUDGET = 1024
THINKING_MAX_BUDGET = 24576
THINKING_DEFAULT_BUDGET = 20000


def generate_session_id(messages: list) -> str:
    """基于消息内容生成会话ID"""
    content = json.dumps(messages[:3], sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def extract_images_from_content(content) -> Tuple[str, List[dict]]:
    """从消息内容中提取文本和图片
    
    Returns:
        (text_content, images_list)
    """
    if isinstance(content, str):
        return content, []
    
    if not isinstance(content, list):
        return str(content) if content else "", []
    
    text_parts = []
    images = []
    
    for block in content:
        if isinstance(block, str):
            text_parts.append(block)
        elif isinstance(block, dict):
            block_type = block.get("type", "")
            
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            
            elif block_type == "image":
                # Anthropic 格式
                source = block.get("source", {})
                media_type = source.get("media_type", "image/jpeg")
                data = source.get("data", "")
                
                fmt = "jpeg"
                if "png" in media_type:
                    fmt = "png"
                elif "gif" in media_type:
                    fmt = "gif"
                elif "webp" in media_type:
                    fmt = "webp"
                
                if data:
                    images.append({
                        "format": fmt,
                        "source": {"bytes": data}
                    })
            
            elif block_type == "image_url":
                # OpenAI 格式
                image_url = block.get("image_url", {})
                url = image_url.get("url", "")
                
                if url.startswith("data:"):
                    match = re.match(r'data:image/(\w+);base64,(.+)', url)
                    if match:
                        fmt = match.group(1)
                        data = match.group(2)
                        images.append({
                            "format": fmt,
                            "source": {"bytes": data}
                        })
    
    return "\n".join(text_parts), images


def truncate_description(desc: str, max_length: int = MAX_TOOL_DESCRIPTION_LENGTH) -> str:
    """截断工具描述"""
    if len(desc) <= max_length:
        return desc
    return desc[:max_length - 3] + "..."


def _normalize_thinking_budget(budget_tokens: Any) -> int:
    value = THINKING_DEFAULT_BUDGET
    try:
        parsed = int(budget_tokens)
        if parsed > 0:
            value = parsed
    except Exception:
        pass
    if value < THINKING_MIN_BUDGET:
        return THINKING_MIN_BUDGET
    if value > THINKING_MAX_BUDGET:
        return THINKING_MAX_BUDGET
    return value


def build_thinking_prefix(thinking: Any) -> str:
    """将 thinking 配置映射为 Kiro 可识别前缀。"""
    if not isinstance(thinking, dict):
        return ""

    thinking_type = str(thinking.get("type", "")).strip().lower()
    if thinking_type == "enabled":
        budget = _normalize_thinking_budget(thinking.get("budget_tokens"))
        return f"<thinking_mode>enabled</thinking_mode><max_thinking_length>{budget}</max_thinking_length>"

    if thinking_type == "adaptive":
        effort = str(thinking.get("effort", "high")).strip().lower()
        if effort not in {"low", "medium", "high"}:
            effort = "high"
        return f"<thinking_mode>adaptive</thinking_mode><thinking_effort>{effort}</thinking_effort>"

    return ""


def inject_thinking_prefix(system_text: str, thinking: Any) -> str:
    """把 thinking 前缀注入 system 文本（避免重复注入）。"""
    prefix = build_thinking_prefix(thinking)
    if not prefix:
        return system_text

    if "<thinking_mode>" in system_text:
        return system_text

    if system_text:
        return f"{prefix}\n{system_text}"
    return prefix


# ==================== Anthropic 转换 ====================

def convert_anthropic_tools_to_kiro(tools: List[dict]) -> List[dict]:
    """将 Anthropic 工具格式转换为 Kiro 格式
    
    增强：
    - 完整保留工具定义
    - 截断过长的描述
    - 支持 web_search 特殊工具
    """
    kiro_tools = []
    for tool in tools:
        name = tool.get("name", "")
        
        # 特殊工具：web_search
        if name in ("web_search", "web_search_20250305"):
            kiro_tools.append({
                "webSearchTool": {
                    "type": "web_search"
                }
            })
            continue
        
        description = tool.get("description", f"Tool: {name}")
        description = truncate_description(description)
        
        input_schema = tool.get("input_schema", {"type": "object", "properties": {}})
        
        kiro_tools.append({
            "toolSpecification": {
                "name": name,
                "description": description,
                "inputSchema": {
                    "json": input_schema
                }
            }
        })
    
    return kiro_tools


def fix_history_alternation(history: List[dict], model_id: str = "claude-sonnet-4") -> List[dict]:
    """修复历史记录，确保 user/assistant 严格交替，并验证 toolUses/toolResults 配对
    
    Kiro API 规则：
    1. 消息必须严格交替：user -> assistant -> user -> assistant
    2. 当 assistant 有 toolUses 时，下一条 user 必须有对应的 toolResults
    3. 当 assistant 没有 toolUses 时，下一条 user 不能有 toolResults
    """
    if not history:
        return history
    
    # 深拷贝以避免修改原始数据
    import copy
    history = copy.deepcopy(history)
    
    fixed = []
    
    for i, item in enumerate(history):
        is_user = "userInputMessage" in item
        is_assistant = "assistantResponseMessage" in item
        
        if is_user:
            # 检查上一条是否也是 user
            if fixed and "userInputMessage" in fixed[-1]:
                # 检查当前消息是否有 tool_results
                user_msg = item["userInputMessage"]
                ctx = user_msg.get("userInputMessageContext", {})
                has_tool_results = bool(ctx.get("toolResults"))
                
                if has_tool_results:
                    # 合并 tool_results 到上一条 user 消息
                    new_results = ctx["toolResults"]
                    last_user = fixed[-1]["userInputMessage"]
                    
                    if "userInputMessageContext" not in last_user:
                        last_user["userInputMessageContext"] = {}
                    
                    last_ctx = last_user["userInputMessageContext"]
                    if "toolResults" in last_ctx and last_ctx["toolResults"]:
                        last_ctx["toolResults"].extend(new_results)
                    else:
                        last_ctx["toolResults"] = new_results
                    continue
                else:
                    # 插入一个占位 assistant 消息（不带 toolUses）
                    fixed.append({
                        "assistantResponseMessage": {
                            "content": "I understand."
                        }
                    })
            
            # 验证 toolResults 与前一个 assistant 的 toolUses 配对
            if fixed and "assistantResponseMessage" in fixed[-1]:
                last_assistant = fixed[-1]["assistantResponseMessage"]
                has_tool_uses = bool(last_assistant.get("toolUses"))
                
                user_msg = item["userInputMessage"]
                ctx = user_msg.get("userInputMessageContext", {})
                has_tool_results = bool(ctx.get("toolResults"))
                
                if has_tool_uses and not has_tool_results:
                    # assistant 有 toolUses 但 user 没有 toolResults
                    # 这是不允许的，需要清除 assistant 的 toolUses
                    last_assistant.pop("toolUses", None)
                elif not has_tool_uses and has_tool_results:
                    # assistant 没有 toolUses 但 user 有 toolResults
                    # 这是不允许的，需要清除 user 的 toolResults
                    item["userInputMessage"].pop("userInputMessageContext", None)
            
            fixed.append(item)
        
        elif is_assistant:
            # 检查上一条是否也是 assistant
            if fixed and "assistantResponseMessage" in fixed[-1]:
                # 插入一个占位 user 消息（不带 toolResults）
                fixed.append({
                    "userInputMessage": {
                        "content": "Continue",
                        "modelId": model_id,
                        "origin": "AI_EDITOR"
                    }
                })
            
            # 如果历史为空，先插入一个 user 消息
            if not fixed:
                fixed.append({
                    "userInputMessage": {
                        "content": "Continue",
                        "modelId": model_id,
                        "origin": "AI_EDITOR"
                    }
                })
            
            fixed.append(item)
    
    # 确保以 assistant 结尾（如果最后是 user，添加占位 assistant）
    if fixed and "userInputMessage" in fixed[-1]:
        # 不需要清除 toolResults，因为它是与前一个 assistant 的 toolUses 配对的
        # 占位 assistant 只是为了满足交替规则
        fixed.append({
            "assistantResponseMessage": {
                "content": "I understand."
            }
        })
    
    return fixed


def convert_anthropic_messages_to_kiro(
    messages: List[dict],
    system="",
    thinking: Optional[dict] = None,
) -> Tuple[str, List[dict], List[dict]]:
    """将 Anthropic 消息格式转换为 Kiro 格式
    
    Returns:
        (user_content, history, tool_results)
    """
    history = []
    user_content = ""
    current_tool_results = []
    
    # 处理 system
    system_text = ""
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                system_text += block.get("text", "") + "\n"
            elif isinstance(block, str):
                system_text += block + "\n"
        system_text = system_text.strip()
    elif isinstance(system, str):
        system_text = system
    system_text = inject_thinking_prefix(system_text, thinking)
    
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        is_last = (i == len(messages) - 1)
        
        # 处理 content 列表
        tool_results = []
        text_parts = []
        
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        tr_content = block.get("content", "")
                        if isinstance(tr_content, list):
                            tr_text_parts = []
                            for tc in tr_content:
                                if isinstance(tc, dict) and tc.get("type") == "text":
                                    tr_text_parts.append(tc.get("text", ""))
                                elif isinstance(tc, str):
                                    tr_text_parts.append(tc)
                            tr_content = "\n".join(tr_text_parts)
                        
                        # 处理 is_error
                        status = "error" if block.get("is_error") else "success"
                        
                        tool_results.append({
                            "content": [{"text": str(tr_content)}],
                            "status": status,
                            "toolUseId": block.get("tool_use_id", "")
                        })
                elif isinstance(block, str):
                    text_parts.append(block)
            
            content = "\n".join(text_parts) if text_parts else ""
        
        # 处理工具结果
        if tool_results:
            # 去重
            seen_ids = set()
            unique_results = []
            for tr in tool_results:
                if tr["toolUseId"] not in seen_ids:
                    seen_ids.add(tr["toolUseId"])
                    unique_results.append(tr)
            tool_results = unique_results
            
            if is_last:
                current_tool_results = tool_results
                user_content = content if content else "Tool results provided."
            else:
                history.append({
                    "userInputMessage": {
                        "content": content if content else "Tool results provided.",
                        "modelId": "claude-sonnet-4",
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {
                            "toolResults": tool_results
                        }
                    }
                })
            continue
        
        if role == "user":
            if system_text and not history:
                content_str = content if isinstance(content, str) else str(content or "")
                # Claude Code 请求里可能把关键计费/路由头放在消息开头，
                # 必须保留首行顺序，避免上游识别变化。
                if content_str.lstrip().startswith("x-anthropic-billing-header:"):
                    content = content_str
                else:
                    content = f"{system_text}\n\n{content_str}" if content_str else system_text
            
            if is_last:
                user_content = content if content else "Continue"
            else:
                history.append({
                    "userInputMessage": {
                        "content": content if content else "Continue",
                        "modelId": "claude-sonnet-4",
                        "origin": "AI_EDITOR"
                    }
                })
        
        elif role == "assistant":
            tool_uses = []
            assistant_text = ""
            
            if isinstance(msg.get("content"), list):
                text_parts = []
                for block in msg["content"]:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_uses.append({
                                "toolUseId": block.get("id", ""),
                                "name": block.get("name", ""),
                                "input": block.get("input", {})
                            })
                        elif block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                assistant_text = "\n".join(text_parts)
            else:
                assistant_text = content if isinstance(content, str) else ""
            
            # 确保 assistant 消息有内容
            if not assistant_text:
                assistant_text = "I understand."
            
            assistant_msg = {
                "assistantResponseMessage": {
                    "content": assistant_text
                }
            }
            # 只有在有 toolUses 时才添加这个字段
            if tool_uses:
                assistant_msg["assistantResponseMessage"]["toolUses"] = tool_uses
            
            history.append(assistant_msg)
    
    # 修复历史交替
    history = fix_history_alternation(history)
    
    return user_content, history, current_tool_results


def convert_kiro_response_to_anthropic(result: dict, model: str, msg_id: str) -> dict:
    """将 Kiro 响应转换为 Anthropic 格式"""
    content = []
    text = "".join(result["content"])
    if text:
        content.append({"type": "text", "text": text})
    
    for tool_use in result["tool_uses"]:
        content.append(tool_use)
    
    return {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": model,
        "stop_reason": result["stop_reason"],
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 100}
    }


# ==================== OpenAI 转换 ====================

def is_tool_choice_required(tool_choice) -> bool:
    """检查 tool_choice 是否为 required"""
    if isinstance(tool_choice, dict):
        t = tool_choice.get("type", "")
        return t in ("any", "tool", "required")
    elif isinstance(tool_choice, str):
        return tool_choice in ("required", "any")
    return False


def convert_openai_tools_to_kiro(tools: List[dict]) -> List[dict]:
    """将 OpenAI 工具格式转换为 Kiro 格式"""
    kiro_tools = []
    
    for tool in tools:
        tool_type = tool.get("type", "function")
        
        # 特殊工具
        if tool_type == "web_search":
            kiro_tools.append({
                "webSearchTool": {
                    "type": "web_search"
                }
            })
            continue
        
        if tool_type != "function":
            continue
        
        func = tool.get("function", {})
        name = func.get("name", "")
        description = func.get("description", f"Tool: {name}")
        description = truncate_description(description)
        parameters = func.get("parameters", {"type": "object", "properties": {}})
        
        kiro_tools.append({
            "toolSpecification": {
                "name": name,
                "description": description,
                "inputSchema": {
                    "json": parameters
                }
            }
        })
    
    return kiro_tools


def convert_openai_messages_to_kiro(
    messages: List[dict], 
    model: str,
    tools: List[dict] = None,
    tool_choice = None,
    thinking: Optional[dict] = None,
) -> Tuple[str, List[dict], List[dict], List[dict]]:
    """将 OpenAI 消息格式转换为 Kiro 格式
    
    增强：
    - 支持 tool 角色消息
    - 支持 assistant 的 tool_calls
    - 支持 tool_choice: required
    - 历史交替修复
    
    Returns:
        (user_content, history, tool_results, kiro_tools)
    """
    system_content = ""
    history = []
    user_content = ""
    current_tool_results = []
    pending_tool_results = []  # 待处理的 tool 消息
    
    # 处理 tool_choice: required
    tool_instruction = ""
    if is_tool_choice_required(tool_choice) and tools:
        tool_instruction = "\n\n[CRITICAL INSTRUCTION] You MUST use one of the provided tools to respond. Do NOT respond with plain text. Call a tool function immediately."
    thinking_prefix = build_thinking_prefix(thinking)
    
    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        is_last = (i == len(messages) - 1)
        
        # 提取文本内容
        if isinstance(content, list):
            content = " ".join([c.get("text", "") for c in content if c.get("type") == "text"])
        if not content:
            content = ""
        
        if role == "system":
            system_content = content + tool_instruction
            if thinking_prefix:
                system_content = f"{thinking_prefix}\n{system_content}" if system_content else thinking_prefix
        
        elif role == "tool":
            # OpenAI tool 角色消息 -> Kiro toolResults
            tool_call_id = msg.get("tool_call_id", "")
            pending_tool_results.append({
                "content": [{"text": str(content)}],
                "status": "success",
                "toolUseId": tool_call_id
            })
        
        elif role == "user":
            # 如果有待处理的 tool results，先处理
            if pending_tool_results:
                # 去重
                seen_ids = set()
                unique_results = []
                for tr in pending_tool_results:
                    if tr["toolUseId"] not in seen_ids:
                        seen_ids.add(tr["toolUseId"])
                        unique_results.append(tr)
                
                if is_last:
                    current_tool_results = unique_results
                else:
                    history.append({
                        "userInputMessage": {
                            "content": "Tool results provided.",
                            "modelId": model,
                            "origin": "AI_EDITOR",
                            "userInputMessageContext": {
                                "toolResults": unique_results
                            }
                        }
                    })
                pending_tool_results = []
            
            # 合并 system prompt
            if system_content and not history:
                content = f"{system_content}\n\n{content}"
            
            if is_last:
                user_content = content
            else:
                history.append({
                    "userInputMessage": {
                        "content": content,
                        "modelId": model,
                        "origin": "AI_EDITOR"
                    }
                })
        
        elif role == "assistant":
            # 如果有待处理的 tool results，先创建 user 消息
            if pending_tool_results:
                seen_ids = set()
                unique_results = []
                for tr in pending_tool_results:
                    if tr["toolUseId"] not in seen_ids:
                        seen_ids.add(tr["toolUseId"])
                        unique_results.append(tr)
                
                history.append({
                    "userInputMessage": {
                        "content": "Tool results provided.",
                        "modelId": model,
                        "origin": "AI_EDITOR",
                        "userInputMessageContext": {
                            "toolResults": unique_results
                        }
                    }
                })
                pending_tool_results = []
            
            # 处理 tool_calls
            tool_uses = []
            tool_calls = msg.get("tool_calls", [])
            for tc in tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str)
                except:
                    args = {}
                
                tool_uses.append({
                    "toolUseId": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "input": args
                })
            
            assistant_text = content if content else "I understand."
            
            assistant_msg = {
                "assistantResponseMessage": {
                    "content": assistant_text
                }
            }
            # 只有在有 toolUses 时才添加这个字段
            if tool_uses:
                assistant_msg["assistantResponseMessage"]["toolUses"] = tool_uses
            
            history.append(assistant_msg)
    
    # 处理末尾的 tool results
    if pending_tool_results:
        seen_ids = set()
        unique_results = []
        for tr in pending_tool_results:
            if tr["toolUseId"] not in seen_ids:
                seen_ids.add(tr["toolUseId"])
                unique_results.append(tr)
        current_tool_results = unique_results
        if not user_content:
            user_content = "Tool results provided."
    
    # 如果没有用户消息
    if not user_content:
        user_content = messages[-1].get("content", "") if messages else "Continue"
        if isinstance(user_content, list):
            user_content = " ".join([c.get("text", "") for c in user_content if c.get("type") == "text"])
        if not user_content:
            user_content = "Continue"
    
    # 历史不包含最后一条用户消息
    if history and "userInputMessage" in history[-1]:
        history = history[:-1]
    
    # 修复历史交替
    history = fix_history_alternation(history, model)
    
    # 转换工具
    kiro_tools = convert_openai_tools_to_kiro(tools) if tools else []
    
    return user_content, history, current_tool_results, kiro_tools


def convert_kiro_response_to_openai(result: dict, model: str, msg_id: str) -> dict:
    """将 Kiro 响应转换为 OpenAI 格式"""
    text = "".join(result["content"])
    tool_calls = []
    
    for tool_use in result.get("tool_uses", []):
        if tool_use.get("type") == "tool_use":
            tool_calls.append({
                "id": tool_use.get("id", ""),
                "type": "function",
                "function": {
                    "name": tool_use.get("name", ""),
                    "arguments": json.dumps(tool_use.get("input", {}))
                }
            })
    
    # 映射 stop_reason
    stop_reason = result.get("stop_reason", "stop")
    finish_reason = "tool_calls" if tool_calls else "stop"
    if stop_reason == "max_tokens":
        finish_reason = "length"
    
    message = {
        "role": "assistant",
        "content": text if text else None
    }
    if tool_calls:
        message["tool_calls"] = tool_calls

    prompt_tokens = int(result.get("input_tokens", 0) or 0)
    completion_tokens = int(result.get("output_tokens", 0) or 0)

    return {
        "id": msg_id,
        "object": "chat.completion",
        "model": model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    }


# ==================== Gemini 转换 ====================

def convert_gemini_tools_to_kiro(tools: List[dict]) -> List[dict]:
    """将 Gemini 工具格式转换为 Kiro 格式
    
    Gemini 工具格式：
    {
        "functionDeclarations": [
            {
                "name": "get_weather",
                "description": "Get weather info",
                "parameters": {...}
            }
        ]
    }
    """
    kiro_tools = []
    
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        
        # Gemini 原生联网工具（统一映射为 Kiro web_search）
        if any(k in tool for k in ("googleSearch", "googleSearchRetrieval", "webSearch", "urlContext")):
            kiro_tools.append({"webSearchTool": {"type": "web_search"}})
            continue
        
        # Gemini 工具定义可能是 camelCase 或 snake_case
        declarations = (
            tool.get("functionDeclarations")
            or tool.get("function_declarations")
            or []
        )
        
        for func in declarations:
            if not isinstance(func, dict):
                continue
            
            name = func.get("name", "")
            if not name:
                continue

            description = func.get("description", f"Tool: {name}")
            description = truncate_description(description)
            parameters = func.get("parameters", {"type": "object", "properties": {}})
            
            kiro_tools.append({
                "toolSpecification": {
                    "name": name,
                    "description": description,
                    "inputSchema": {
                        "json": parameters
                    }
                }
            })
    
    return kiro_tools


def _convert_gemini_inline_image_to_kiro(part: dict) -> Optional[dict]:
    """将 Gemini inlineData 图片转换为 Kiro 图片格式"""
    inline_data = part.get("inlineData")
    if not isinstance(inline_data, dict):
        return None
    
    mime_type = str(inline_data.get("mimeType", "")).lower()
    data = inline_data.get("data")
    
    if not (isinstance(data, str) and data):
        return None
    if not mime_type.startswith("image/"):
        return None
    
    image_format = mime_type.split("/", 1)[1].split(";", 1)[0] or "jpeg"
    return {
        "format": image_format,
        "source": {"bytes": data},
    }


def _gemini_inline_data_note(inline_data: dict) -> str:
    """将 Gemini inlineData 转换为可读描述（用于工具结果文本化）"""
    mime_type = inline_data.get("mimeType", "application/octet-stream")
    return f"[Inline data: ({mime_type})]"


def _gemini_file_data_note(file_data: dict) -> str:
    """将 Gemini fileData 转换为可读描述（用于文本化）"""
    file_uri = file_data.get("fileUri")
    mime_type = file_data.get("mimeType", "application/octet-stream")
    if file_uri:
        return f"[Attached file: {file_uri} ({mime_type})]"
    return f"[Attached file: ({mime_type})]"


def _dedupe_text_lines(lines: List[str]) -> List[str]:
    """按出现顺序去重文本行"""
    seen = set()
    unique = []
    for line in lines:
        if not isinstance(line, str):
            continue
        if not line.strip():
            continue
        dedupe_key = line.strip()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        unique.append(line)
    return unique


def _extract_text_from_gemini_payload(payload: Any, depth: int = 0) -> List[str]:
    """尽量从 Gemini payload 中提取文本信息，包含多模态描述"""
    if depth > 5:
        return []
    
    if payload is None:
        return []
    if isinstance(payload, str):
        return [payload] if payload else []
    if isinstance(payload, (int, float, bool)):
        return [json.dumps(payload, ensure_ascii=False)]
    if isinstance(payload, list):
        lines = []
        for item in payload:
            lines.extend(_extract_text_from_gemini_payload(item, depth + 1))
        return lines
    if isinstance(payload, dict):
        lines = []
        
        text = payload.get("text")
        if isinstance(text, str) and text:
            lines.append(text)
        
        inline_data = payload.get("inlineData") or payload.get("inline_data")
        if isinstance(inline_data, dict):
            lines.append(_gemini_inline_data_note(inline_data))
        
        file_data = payload.get("fileData") or payload.get("file_data")
        if isinstance(file_data, dict):
            lines.append(_gemini_file_data_note(file_data))
        
        # 常见结构字段（函数输出/工具响应/多模态嵌套）
        for key in ("output", "content", "parts", "data", "message", "result", "error"):
            if key in payload:
                lines.extend(_extract_text_from_gemini_payload(payload.get(key), depth + 1))
        
        if lines:
            return lines
        
        try:
            return [json.dumps(payload, ensure_ascii=False)]
        except Exception:
            return [str(payload)]
    
    return [str(payload)]


def _extract_gemini_function_response(fr: dict) -> Tuple[str, str]:
    """提取 Gemini functionResponse 的文本和状态"""
    response = fr.get("response")
    status = "success"
    
    if fr.get("isError") is True or fr.get("is_error") is True or fr.get("error"):
        status = "error"
    
    if isinstance(response, dict):
        if (
            response.get("success") is False
            or response.get("isError") is True
            or response.get("is_error") is True
            or response.get("error")
        ):
            status = "error"
    
    text_lines = _extract_text_from_gemini_payload(response)
    if "parts" in fr:
        text_lines.extend(_extract_text_from_gemini_payload(fr.get("parts")))
    
    output_text = "\n".join(_dedupe_text_lines(text_lines))
    if not output_text:
        output_text = "Tool execution completed."
    
    return output_text, status


def _dedupe_tool_results(results: List[dict]) -> List[dict]:
    """按 toolUseId 去重并合并内容"""
    merged: Dict[str, dict] = {}
    ordered: List[dict] = []
    
    for tr in results:
        tool_use_id = tr.get("toolUseId")
        if not tool_use_id:
            continue
        
        new_text = ""
        content = tr.get("content", [])
        if isinstance(content, list) and content and isinstance(content[0], dict):
            new_text = str(content[0].get("text", ""))
        
        new_status = "error" if tr.get("status") == "error" else "success"
        
        if tool_use_id not in merged:
            normalized = {
                "content": [{"text": new_text if new_text else "Tool execution completed."}],
                "status": new_status,
                "toolUseId": tool_use_id
            }
            merged[tool_use_id] = normalized
            ordered.append(normalized)
            continue
        
        existing = merged[tool_use_id]
        existing_text = ""
        existing_content = existing.get("content", [])
        if isinstance(existing_content, list) and existing_content and isinstance(existing_content[0], dict):
            existing_text = str(existing_content[0].get("text", ""))
        
        if new_text:
            merged_lines = _dedupe_text_lines([existing_text, new_text])
            existing["content"] = [{"text": "\n".join(merged_lines)}]
        
        if new_status == "error":
            existing["status"] = "error"
    
    return ordered


def convert_gemini_contents_to_kiro(
    contents: List[dict], 
    system_instruction: dict, 
    model: str,
    tools: List[dict] = None,
    tool_config: dict = None,
    thinking_config: Optional[dict] = None,
) -> Tuple[str, List[dict], List[dict], List[dict], List[dict]]:
    """将 Gemini 消息格式转换为 Kiro 格式
    
    增强：
    - 支持 functionCall 和 functionResponse
    - 支持 tool_config
    
    Returns:
        (user_content, history, tool_results, kiro_tools, images)
    """
    history = []
    user_content = ""
    current_tool_results = []
    current_images = []
    pending_call_ids = deque()
    pending_call_ids_by_name: Dict[str, deque] = {}
    consumed_call_ids = set()
    
    def remember_call_id(call_name: str, call_id: str):
        pending_call_ids.append(call_id)
        if call_name:
            pending_call_ids_by_name.setdefault(call_name, deque()).append(call_id)
    
    def consume_call_id(call_name: str, explicit_id: str = "") -> Optional[str]:
        if explicit_id:
            consumed_call_ids.add(explicit_id)
            return explicit_id
        
        if call_name:
            queue = pending_call_ids_by_name.get(call_name)
            if queue:
                while queue and queue[0] in consumed_call_ids:
                    queue.popleft()
                if queue:
                    call_id = queue.popleft()
                    consumed_call_ids.add(call_id)
                    return call_id
        
        while pending_call_ids and pending_call_ids[0] in consumed_call_ids:
            pending_call_ids.popleft()
        if pending_call_ids:
            call_id = pending_call_ids.popleft()
            consumed_call_ids.add(call_id)
            return call_id
        return None
    
    # 处理 system instruction
    system_text = ""
    if system_instruction:
        if isinstance(system_instruction, str):
            system_text = system_instruction
        elif isinstance(system_instruction, dict):
            parts = system_instruction.get("parts", [])
            if isinstance(parts, list):
                system_text = " ".join(
                    p.get("text", "") for p in parts
                    if isinstance(p, dict) and isinstance(p.get("text"), str)
                )
    normalized_thinking = thinking_config if isinstance(thinking_config, dict) else None
    if normalized_thinking and "type" not in normalized_thinking:
        if normalized_thinking.get("includeThoughts") is True or normalized_thinking.get("thinkingBudget") is not None:
            normalized_thinking = {
                "type": "enabled",
                "budget_tokens": normalized_thinking.get("thinkingBudget"),
            }
        else:
            normalized_thinking = None
    system_text = inject_thinking_prefix(system_text, normalized_thinking)
    
    # 处理 tool_config（类似 tool_choice）
    tool_instruction = ""
    function_calling_config = {}
    if isinstance(tool_config, dict):
        function_calling_config = (
            tool_config.get("functionCallingConfig")
            or tool_config.get("function_calling_config")
            or {}
        )
    mode = str(function_calling_config.get("mode", "")).upper()
    if mode in ("ANY", "REQUIRED"):
        tool_instruction = "\n\n[CRITICAL INSTRUCTION] You MUST use one of the provided tools to respond. Do NOT respond with plain text."
        allowed_names = function_calling_config.get("allowedFunctionNames") or function_calling_config.get("allowed_function_names")
        if isinstance(allowed_names, list) and allowed_names:
            tool_instruction += f"\nAllowed tools: {', '.join(str(n) for n in allowed_names)}"
    
    system_attached = False
    
    for i, content in enumerate(contents):
        if not isinstance(content, dict):
            continue
        
        role = content.get("role", "user")
        parts = content.get("parts", [])
        is_last = (i == len(contents) - 1)
        if not isinstance(parts, list):
            parts = [parts] if parts else []
        
        # 提取文本和工具调用
        text_parts = []
        tool_calls = []
        tool_responses = []
        images = []
        
        for part_index, part in enumerate(parts):
            if isinstance(part, str):
                text_parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
            
            inline_image = _convert_gemini_inline_image_to_kiro(part)
            if inline_image:
                images.append(inline_image)
            
            if "fileData" in part and isinstance(part.get("fileData"), dict):
                file_data = part.get("fileData", {})
                text_parts.append(_gemini_file_data_note(file_data))
            
            function_call = part.get("functionCall")
            if not isinstance(function_call, dict):
                function_call = part.get("function_call")
            
            if isinstance(function_call, dict):
                # Gemini 的工具调用
                fc = function_call
                fc_name = str(fc.get("name", "") or "").strip()
                fc_id = str(fc.get("id") or f"{fc_name or 'tool'}_{i}_{part_index}")
                fc_args = fc.get("args", {})
                if isinstance(fc_args, str):
                    try:
                        parsed_args = json.loads(fc_args)
                        fc_args = parsed_args if isinstance(parsed_args, dict) else {"input": parsed_args}
                    except Exception:
                        fc_args = {"input": fc_args}
                elif not isinstance(fc_args, dict):
                    fc_args = {"input": fc_args}
                
                remember_call_id(fc_name, fc_id)
                
                tool_calls.append({
                    "toolUseId": fc_id,
                    "name": fc_name,
                    "input": fc_args
                })
                continue
            
            function_response = part.get("functionResponse")
            if not isinstance(function_response, dict):
                function_response = part.get("function_response")
            
            if isinstance(function_response, dict):
                # Gemini 的工具响应
                fr = function_response
                fr_name = str(fr.get("name", "") or "").strip()
                fr_id = str(fr.get("id") or "")
                call_id = consume_call_id(fr_name, fr_id) or f"{fr_name or 'tool'}_{i}_{part_index}"
                response_text, status = _extract_gemini_function_response(fr)
                
                tool_responses.append({
                    "content": [{"text": response_text}],
                    "status": status,
                    "toolUseId": call_id
                })
        
        text = "\n".join([t for t in text_parts if isinstance(t, str) and t])
        
        if role == "user":
            # 合并 system prompt
            if (system_text or tool_instruction) and not system_attached:
                system_prefix = f"{system_text}{tool_instruction}".strip()
                text = f"{system_prefix}\n\n{text}" if text else system_prefix
                system_attached = True
            
            if images and not is_last:
                image_note = f"[User attached {len(images)} image(s)]"
                text = f"{text}\n{image_note}" if text else image_note
            
            tool_responses = _dedupe_tool_results(tool_responses)
            
            if is_last:
                user_content = text if text else ("Tool results provided." if tool_responses else "Continue")
                current_tool_results = tool_responses
                current_images = images
            else:
                user_msg = {
                    "userInputMessage": {
                        "content": text if text else ("Tool results provided." if tool_responses else "Continue"),
                        "modelId": model,
                        "origin": "AI_EDITOR"
                    }
                }
                if tool_responses:
                    user_msg["userInputMessage"]["userInputMessageContext"] = {
                        "toolResults": tool_responses
                    }
                history.append(user_msg)
        
        elif role == "model":
            assistant_text = text if text else "I understand."
            
            assistant_msg = {
                "assistantResponseMessage": {
                    "content": assistant_text
                }
            }
            # 只有在有 toolUses 时才添加这个字段
            if tool_calls:
                assistant_msg["assistantResponseMessage"]["toolUses"] = tool_calls
            
            history.append(assistant_msg)
    
    # 如果没有用户消息
    if not user_content:
        if contents:
            last_parts = contents[-1].get("parts", [])
            user_content = " ".join(
                p.get("text", "") for p in last_parts
                if isinstance(p, dict) and "text" in p
            )
        if not user_content:
            user_content = "Continue"
    
    # 修复历史交替
    history = fix_history_alternation(history, model)
    
    # 转换工具
    kiro_tools = convert_gemini_tools_to_kiro(tools) if tools else []
    
    return user_content, history, current_tool_results, kiro_tools, current_images


def convert_kiro_response_to_gemini(result: dict, model: str) -> dict:
    """将 Kiro 响应转换为 Gemini 格式"""
    text = "".join(result.get("content", []))
    tool_uses = result.get("tool_uses", [])
    
    parts = []
    
    # 添加文本部分
    if text:
        parts.append({"text": text})
    
    # 添加工具调用
    for tool_use in tool_uses:
        if tool_use.get("type") == "tool_use":
            function_call = {
                "name": tool_use.get("name", ""),
                "args": tool_use.get("input", {})
            }
            if tool_use.get("id"):
                function_call["id"] = tool_use.get("id")
            parts.append({
                "functionCall": function_call
            })
    
    # 映射 stop_reason
    stop_reason = str(result.get("stop_reason", "")).lower()
    finish_reason = "STOP"
    if stop_reason == "max_tokens":
        finish_reason = "MAX_TOKENS"
    elif stop_reason in ("safety", "content_filter"):
        finish_reason = "SAFETY"
    elif stop_reason in ("recitation",):
        finish_reason = "RECITATION"
    
    prompt_tokens = int(result.get("input_tokens", 0) or 0)
    candidate_tokens = int(result.get("output_tokens", 0) or 0)
    
    return {
        "candidates": [{
            "content": {
                "parts": parts,
                "role": "model"
            },
            "finishReason": finish_reason,
            "index": 0
        }],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": candidate_tokens,
            "totalTokenCount": prompt_tokens + candidate_tokens
        }
    }
