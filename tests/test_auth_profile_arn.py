import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from kiro_proxy.core.auth_guard import ensure_profile_arn_ready
from kiro_proxy.core.error_handler import classify_error, ErrorType


class _DummyCreds:
    def __init__(self, profile_arn=None, refresh_token="rt"):
        self.profile_arn = profile_arn
        self.refresh_token = refresh_token

    def save_to_file(self, _path):
        return None


class _DummyAccount:
    def __init__(self, creds, refresh_result=(True, "ok"), refreshed_profile_arn=None, token_path=None):
        self._creds = creds
        self._refresh_result = refresh_result
        self._refreshed_profile_arn = refreshed_profile_arn
        self.refresh_calls = 0
        self.token_path = token_path or "/tmp/dummy-token.json"
        self._machine_id = "dummy"

    def get_credentials(self):
        return self._creds

    async def refresh_token(self):
        self.refresh_calls += 1
        ok, msg = self._refresh_result
        if ok and self._refreshed_profile_arn:
            self._creds.profile_arn = self._refreshed_profile_arn
        return ok, msg


class AuthProfileArnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._old_env = os.environ.get("KIRO_PROFILE_ARN")

    async def asyncTearDown(self):
        if self._old_env is None:
            os.environ.pop("KIRO_PROFILE_ARN", None)
        else:
            os.environ["KIRO_PROFILE_ARN"] = self._old_env

    async def test_ensure_profile_arn_ready_passes_when_present(self):
        account = _DummyAccount(_DummyCreds(profile_arn="arn:aws:test"))
        ok, msg = await ensure_profile_arn_ready(account)
        self.assertTrue(ok)
        self.assertEqual(msg, "")
        self.assertEqual(account.refresh_calls, 0)

    async def test_ensure_profile_arn_ready_refreshes_when_missing(self):
        account = _DummyAccount(
            _DummyCreds(profile_arn=None, refresh_token="rt"),
            refresh_result=(True, "ok"),
            refreshed_profile_arn="arn:aws:test",
        )
        with patch("kiro_proxy.core.auth_guard._find_profile_arn_from_kiro_logs", return_value=None):
            ok, msg = await ensure_profile_arn_ready(account)
        self.assertTrue(ok)
        self.assertEqual(msg, "")
        self.assertEqual(account.refresh_calls, 1)

    async def test_ensure_profile_arn_ready_fails_when_refresh_no_profile(self):
        account = _DummyAccount(
            _DummyCreds(profile_arn=None, refresh_token="rt"),
            refresh_result=(True, "ok"),
            refreshed_profile_arn=None,
        )
        with patch("kiro_proxy.core.auth_guard._find_profile_arn_from_kiro_logs", return_value=None):
            ok, msg = await ensure_profile_arn_ready(account)
        self.assertFalse(ok)
        self.assertIn("缺少 profileArn", msg)
        self.assertEqual(account.refresh_calls, 1)

    async def test_ensure_profile_arn_ready_backfills_from_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "token.json"
            token_path.write_text("{}", encoding="utf-8")

            os.environ["KIRO_PROFILE_ARN"] = "arn:aws:codewhisperer:us-east-1:123456789012:profile/test"
            account = _DummyAccount(
                _DummyCreds(profile_arn=None, refresh_token=None),
                token_path=str(token_path),
            )
            ok, msg = await ensure_profile_arn_ready(account)
            self.assertTrue(ok)
            self.assertEqual(msg, "")
            self.assertEqual(account.get_credentials().profile_arn, os.environ["KIRO_PROFILE_ARN"])
            self.assertIsNone(account._machine_id)

    def test_classify_error_maps_profile_arn_required_to_auth_failed(self):
        err = classify_error(
            400,
            "{\"message\":\"profileArn is required for this request.\",\"reason\":null}",
        )
        self.assertEqual(err.type, ErrorType.AUTH_FAILED)
        self.assertIn("profileArn", err.user_message)


if __name__ == "__main__":
    unittest.main()
