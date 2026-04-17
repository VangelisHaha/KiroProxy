import json
import tempfile
import unittest
from pathlib import Path

from kiro_proxy.core.account import Account


class AccountCredentialsMergeTests(unittest.TestCase):
    def test_load_credentials_merges_client_secret_with_client_id_hash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            hash_name = "abc123hash"

            token_file = cache_dir / "token.json"
            token_file.write_text(
                json.dumps(
                    {
                        "accessToken": "at",
                        "refreshToken": "rt",
                        "clientId": "cid",
                        "clientIdHash": hash_name,
                        "authMethod": "idc",
                    }
                ),
                encoding="utf-8",
            )

            hash_file = cache_dir / f"{hash_name}.json"
            hash_file.write_text(
                json.dumps(
                    {
                        "clientId": "cid",
                        "clientSecret": "secret-value",
                    }
                ),
                encoding="utf-8",
            )

            account = Account(id="a1", name="test", token_path=str(token_file))
            creds = account.load_credentials()

            self.assertIsNotNone(creds)
            self.assertEqual(creds.client_id, "cid")
            self.assertEqual(creds.client_secret, "secret-value")

    def test_load_credentials_merges_profile_arn_from_neighbor_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            token_file = cache_dir / "kiro-auth-token.json"
            token_file.write_text(
                json.dumps(
                    {
                        "accessToken": "at",
                        "refreshToken": "rt",
                        "authMethod": "social",
                    }
                ),
                encoding="utf-8",
            )

            extra_file = cache_dir / "session-extra.json"
            extra_file.write_text(
                json.dumps(
                    {
                        "profileArn": "arn:aws:codewhisperer:us-east-1:123456789012:profile/test",
                        "region": "us-east-1",
                    }
                ),
                encoding="utf-8",
            )

            account = Account(id="a2", name="test2", token_path=str(token_file))
            creds = account.load_credentials()

            self.assertIsNotNone(creds)
            self.assertEqual(
                creds.profile_arn,
                "arn:aws:codewhisperer:us-east-1:123456789012:profile/test",
            )

    def test_load_credentials_recovers_corrupted_json_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            token_file = cache_dir / "kiro-auth-token.json"
            token_file.write_text(
                '{"accessToken":"at","refreshToken":"rt","clientId":"cid","clientSecret":"sec","profileArn":"arn:aws:codewhisperer:us-east-1:123456789012:profile/test",',
                encoding="utf-8",
            )

            account = Account(id="a3", name="test3", token_path=str(token_file))
            creds = account.load_credentials()

            self.assertIsNotNone(creds)
            self.assertEqual(creds.access_token, "at")
            self.assertEqual(creds.client_id, "cid")
            self.assertEqual(creds.client_secret, "sec")
            self.assertEqual(
                creds.profile_arn,
                "arn:aws:codewhisperer:us-east-1:123456789012:profile/test",
            )


if __name__ == "__main__":
    unittest.main()
