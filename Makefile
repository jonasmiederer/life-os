.PHONY: privacy-scan install-hooks lint types unit security fixtures evals-det

# Full local gate. Run before the first push and before each release tag.
privacy-scan:
	python3 scripts/privacy_scan.py --tree --history
	gitleaks dir . --config .gitleaks.toml --redact --no-banner
	gitleaks git . --config .gitleaks.toml --redact --no-banner

install-hooks:
	git config core.hooksPath scripts/hooks

# Local test gate, same commands as CI. Needs: pip install --group dev
lint:
	ruff check .
	ruff format --check .

types:
	mypy

unit:
	pytest -m "not security"

security:
	pytest -m security

# Generates synthetic samples at run time, then scans them. Negative tests: tests/security.
fixtures:
	python3 scripts/check_fixtures_clean.py tests/fixtures
	python3 scripts/check_permissions_lock.py

evals-det:
	python3 -m evals.det.run
