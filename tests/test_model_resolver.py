import unittest

from kiro_proxy.model_resolver import merge_advertised_models


class ModelResolverTests(unittest.TestCase):
    def test_merge_advertised_models_adds_hidden_models_without_duplicates(self):
        models = merge_advertised_models(
            [{"modelId": "claude-opus-4.5", "modelName": "Claude Opus 4.5"}],
            ["gpt-5.6-sol", "claude-opus-4.5", "gpt-5.6-terra"],
        )

        self.assertEqual(
            [model["modelId"] for model in models],
            ["claude-opus-4.5", "gpt-5.6-sol", "gpt-5.6-terra"],
        )


if __name__ == "__main__":
    unittest.main()
