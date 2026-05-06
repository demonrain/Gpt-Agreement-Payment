import json
import shutil
import unittest
from pathlib import Path

from oracle_free.config import ConfigError, load_config


TEST_TMP = Path(__file__).resolve().parents[1] / "output" / "test-tmp"


_COUNTER = 0


class _TempDir:
    def __enter__(self):
        global _COUNTER
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        _COUNTER += 1
        self.path = TEST_TMP / f"case-{_COUNTER}"
        if self.path.exists():
            shutil.rmtree(self.path)
        self.path.mkdir(parents=True)
        return str(self.path)

    def __exit__(self, exc_type, exc, tb):
        shutil.rmtree(self.path, ignore_errors=True)
        return False


def _temp_dir():
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    return _TempDir()


def _valid_config():
    return {
        "profile": {
            "email": "owner@example.com",
            "first_name": "Ada",
            "last_name": "Lovelace",
            "country": "US",
            "home_region": "us-ashburn-1",
            "cloud_account_name": "ada-lab",
        },
        "oci": {
            "region": "us-ashburn-1",
            "compartment_ocid": "ocid1.tenancy.oc1..example",
            "ssh_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey owner@example.com",
        },
    }


class ConfigTest(unittest.TestCase):
    def test_load_config_accepts_minimal_owner_profile(self):
        with _temp_dir() as tmp:
            path = Path(tmp) / "oracle.json"
            path.write_text(json.dumps(_valid_config()), encoding="utf-8")

            cfg = load_config(path)

        self.assertEqual(cfg.profile.email, "owner@example.com")
        self.assertEqual(cfg.profile.cloud_account_name, "ada-lab")
        self.assertEqual(cfg.oci.region, "us-ashburn-1")

    def test_load_config_rejects_stored_payment_or_verification_secrets(self):
        with _temp_dir() as tmp:
            data = _valid_config()
            data["payment"] = {"card_number": "4111111111111111", "cvv": "123"}
            data["captcha_solver"] = {"api_key": "not-allowed"}
            path = Path(tmp) / "oracle.json"
            path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaises(ConfigError) as cm:
                load_config(path)

        message = str(cm.exception)
        self.assertIn("card_number", message)
        self.assertIn("cvv", message)
        self.assertIn("captcha_solver", message)

    def test_safe_dict_redacts_personal_contact_fields(self):
        with _temp_dir() as tmp:
            path = Path(tmp) / "oracle.json"
            path.write_text(json.dumps(_valid_config()), encoding="utf-8")

            safe = load_config(path).to_safe_dict()

        self.assertEqual(safe["profile"]["email"], "o***@example.com")
        self.assertEqual(safe["profile"]["first_name"], "A***")
        self.assertEqual(safe["profile"]["last_name"], "L***")


if __name__ == "__main__":
    unittest.main()
