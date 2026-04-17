import unittest

from kiro_proxy.handlers.responses import (
    _build_response,
    _convert_responses_input_to_kiro,
    _convert_tools_to_kiro,
)


class ResponsesCompatTests(unittest.TestCase):
    def test_convert_supports_modern_tool_output_item_types(self):
        input_data = [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Running tools."}],
            },
            {
                "type": "function_call",
                "call_id": "call_fn",
                "name": "local_shell",
                "arguments": "{\"command\":[\"pwd\"]}",
            },
            {
                "type": "custom_tool_call_output",
                "call_id": "call_fn",
                "output": "done",
            },
            {
                "type": "mcp_tool_call_output",
                "call_id": "call_mcp",
                "output": {
                    "content": [{"type": "text", "text": "mcp result"}],
                    "isError": False,
                },
            },
            {
                "type": "tool_search_output",
                "call_id": "call_search",
                "status": "failed",
                "execution": "client",
                "tools": [{"name": "calendar"}],
            },
        ]

        user_content, history, tool_results, images = _convert_responses_input_to_kiro(input_data)
        self.assertEqual(user_content, "Please continue based on the tool results.")
        self.assertEqual(len(history), 1)
        self.assertIsNone(images)
        self.assertEqual(len(tool_results), 3)

        by_id = {item["toolUseId"]: item for item in tool_results}
        self.assertEqual(by_id["call_fn"]["status"], "success")
        self.assertIn("done", by_id["call_fn"]["content"][0]["text"])
        self.assertEqual(by_id["call_mcp"]["status"], "success")
        self.assertIn("mcp result", by_id["call_mcp"]["content"][0]["text"])
        self.assertEqual(by_id["call_search"]["status"], "error")

    def test_convert_supports_output_content_array(self):
        input_data = [
            {
                "type": "function_call_output",
                "call_id": "call_array",
                "output": [
                    {"type": "input_text", "text": "line-1"},
                    {"type": "input_text", "text": "line-2"},
                ],
            }
        ]

        _, _, tool_results, _ = _convert_responses_input_to_kiro(input_data)
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]["toolUseId"], "call_array")
        self.assertEqual(tool_results[0]["content"][0]["text"], "line-1\nline-2")

    def test_convert_message_extracts_data_image(self):
        input_data = [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "describe this"},
                    {"type": "input_image", "image_url": "data:image/png;base64,QUJD"},
                ],
            }
        ]

        user_content, history, tool_results, images = _convert_responses_input_to_kiro(input_data)
        self.assertEqual(user_content, "describe this")
        self.assertEqual(history, [])
        self.assertEqual(tool_results, [])
        self.assertEqual(len(images or []), 1)
        self.assertEqual(images[0]["format"], "png")
        self.assertEqual(images[0]["source"]["bytes"], "QUJD")

    def test_convert_tools_maps_special_types(self):
        tools = [
            {"type": "local_shell"},
            {
                "type": "tool_search",
                "description": "Search tools",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            },
            {"type": "web_search", "external_web_access": False},
            {"type": "web_search", "external_web_access": True},
        ]
        kiro_tools = _convert_tools_to_kiro(tools)
        self.assertIsNotNone(kiro_tools)
        self.assertEqual(len(kiro_tools), 3)

        tool_specs = [t.get("toolSpecification", {}) for t in kiro_tools if "toolSpecification" in t]
        names = {spec.get("name") for spec in tool_specs}
        self.assertIn("local_shell", names)
        self.assertIn("tool_search", names)
        self.assertTrue(any("webSearchTool" in t for t in kiro_tools))

    def test_build_response_uses_stable_call_id(self):
        result = {
            "content": [],
            "tool_uses": [{"name": "calendar_lookup", "input": {"date": "2026-01-01"}}],
        }
        response = _build_response(result, "claude-sonnet-4", "abc123")
        self.assertEqual(response["status"], "completed")
        self.assertEqual(len(response["output"]), 1)
        tool_call = response["output"][0]
        self.assertEqual(tool_call["type"], "function_call")
        self.assertEqual(tool_call["id"], tool_call["call_id"])

    def test_convert_supports_web_and_image_call_history_items(self):
        input_data = [
            {
                "type": "web_search_call",
                "id": "ws_1",
                "status": "completed",
                "action": {"type": "search", "query": "profileArn"},
            },
            {
                "type": "image_generation_call",
                "id": "ig_1",
                "status": "completed",
                "revised_prompt": "proxy dashboard",
                "result": "data:image/png;base64,AAAA",
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "continue"}],
            },
        ]

        user_content, history, tool_results, _ = _convert_responses_input_to_kiro(input_data)
        self.assertIn("continue", user_content)
        self.assertEqual(tool_results, [])
        assistant_texts = [
            h["assistantResponseMessage"]["content"]
            for h in history
            if "assistantResponseMessage" in h
        ]
        self.assertTrue(any("[web_search_call:" in text for text in assistant_texts))
        self.assertTrue(any("[image_generation_call:" in text for text in assistant_texts))

    def test_convert_preserves_tool_pairing_when_only_call_and_output_items_exist(self):
        input_data = [
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "run_shell_command",
                "arguments": "{\"command\":[\"pwd\"]}",
            },
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "ok",
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "next"}],
            },
        ]

        user_content, history, tool_results, _ = _convert_responses_input_to_kiro(input_data)
        self.assertIn("next", user_content)
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]["toolUseId"], "call_1")

        tool_use_ids = []
        for item in history:
            assistant = item.get("assistantResponseMessage")
            if not assistant:
                continue
            tool_use_ids.extend([tu.get("toolUseId") for tu in assistant.get("toolUses", [])])
        self.assertIn("call_1", tool_use_ids)

    def test_convert_namespaced_function_call_keeps_namespace_in_tool_name(self):
        input_data = [
            {
                "type": "function_call",
                "call_id": "call_ns_1",
                "name": "read_resource",
                "namespace": "mcp.files",
                "arguments": "{\"path\":\"README.md\"}",
            },
            {
                "type": "function_call_output",
                "call_id": "call_ns_1",
                "output": "done",
            },
        ]

        _, history, tool_results, _ = _convert_responses_input_to_kiro(input_data)
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]["toolUseId"], "call_ns_1")
        self.assertEqual(len(history), 1)
        tool_uses = history[0]["assistantResponseMessage"].get("toolUses", [])
        self.assertEqual(tool_uses[0]["name"], "mcp.files.read_resource")


if __name__ == "__main__":
    unittest.main()
