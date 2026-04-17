import unittest

from kiro_proxy.credential.types import KiroCredentials
from kiro_proxy.providers.kiro import KiroProvider


class KiroProviderRequestTests(unittest.TestCase):
    def test_build_request_includes_top_level_profile_arn(self):
        creds = KiroCredentials(profile_arn="arn:aws:codewhisperer:us-east-1:123456789012:profile/test")
        provider = KiroProvider(credentials=creds)

        payload = provider.build_request(user_content="ping", model="claude-haiku-4.5", history=[])

        self.assertIn("conversationState", payload)
        self.assertEqual(payload.get("profileArn"), creds.profile_arn)
        self.assertEqual(payload["conversationState"].get("profileArn"), creds.profile_arn)


if __name__ == "__main__":
    unittest.main()
