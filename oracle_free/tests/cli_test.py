import json
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from oracle_free.cli import main


TEST_TMP = Path(__file__).resolve().parents[1] / "output" / "test-tmp"
_COUNTER = 0


class _TempDir:
    def __enter__(self):
        global _COUNTER
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        _COUNTER += 1
        self.path = TEST_TMP / f"cli-case-{_COUNTER}"
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


def _config(tmp_path: Path):
    path = tmp_path / "oracle.json"
    path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    return path


def _run(argv):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class CliTest(unittest.TestCase):
    def test_cli_validate_prints_redacted_config(self):
        with _temp_dir() as tmp:
            code, out, _err = _run(["validate", "--config", str(_config(Path(tmp)))])

        self.assertEqual(code, 0)
        self.assertIn("o***@example.com", out)
        self.assertNotIn("owner@example.com", out)

    def test_cli_init_terraform_writes_project(self):
        with _temp_dir() as tmp:
            tmp_path = Path(tmp)
            out_dir = tmp_path / "terraform"

            code, out, _err = _run(
                [
                    "init-terraform",
                    "--config",
                    str(_config(tmp_path)),
                    "--out-dir",
                    str(out_dir),
                ]
            )

            self.assertEqual(code, 0)
            self.assertIn("main.tf", out)
            self.assertTrue((out_dir / "main.tf").exists())

    def test_cli_register_assistant_dry_run_shows_manual_boundaries(self):
        with _temp_dir() as tmp:
            code, out, _err = _run(
                ["register-assistant", "--config", str(_config(Path(tmp))), "--dry-run"]
            )

        self.assertEqual(code, 0)
        self.assertIn("https://www.oracle.com/cloud/free/", out)
        self.assertIn("manual", out.lower())
        self.assertIn("CAPTCHA", out)


if __name__ == "__main__":
    unittest.main()
