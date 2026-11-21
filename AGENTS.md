# AGENTS.md

Rules for every agent and every human who changes this repo.

## Privacy (absolute)

This repository is **public**. Git history is permanent and forks keep copies.

Never put any of these into a file, a commit message, a branch name, an issue, a PR, a comment, a log, a test or a fixture:
- real names, addresses, email addresses, phone numbers, domains of the owner
- account numbers, IBANs, tax ids, contract or policy numbers
- the names of the owner's banks, brokers, agencies, providers or hosts
- home paths (`/Users/<name>`, `/home/<name>`), tokens, keys, OAuth client ids
- text, scans or photos of real letters or mails

Use placeholders and reserved values: `example.com`, `Max Mustermann`, `Musterstrasse`, IBANs with check digits `00`.
When unsure, leave it out and ask.

Files under `docs/` and `tests/fixtures/` must contain the line `synthetic: true` or be listed in `.privacy-allow`.

## Rules

- Never use `--no-verify`, never unset `core.hooksPath`, never edit hooks to skip a check.
- Run `make privacy-scan` before pushing. Fix findings. Do not allowlist a finding to make it pass.
- Commit as the configured repo identity (`git config user.email`). The pre-push hook rejects any other identity.
- Do not paste real data into issues, PRs, logs or CI output. Use `lifeos report --dry-run` output only.
- Working directory is this repo only. Do not read the owner's home directory or private folders.
- Do not edit high-risk paths (see `.github/CODEOWNERS`) unless the issue says so. They need owner review.
- No `pull_request_target`. Pin GitHub Actions by full commit SHA. Workflows start with `permissions: {}`.
