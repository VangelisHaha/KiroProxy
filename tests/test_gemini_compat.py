import unittest

from kiro_proxy.converters import (
    convert_gemini_contents_to_kiro,
    convert_kiro_response_to_gemini,
    convert_gemini_tools_to_kiro,
)


class GeminiCompatTests(unittest.TestCase):
    def test_convert_matches_function_response_ids_by_order_when_missing(self):
        contents = [
            {"role": "user", "parts": [{"text": "run tools"}]},
            {
                "role": "model",
                "parts": [
                    {"functionCall": {"id": "call_1", "name": "search", "args": {"q": "a"}}},
                    {"functionCall": {"id": "call_2", "name": "search", "args": {"q": "b"}}},
                ],
            },
            {
                "role": "user",
                "parts": [
                    {"functionResponse": {"name": "search", "response": {"output": "result a"}}},
                    {"functionResponse": {"name": "search", "response": {"output": "result b"}}},
                ],
            },
        ]

        user_content, history, tool_results, kiro_tools, images = convert_gemini_contents_to_kiro(
            contents, {}, "claude-sonnet-4"
        )

        self.assertEqual(user_content, "Tool results provided.")
        self.assertEqual(kiro_tools, [])
        self.assertEqual(images, [])
        self.assertEqual(len(history), 2)
        self.assertEqual([tr["toolUseId"] for tr in tool_results], ["call_1", "call_2"])
        self.assertEqual([tr["content"][0]["text"] for tr in tool_results], ["result a", "result b"])

    def test_convert_prefers_explicit_function_response_id_and_merges_duplicates(self):
        contents = [
            {"role": "user", "parts": [{"text": "run tools"}]},
            {
                "role": "model",
                "parts": [
                    {"functionCall": {"id": "call_a", "name": "lookup", "args": {"k": "a"}}},
                    {"functionCall": {"id": "call_b", "name": "lookup", "args": {"k": "b"}}},
                ],
            },
            {
                "role": "user",
                "parts": [
                    {"functionResponse": {"id": "call_b", "name": "lookup", "response": {"output": "b-1"}}},
                    {"functionResponse": {"name": "lookup", "response": {"output": "a-1"}}},
                    {"functionResponse": {"id": "call_b", "name": "lookup", "response": {"output": "b-2"}}},
                ],
            },
        ]

        _, _, tool_results, _, _ = convert_gemini_contents_to_kiro(contents, {}, "claude-sonnet-4")
        self.assertEqual([tr["toolUseId"] for tr in tool_results], ["call_b", "call_a"])
        by_id = {tr["toolUseId"]: tr for tr in tool_results}
        self.assertIn("b-1", by_id["call_b"]["content"][0]["text"])
        self.assertIn("b-2", by_id["call_b"]["content"][0]["text"])
        self.assertEqual(by_id["call_a"]["content"][0]["text"], "a-1")

    def test_convert_extracts_inline_image_for_last_user_message(self):
        contents = [
            {
                "role": "user",
                "parts": [
                    {"text": "describe image"},
                    {"inlineData": {"mimeType": "image/png", "data": "QUJD"}},
                ],
            }
        ]

        user_content, history, tool_results, _, images = convert_gemini_contents_to_kiro(
            contents, {}, "claude-sonnet-4"
        )
        self.assertEqual(user_content, "describe image")
        self.assertEqual(history, [])
        self.assertEqual(tool_results, [])
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["format"], "png")
        self.assertEqual(images[0]["source"]["bytes"], "QUJD")

    def test_convert_function_response_keeps_multimodal_hints(self):
        contents = [
            {
                "role": "model",
                "parts": [{"functionCall": {"id": "call_img", "name": "vision_tool", "args": {}}}],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "vision_tool",
                            "response": {"output": "done"},
                            "parts": [{"inlineData": {"mimeType": "image/png", "data": "AAAA"}}],
                        }
                    }
                ],
            },
        ]

        _, _, tool_results, _, _ = convert_gemini_contents_to_kiro(contents, {}, "claude-sonnet-4")
        self.assertEqual(len(tool_results), 1)
        self.assertEqual(tool_results[0]["toolUseId"], "call_img")
        text = tool_results[0]["content"][0]["text"]
        self.assertIn("done", text)
        self.assertIn("Inline data", text)

    def test_convert_kiro_response_to_gemini_preserves_function_call_id(self):
        result = {
            "content": ["hello"],
            "tool_uses": [
                {"type": "tool_use", "id": "call_xyz", "name": "lookup", "input": {"city": "Shanghai"}}
            ],
            "stop_reason": "max_tokens",
            "input_tokens": 11,
            "output_tokens": 7,
        }

        gemini = convert_kiro_response_to_gemini(result, "gemini-2.0-flash")
        candidate = gemini["candidates"][0]
        parts = candidate["content"]["parts"]

        self.assertEqual(parts[0]["text"], "hello")
        self.assertEqual(parts[1]["functionCall"]["name"], "lookup")
        self.assertEqual(parts[1]["functionCall"]["id"], "call_xyz")
        self.assertEqual(candidate["finishReason"], "MAX_TOKENS")
        self.assertEqual(gemini["usageMetadata"]["promptTokenCount"], 11)
        self.assertEqual(gemini["usageMetadata"]["candidatesTokenCount"], 7)
        self.assertEqual(gemini["usageMetadata"]["totalTokenCount"], 18)

    def test_convert_gemini_tools_maps_url_context_to_web_search(self):
        tools = [{"urlContext": {}}]
        kiro_tools = convert_gemini_tools_to_kiro(tools)
        self.assertEqual(len(kiro_tools), 1)
        self.assertIn("webSearchTool", kiro_tools[0])
        self.assertEqual(kiro_tools[0]["webSearchTool"]["type"], "web_search")


if __name__ == "__main__":
    unittest.main()
