from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template

from .config import OciConfig


@dataclass
class TerraformPlan:
    project_name: str
    region: str
    compartment_ocid: str
    ssh_public_key: str
    availability_domain: str = ""
    shape: str = "VM.Standard.A1.Flex"
    ocpus: float = 1.0
    memory_gbs: float = 6.0
    boot_volume_gbs: int = 50
    create_ipv6: bool = True
    instance_name: str = "always-free-a1"

    @classmethod
    def from_oci_config(cls, cfg: OciConfig, project_name: str = "oracle-free") -> "TerraformPlan":
        return cls(
            project_name=project_name,
            region=cfg.region,
            compartment_ocid=cfg.compartment_ocid,
            ssh_public_key=cfg.ssh_public_key,
            availability_domain=cfg.availability_domain,
            shape=cfg.shape,
            ocpus=cfg.ocpus,
            memory_gbs=cfg.memory_gbs,
            boot_volume_gbs=cfg.boot_volume_gbs,
            create_ipv6=cfg.create_ipv6,
            instance_name=cfg.instance_name,
        )


def write_terraform_project(out_dir: str | Path, plan: TerraformPlan) -> list[Path]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    files = [
        target / "versions.tf",
        target / "variables.tf",
        target / "main.tf",
        target / "terraform.tfvars.example",
        target / "README.md",
    ]
    payloads = {
        "versions.tf": _versions_tf(),
        "variables.tf": _variables_tf(),
        "main.tf": _main_tf(),
        "terraform.tfvars.example": _tfvars_example(plan),
        "README.md": _readme(plan),
    }
    for path in files:
        path.write_text(payloads[path.name], encoding="utf-8")
    return files


def _versions_tf() -> str:
    return """terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

provider "oci" {
  region = var.region
}
"""


def _variables_tf() -> str:
    return """variable "region" {
  description = "OCI home or target region, for example us-ashburn-1."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment OCID where Always Free resources will be created."
  type        = string
}

variable "availability_domain" {
  description = "Optional availability domain. Leave empty to use the first available AD."
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "SSH public key installed on the instance."
  type        = string
}

variable "instance_name" {
  description = "Display name for the instance."
  type        = string
  default     = "always-free-a1"
}

variable "shape" {
  description = "Compute shape. VM.Standard.A1.Flex is commonly used for Always Free ARM."
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "ocpus" {
  description = "OCPUs assigned to the flex instance."
  type        = number
  default     = 1
}

variable "memory_gbs" {
  description = "Memory assigned to the flex instance."
  type        = number
  default     = 6
}

variable "boot_volume_gbs" {
  description = "Boot volume size in GB."
  type        = number
  default     = 50
}

variable "create_ipv6" {
  description = "Enable IPv6 on the VCN and subnet."
  type        = bool
  default     = true
}
"""


def _main_tf() -> str:
    return """data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_ocid
}

locals {
  selected_ad = var.availability_domain != "" ? var.availability_domain : data.oci_identity_availability_domains.ads.availability_domains[0].name
}

data "oci_core_images" "ubuntu" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = var.shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "free" {
  compartment_id = var.compartment_ocid
  cidr_block     = "10.20.0.0/16"
  display_name   = "${var.instance_name}-vcn"
  dns_label      = "freevcn"
  is_ipv6enabled = var.create_ipv6
}

resource "oci_core_internet_gateway" "free" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.instance_name}-igw"
  vcn_id         = oci_core_vcn.free.id
  enabled        = true
}

resource "oci_core_route_table" "free" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.instance_name}-rt"
  vcn_id         = oci_core_vcn.free.id

  route_rules {
    network_entity_id = oci_core_internet_gateway.free.id
    destination       = "0.0.0.0/0"
  }
}

resource "oci_core_security_list" "free" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.instance_name}-sl"
  vcn_id         = oci_core_vcn.free.id

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"

    tcp_options {
      min = 22
      max = 22
    }
  }

  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_subnet" "free" {
  compartment_id             = var.compartment_ocid
  cidr_block                 = "10.20.1.0/24"
  display_name               = "${var.instance_name}-subnet"
  dns_label                  = "freesubnet"
  vcn_id                     = oci_core_vcn.free.id
  route_table_id             = oci_core_route_table.free.id
  security_list_ids          = [oci_core_security_list.free.id]
  prohibit_public_ip_on_vnic = false
  ipv6cidr_block             = var.create_ipv6 ? cidrsubnet(oci_core_vcn.free.ipv6cidr_blocks[0], 8, 1) : null
}

resource "oci_core_instance" "free" {
  availability_domain = local.selected_ad
  compartment_id      = var.compartment_ocid
  display_name        = var.instance_name
  shape               = var.shape

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_gbs
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.free.id
    assign_public_ip = true
    assign_ipv6ip    = var.create_ipv6
    display_name     = "${var.instance_name}-vnic"
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_gbs
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
  }
}

output "instance_public_ip" {
  value = oci_core_instance.free.public_ip
}

output "instance_private_ip" {
  value = oci_core_instance.free.private_ip
}

output "image_name" {
  value = data.oci_core_images.ubuntu.images[0].display_name
}
"""


def _tfvars_example(plan: TerraformPlan) -> str:
    return Template(
        '''region              = "$region"
compartment_ocid    = "$compartment_ocid"
availability_domain = "$availability_domain"
ssh_public_key      = "$ssh_public_key"
instance_name       = "$instance_name"
shape               = "$shape"
ocpus               = $ocpus
memory_gbs          = $memory_gbs
boot_volume_gbs     = $boot_volume_gbs
create_ipv6         = $create_ipv6
'''
    ).substitute(
        region=plan.region,
        compartment_ocid=plan.compartment_ocid,
        availability_domain=plan.availability_domain,
        ssh_public_key=plan.ssh_public_key,
        instance_name=plan.instance_name,
        shape=plan.shape,
        ocpus=plan.ocpus,
        memory_gbs=plan.memory_gbs,
        boot_volume_gbs=plan.boot_volume_gbs,
        create_ipv6=str(plan.create_ipv6).lower(),
    )


def _readme(plan: TerraformPlan) -> str:
    return f"""# {plan.project_name}

Terraform scaffold for a compliant Oracle Cloud Free Tier setup.

This project assumes the Oracle account was created manually by the owner and
that OCI CLI authentication is already configured on this machine.

## Run

```bash
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan
terraform apply
```

## Notes

- The default instance shape is `{plan.shape}`.
- Oracle may change Always Free availability by region and stock level.
- Review all generated resources before `terraform apply`.
"""
