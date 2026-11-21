.PHONY: privacy-scan install-hooks

# Full local gate. Run before the first push and before each release tag.
privacy-scan:
	python3 scripts/privacy_scan.py --tree --history
	gitleaks dir . --config .gitleaks.toml --redact --no-banner
	gitleaks git . --config .gitleaks.toml --redact --no-banner

install-hooks:
	git config core.hooksPath scripts/hooks
