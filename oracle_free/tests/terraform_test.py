import shutil
import unittest
from pathlib import Path

from oracle_free.config import OciConfig
from oracle_free.terraform import TerraformPlan, write_terraform_project


TEST_TMP = Path(__file__).resolve().parents[1] / "output" / "test-tmp"
_COUNTER = 0


class _TempDir:
    def __enter__(self):
        global _COUNTER
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        _COUNTER += 1
        self.path = TEST_TMP / f"tf-case-{_COUNTER}"
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


class TerraformTest(unittest.TestCase):
    def test_write_terraform_project_creates_always_free_vm_files(self):
        with _temp_dir() as tmp:
            tmp_path = Path(tmp)
            plan = TerraformPlan(
                project_name="oracle-always-free",
                region="us-ashburn-1",
                compartment_ocid="ocid1.tenancy.oc1..example",
                ssh_public_key="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey owner@example.com",
            )

            files = write_terraform_project(tmp_path, plan)

            main_tf = (tmp_path / "main.tf").read_text(encoding="utf-8")
            variables_tf = (tmp_path / "variables.tf").read_text(encoding="utf-8")
            tfvars = (tmp_path / "terraform.tfvars.example").read_text(encoding="utf-8")
            readme = (tmp_path / "README.md").read_text(encoding="utf-8")

        self.assertEqual(
            files,
            [
                tmp_path / "versions.tf",
                tmp_path / "variables.tf",
                tmp_path / "main.tf",
                tmp_path / "terraform.tfvars.example",
                tmp_path / "README.md",
            ],
        )
        self.assertIn("VM.Standard.A1.Flex", variables_tf + tfvars + readme)
        self.assertIn("is_ipv6enabled = var.create_ipv6", main_tf)
        self.assertIn("Canonical Ubuntu", main_tf)
        self.assertIn('variable "compartment_ocid"', variables_tf)
        self.assertIn("terraform init", readme)

    def test_plan_from_oci_config_uses_config_values(self):
        cfg = OciConfig(
            region="ap-seoul-1",
            compartment_ocid="ocid1.tenancy.oc1..abc",
            ssh_public_key="ssh-rsa AAAATEST owner@example.com",
            availability_domain="abc:AP-SEOUL-1-AD-1",
        )

        plan = TerraformPlan.from_oci_config(cfg, project_name="oci-free")

        self.assertEqual(plan.region, "ap-seoul-1")
        self.assertEqual(plan.compartment_ocid, "ocid1.tenancy.oc1..abc")
        self.assertEqual(plan.availability_domain, "abc:AP-SEOUL-1-AD-1")


if __name__ == "__main__":
    unittest.main()
