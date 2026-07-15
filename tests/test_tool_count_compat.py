import unittest

from kiro_proxy.converters import (
    convert_anthropic_tools_to_kiro,
    convert_gemini_tools_to_kiro,
    convert_openai_tools_to_kiro,
)
from kiro_proxy.handlers.responses import _convert_tools_to_kiro


TOOL_COUNT = 75


def _tool_names(converted):
    return [
        item["toolSpecification"]["name"]
        for item in converted or []
        if "toolSpecification" in item
    ]


class ToolCountCompatTests(unittest.TestCase):
    def test_anthropic_keeps_all_mcp_and_skill_tools(self):
        tools = [
            {
                "name": f"skill_or_mcp_{index}",
                "description": f"tool {index}",
                "input_schema": {"type": "object", "properties": {}},
            }
            for index in range(TOOL_COUNT)
        ]

        names = _tool_names(convert_anthropic_tools_to_kiro(tools))

        self.assertEqual(len(names), TOOL_COUNT)
        self.assertEqual(names[-1], "skill_or_mcp_74")

    def test_openai_chat_keeps_all_tools(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": f"chat_tool_{index}",
                    "description": f"tool {index}",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for index in range(TOOL_COUNT)
        ]

        names = _tool_names(convert_openai_tools_to_kiro(tools))

        self.assertEqual(len(names), TOOL_COUNT)
        self.assertEqual(names[-1], "chat_tool_74")

    def test_openai_responses_keeps_all_tools(self):
        tools = [
            {
                "type": "function",
                "name": f"responses_tool_{index}",
                "description": f"tool {index}",
                "parameters": {"type": "object", "properties": {}},
            }
            for index in range(TOOL_COUNT)
        ]

        names = _tool_names(_convert_tools_to_kiro(tools))

        self.assertEqual(len(names), TOOL_COUNT)
        self.assertEqual(names[-1], "responses_tool_74")

    def test_gemini_keeps_all_tools(self):
        tools = [{
            "functionDeclarations": [
                {
                    "name": f"gemini_tool_{index}",
                    "description": f"tool {index}",
                    "parameters": {"type": "object", "properties": {}},
                }
                for index in range(TOOL_COUNT)
            ]
        }]

        names = _tool_names(convert_gemini_tools_to_kiro(tools))

        self.assertEqual(len(names), TOOL_COUNT)
        self.assertEqual(names[-1], "gemini_tool_74")


if __name__ == "__main__":
    unittest.main()
