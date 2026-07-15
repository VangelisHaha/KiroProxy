import unittest
from unittest.mock import patch

from kiro_proxy.credential.fingerprint import generate_machine_id, get_kiro_version


class MachineIdStabilityTests(unittest.TestCase):
    def test_kiro_version_supports_environment_override(self):
        with patch.dict("os.environ", {"KIRO_CLIENT_VERSION": "1.0.138"}):
            self.assertEqual(get_kiro_version(), "1.0.138")

    def test_machine_id_is_stable_for_same_inputs(self):
        m1 = generate_machine_id(
            profile_arn="arn:aws:codewhisperer:us-east-1:123456789012:profile/test",
            client_id="client-a",
            uuid="node-1",
        )
        m2 = generate_machine_id(
            profile_arn="arn:aws:codewhisperer:us-east-1:123456789012:profile/test",
            client_id="client-a",
            uuid="node-1",
        )
        self.assertEqual(m1, m2)

    def test_machine_id_prefers_uuid_over_profile_arn(self):
        with_uuid = generate_machine_id(
            profile_arn="arn:aws:codewhisperer:us-east-1:123456789012:profile/test",
            client_id="client-a",
            uuid="node-1",
        )
        uuid_only = generate_machine_id(uuid="node-1")
        self.assertEqual(with_uuid, uuid_only)


if __name__ == "__main__":
    unittest.main()
