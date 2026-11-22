<!-- synthetic: true -->
# Factory dry run (owner checklist)

Workflow: `.github/workflows/factory.yml`. It is **off** until step 8. It is not a required check.
Do the owner steps first. Nothing here needs real data. Use synthetic text only.

## Owner steps (the agent cannot do these)

1. **GitHub App.** Settings, Developer settings, new App. Repository permissions: Contents write,
   Pull requests write. Nothing else. Install it on this repo only. No webhook.
2. **Environments** (Settings, Environments). Both: deployment branches = `main` only.
   - `factory-agent`: secret `KIRO_API_KEY` (a Kiro key made only for the factory, not the one the gateway uses).
   - `factory-publish`: secrets `APP_ID`, `APP_PRIVATE_KEY`. No Kiro key here.
   Do not put these as repo-level secrets.
   **Add yourself (the owner) as required reviewer on both environments.** "main only" does not
   limit who can run. The reviewer click puts a human in front of every secret release. Approve
   a run only after you see the issue is your own toy issue.
3. **Labels.** Create `agent:spec`, `agent:build`, `agent:stop`, `idea`, `dep-change`.
4. **Kiro spend cap.** Set a hard limit in the Kiro account for the factory key, before the first run.
5. **Actions settings** (Settings, Actions, General): approval for all outside collaborators;
   workflow permissions = read only; "Allow GitHub Actions to create and approve pull requests" off.
6. **CI on agent PRs.** The App opens the PR, so CI starts without the outside-collaborator
   approval, and a patch can add code or tests that CI then runs (for example a conftest). Keep it safe:
   no repo-level secrets, no `pull_request` job uses an environment, default token read-only (step 5).
   The CI jobs only need the read-only token. Check this once in Settings, Secrets. Optional: require CI
   approval for branches named `factory/`.
7. **Ruleset on `main`:** when the App opens PRs, set required approvals to 1 with CODEOWNERS (design 4.5).
8. **Switch on.** Settings, Variables, add repo variable `FACTORY_ENABLED` = `true`.
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
  gate (`scripts/factory_guard.py patch`) is the real control: only `core/`, `helpers/`, `tests/`,
  `docs/` paths, at most 400 changed lines.
- The agent job has no web block. Hosted runners cannot block egress. The tool allowlist is the limit.
- Kill switch: `FACTORY_ENABLED=false` is read at the start of each job. Setting it while the
  agent job runs does not stop that job (up to 30 min of spend). It stops `publish`. To stop a
  running agent, add `agent:stop`: it cancels the run. Any other label event on the same issue
  queues behind the running job and can replace a waiting run. Also revoke or cap the Kiro key.
- Patch gate: paths, modes and sizes come from `git diff --cached --no-renames --raw -z` and
  `--numstat -z` after `git apply --index`, not from reading diff headers. It rejects renames,
  non-`100644` modes, symlinks, submodules, binaries, no paths, and a diff header count that differs from
  the path count. It also rejects `core/gateway/`, `tests/security/` and `evals/baselines/`.
- The actor can read only inside the workspace (`fs_read.allowedPaths ./**`, not verified on a
  runner). Publish scans the patch with gitleaks and `privacy_scan.py --staged`, which has a Kiro
  key rule. Use a short-lived key with a spend cap.
- CODEOWNERS should cover `core/gateway`, `tests/security` and `docs/factory-dry-run.md`. Check it.
- Agent logs (`agent.jsonl`) are not uploaded. Only the patch is, for 1 day.
