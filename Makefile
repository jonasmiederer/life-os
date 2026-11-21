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

# --- P0-3: core, compose, smoke (owner: P0-3) ---
.PHONY: compose-up compose-down smoke smoke-local synthetic-datadir

compose-up:
	mkdir -p data
	docker compose up -d --build --wait

compose-down:
	docker compose down

# Runs inside the core container against the ntfy service. Needs `make compose-up` first.
smoke:
	docker compose exec -T core lifeos smoke --ntfy-url http://ntfy:8080

# Same check without Docker or ntfy.
smoke-local:
	python3 -m core smoke

# Builds a synthetic data dir for restore tests. Usage: make synthetic-datadir OUT=/some/dir
OUT ?= .lifeos/synthetic
synthetic-datadir:
	rm -rf $(OUT)
	python3 -m core synthetic-datadir --out $(OUT)

# --- P0-4: backup, restore --verify, reindex (owner: P0-4) ---
.PHONY: backup-test

# Needs restic on PATH. Uses a temp local repo and a synthetic data dir only.
backup-test:
	pytest tests/contract/test_backup.py tests/unit/core/test_reindex.py
