from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the Oracle helper config is unsafe or incomplete."""


BLOCKED_KEYS = {
    "captcha_solver",
    "captcha_api_key",
    "captcha_key",
    "sms_api_key",
    "otp",
    "otp_code",
    "verification_code",
    "card_number",
    "number",
    "cvv",
    "cvc",
    "security_code",
    "exp_month",
    "exp_year",
}


@dataclass
class ProfileConfig:
    email: str
    first_name: str
    last_name: str
    country: str = "US"
    home_region: str = "us-ashburn-1"
    cloud_account_name: str = ""
    phone_country_code: str = ""
    phone_hint: str = ""


@dataclass
class OciConfig:
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


@dataclass
class BrowserConfig:
    headless: bool = False
    slow_mo_ms: int = 80
    timeout_ms: int = 90000


@dataclass
class OracleFreeConfig:
    profile: ProfileConfig
    oci: OciConfig
    browser: BrowserConfig = field(default_factory=BrowserConfig)

    def to_safe_dict(self) -> dict[str, Any]:
        data = asdict(self)
        profile = data["profile"]
        profile["email"] = _redact_email(profile.get("email", ""))
        profile["first_name"] = _redact_word(profile.get("first_name", ""))
        profile["last_name"] = _redact_word(profile.get("last_name", ""))
        if profile.get("phone_hint"):
            profile["phone_hint"] = _redact_phone(profile["phone_hint"])
        data["oci"]["ssh_public_key"] = _redact_ssh_public_key(data["oci"].get("ssh_public_key", ""))
        return data


def load_config(path: str | Path) -> OracleFreeConfig:
    raw_path = Path(path)
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {raw_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("config root must be a JSON object")

    blocked = sorted(_find_blocked_keys(data))
    if blocked:
        raise ConfigError(
            "unsafe config keys are not allowed because Oracle verification "
            f"must stay manual: {', '.join(blocked)}"
        )

    try:
        profile = ProfileConfig(**_filter(ProfileConfig, data.get("profile") or {}))
        oci = OciConfig(**_filter(OciConfig, data.get("oci") or {}))
        browser = BrowserConfig(**_filter(BrowserConfig, data.get("browser") or {}))
    except TypeError as exc:
        raise ConfigError(f"missing or invalid config field: {exc}") from exc

    _validate_profile(profile)
    _validate_oci(oci)
    return OracleFreeConfig(profile=profile, oci=oci, browser=browser)


def _filter(cls: type, raw: dict[str, Any]) -> dict[str, Any]:
    allowed = set(cls.__dataclass_fields__.keys())
    return {k: v for k, v in raw.items() if k in allowed}


def _find_blocked_keys(value: Any, prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            key_lc = str(key).lower()
            path = f"{prefix}.{key}" if prefix else str(key)
            if key_lc in BLOCKED_KEYS or key_lc.endswith("_otp"):
                found.add(path)
            found.update(_find_blocked_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(_find_blocked_keys(child, f"{prefix}[{index}]"))
    return found


def _validate_profile(profile: ProfileConfig) -> None:
    missing = [
        name
        for name in ("email", "first_name", "last_name", "country", "home_region")
        if not str(getattr(profile, name, "")).strip()
    ]
    if missing:
        raise ConfigError(f"profile is missing required fields: {', '.join(missing)}")
    if "@" not in profile.email:
        raise ConfigError("profile.email must be a valid email address")


def _validate_oci(oci: OciConfig) -> None:
    missing = [
        name
        for name in ("region", "compartment_ocid", "ssh_public_key")
        if not str(getattr(oci, name, "")).strip()
    ]
    if missing:
        raise ConfigError(f"oci is missing required fields: {', '.join(missing)}")
    if not oci.compartment_ocid.startswith("ocid1."):
        raise ConfigError("oci.compartment_ocid must look like an OCI OCID")
    if not (
        oci.ssh_public_key.startswith("ssh-rsa ")
        or oci.ssh_public_key.startswith("ssh-ed25519 ")
        or oci.ssh_public_key.startswith("ecdsa-sha2-")
    ):
        raise ConfigError("oci.ssh_public_key must be an SSH public key")
    if oci.ocpus <= 0:
        raise ConfigError("oci.ocpus must be greater than 0")
    if oci.memory_gbs <= 0:
        raise ConfigError("oci.memory_gbs must be greater than 0")


def _redact_email(value: str) -> str:
    if "@" not in value:
        return _redact_word(value)
    local, domain = value.split("@", 1)
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def _redact_word(value: str) -> str:
    if not value:
        return ""
    return f"{value[0]}***"


def _redact_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def _redact_ssh_public_key(value: str) -> str:
    parts = value.split()
    if len(parts) < 2:
        return "***"
    key_body = parts[1]
    preview = key_body[:16] + "***" if len(key_body) > 16 else "***"
    return f"{parts[0]} {preview}"
