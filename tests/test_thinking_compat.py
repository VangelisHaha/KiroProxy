import unittest

from kiro_proxy.converters import (
    build_thinking_prefix,
    convert_anthropic_messages_to_kiro,
    convert_gemini_contents_to_kiro,
    convert_openai_messages_to_kiro,
)


class ThinkingCompatTests(unittest.TestCase):
    def test_build_thinking_prefix_enabled_clamps_budget(self):
        prefix = build_thinking_prefix({"type": "enabled", "budget_tokens": 1})
        self.assertIn("<thinking_mode>enabled</thinking_mode>", prefix)
        self.assertIn("<max_thinking_length>1024</max_thinking_length>", prefix)

    def test_anthropic_converter_injects_thinking_prefix(self):
        user_content, _, _ = convert_anthropic_messages_to_kiro(
            [{"role": "user", "content": "hello"}],
            system="system prompt",
            thinking={"type": "enabled", "budget_tokens": 1234},
        )
        self.assertIn("<thinking_mode>enabled</thinking_mode>", user_content)
        self.assertIn("<max_thinking_length>1234</max_thinking_length>", user_content)

    def test_openai_converter_injects_thinking_prefix(self):
        user_content, _, _, _ = convert_openai_messages_to_kiro(
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "hello"},
            ],
            model="claude-sonnet-4",
            tools=[],
            tool_choice=None,
            thinking={"type": "adaptive", "effort": "high"},
        )
        self.assertIn("<thinking_mode>adaptive</thinking_mode>", user_content)
        self.assertIn("<thinking_effort>high</thinking_effort>", user_content)

    def test_gemini_converter_maps_thinking_config_to_prefix(self):
        user_content, history, tool_results, _, _ = convert_gemini_contents_to_kiro(
            contents=[{"role": "user", "parts": [{"text": "hello"}]}],
            system_instruction={"parts": [{"text": "system prompt"}]},
            model="claude-sonnet-4",
            tools=[],
            tool_config={},
            thinking_config={"includeThoughts": True, "thinkingBudget": 999999},
        )
        self.assertEqual(history, [])
        self.assertEqual(tool_results, [])
        self.assertIn("<thinking_mode>enabled</thinking_mode>", user_content)
        self.assertIn("<max_thinking_length>24576</max_thinking_length>", user_content)


if __name__ == "__main__":
    unittest.main()
