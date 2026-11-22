<!-- synthetic: true -->
# Factory dry run (owner checklist)

Workflow: `.github/workflows/factory.yml`. It is **off** until step 7. It is not a required check.
Do the owner steps first. Nothing here needs real data. Use synthetic text only.

## Owner steps (the agent cannot do these)

1. **GitHub App.** Settings, Developer settings, new App. Repository permissions: Contents write,
   Pull requests write. Nothing else. Install it on this repo only. No webhook.
2. **Environments** (Settings, Environments). Both: deployment branches = `main` only.
   - `factory-agent`: secret `KIRO_API_KEY` (a Kiro key made only for the factory, not the one the gateway uses).
   - `factory-publish`: secrets `APP_ID`, `APP_PRIVATE_KEY`. No Kiro key here.
   Do not put these as repo-level secrets.
3. **Labels.** Create `agent:spec`, `agent:build`, `agent:stop`, `idea`, `dep-change`.
4. **Kiro spend cap.** Set a hard limit in the Kiro account for the factory key, before the first run.
5. **Actions settings** (Settings, Actions, General): approval for all outside collaborators;
   workflow permissions = read only; "Allow GitHub Actions to create and approve pull requests" off.
6. **Ruleset on `main`:** when the App opens PRs, set required approvals to 1 with CODEOWNERS (design 4.5).
7. **Switch on.** Settings, Variables, add repo variable `FACTORY_ENABLED` = `true`.
   Anything else (or unset) means no run. Set it to `false` to turn the factory off.

## Dry run

Use a toy issue with synthetic text, for example: title `Add a hello helper`, body
`Add function hello(name) in core/hello.py that returns "Hello, <name>". Test it.`

1. Open the issue as the owner. Add label `agent:build`.
2. Actions tab: `factory` starts. `gate` prints `start=true`. `agent` runs and uploads `factory-patch`.
3. `publish` applies the patch, runs the privacy scan, pushes `factory/issue-<n>-<run>` and opens a PR.
4. CI runs on the PR. Review it. Merge or close it yourself. The factory never merges.
5. **Negative test A (non-owner).** Not needed live: `tests/unit/test_factory_guard.py` covers it
   (issue from another account, label from another account, fork, pull request).
   Optional live check: let a second account open an issue and have you label it. `gate` must print
   `start=false` and `reason=issue author is not the owner`.
6. **Stop label test.** Open a second toy issue, add `agent:build`, and while `agent` is running add
   `agent:stop`. Expected: the running `factory` run is cancelled. Then remove `agent:stop`, add
   `agent:build` again: the guard still refuses while `agent:stop` is present.
7. Check the Kiro usage page against the spend cap. Delete the toy PRs and issues.

## What to check in the first run

- `kiro-cli` accepts `--agent factory-actor` and `--trust-tools=fs_read,fs_write` on the runner.
  Not verified on a runner yet. The pinned version is 3.5.0 (checksum in the workflow env).
- The `toolsSettings` paths in `factory/agents/actor.json` are honored. Not verified. The patch
  gate (`scripts/factory_guard.py patch`) is the real control: it rejects paths outside
  `core/`, `helpers/`, `tests/`, `docs/`, binaries, symlinks and more than 400 changed lines.
- The agent job has no web block. Hosted runners cannot block egress. The tool allowlist is the limit.
- Agent logs (`agent.jsonl`) are not uploaded. Only the patch is, for 1 day.
