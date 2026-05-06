# Oracle Free Tier Helper

This directory contains a compliant Oracle Cloud Free Tier registration helper.
It follows the same broad shape as the main project: JSON config, CLI commands,
manual handoff points, and generated runtime output.

## Safety Boundary

The helper does not store or automate card numbers, CVV/CVC, CAPTCHA solving,
phone OTP, email OTP, or terms acceptance. Those steps must be completed by the
account owner in the browser.

Oracle states that only one Oracle Cloud Free Trial or Always Free account is
permitted per person, and signup information must be accurate. Review:

- https://www.oracle.com/cloud/free/faq/
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm

## Commands

Use a Python 3.11+ interpreter.

Browser mode needs Playwright:

```bash
pip install -r oracle_free/requirements.txt
python -m playwright install chromium
```

```bash
python -m oracle_free validate --config oracle_free/config.example.json
python -m oracle_free register-assistant --config oracle_free/config.example.json --dry-run
python -m oracle_free register-assistant --config oracle_free/config.example.json
python -m oracle_free init-terraform --config oracle_free/config.example.json --out-dir oracle_free/output/terraform
```

## Flow

1. Copy `config.example.json` and fill in your own account owner profile.
2. Run `validate` to check the config and see a redacted preview.
3. Run `register-assistant` to open the Oracle Free page.
4. Complete Oracle's manual verification steps yourself.
5. After the account is active, configure OCI CLI locally.
6. Run `init-terraform`, review the generated files, then run Terraform.

## Generated Terraform

The Terraform scaffold creates:

- a VCN
- an internet gateway
- route table and security list for SSH
- public subnet with optional IPv6
- an Ubuntu 22.04 ARM flex instance using `VM.Standard.A1.Flex`

Always review current Oracle Free Tier limits and regional capacity before
applying the Terraform plan.
