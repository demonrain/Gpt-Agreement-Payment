from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .register_assistant import print_dry_run, run_browser_assistant
from .terraform import TerraformPlan, write_terraform_project


DEFAULT_CONFIG = Path("oracle_free/config.example.json")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            cfg = load_config(args.config)
            print(json.dumps(cfg.to_safe_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "register-assistant":
            cfg = load_config(args.config)
            if args.dry_run:
                print_dry_run(cfg)
                return 0
            return run_browser_assistant(cfg)
        if args.command == "init-terraform":
            cfg = load_config(args.config)
            plan = TerraformPlan.from_oci_config(cfg.oci, project_name=args.project_name)
            files = write_terraform_project(args.out_dir, plan)
            print("Wrote Terraform project:")
            for path in files:
                print(f"- {path}")
            return 0
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"runtime error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oracle-free",
        description="Compliant Oracle Cloud Free Tier registration helper and OCI bootstrap scaffold.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate config and print a redacted view")
    validate.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to oracle_free config JSON")

    assistant = sub.add_parser(
        "register-assistant",
        help="open Oracle Free Tier signup and pause at manual verification steps",
    )
    assistant.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to oracle_free config JSON")
    assistant.add_argument(
        "--dry-run",
        action="store_true",
        help="print the planned browser actions without opening a browser",
    )

    tf = sub.add_parser("init-terraform", help="write an OCI Always Free Terraform scaffold")
    tf.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to oracle_free config JSON")
    tf.add_argument("--out-dir", default="oracle_free/output/terraform", help="directory for generated Terraform")
    tf.add_argument("--project-name", default="oracle-free", help="name written into generated docs")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
