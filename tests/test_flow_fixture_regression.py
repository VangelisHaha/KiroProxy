import json
import unittest
from pathlib import Path

from kiro_proxy.core.error_handler import ErrorType, classify_error


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "e2e" / "flows_2026-04-17.json"


class FlowFixtureRegressionTests(unittest.TestCase):
    def test_real_flow_fixture_profile_arn_errors_stay_classified_as_auth(self):
        flows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertIsInstance(flows, list)
        self.assertGreater(len(flows), 0)

        seen_profile_arn_error = False
        for item in flows:
            error = item.get("error", {}) if isinstance(item, dict) else {}
            message = error.get("message", "")
            status_code = error.get("status_code")
            if "profileArn" not in message:
                continue
            seen_profile_arn_error = True
            classified = classify_error(status_code, message)
            self.assertEqual(classified.type, ErrorType.AUTH_FAILED)

        self.assertTrue(seen_profile_arn_error)


if __name__ == "__main__":
    unittest.main()
