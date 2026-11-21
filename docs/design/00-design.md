<!-- synthetic: true -->
# life-os: consolidated design (decision record)

Status: revision 2 for owner approval, 2026-11-21. Design only, no code. Revision 2 (section 10) applies the owner's changes: Markdown store, local data git repo, Docker, NUC host, EU cloud AI, no Paperless-ngx, mail-in.
Writer: merge item. This file is the decision record. Where it conflicts with another design file, this file wins. The other files stay as detail and are not edited. **This file supersedes the earlier detail files wherever they differ**, in particular on storage (SQLite, Paperless-ngx), local-only models, launchd/Mac hosting and mail-in timing.

Earlier detail files (research, architecture, data access, factory, reviews) are kept outside this repository. Cross-references such as "02 §x" or "R1-5" point into them and cannot be followed from here. This file is meant to stand alone.

Convention: "(believed)" means a statement from the reviewer's or writer's knowledge, not from a fetched source. Verify before relying on it. All such items are collected in section 9.

---

## 1. Summary (3-minute read)

**What life-os is.** A private assistant for one person (the owner). It reads your paper and PDF post, finds deadlines, answers questions about your documents, and later tracks contracts and your finances. Your data lives in plain files on your own machine (target: a NUC at home). It never pays, orders or sends anything on its own. It is for personal use only. That is a hard rule, other household members included.

**What it does first (MVP).** You photograph a letter, or forward a mail to your ingest address. A cloud vision model in the EU reads it (German OCR). A local fallback exists. It proposes type, sender, dates and amounts as a draft note. You confirm them next to the page image. Confirmed deadlines get reminders on your phone. You can ask "when does my gym contract end?" and get an answer with a citation.

**Where the data lives.** Markdown files are the only source of truth: originals in `files/`, full text in `raw/`, a short summary with strict frontmatter in `notes/`. No app database. Search is qmd, whose index can be rebuilt any time. `notes/` and `raw/` sit in a local git repo that has no remote. restic backs up the whole data dir.

**Helpers (small specialists on one shared core):**

| Helper | When | Job |
|---|---|---|
| Document (letters, forwarded mail) | Phase 1 | Letter or mail to confirmed facts, deadlines, Q&A |
| Daily brief, Ops | Phase 1 | One morning digest. System health. |
| Contract | Phase 2 | Contracts, notice dates, cancellation letter as PDF (you send it) |
| Financial | Phase 3 | Read-only. Bank and broker file import, spend view, tax worksheet (prepare only) |
| Mail triage (full inbox), Health, Housing, Vehicle, others | Phase 4 | Only if you want them |

**How it stays safe (six rules).**
1. Data stays at home. Only the model gateway talks to the cloud, only to an EU provider with a contract and no training on your data, and only for classes you allow. Each class has a switch (cloud, local only, blocked). Sending a letter to a cloud model is a disclosure to a processor, and the design treats it that way.
2. Text from letters and mail is untrusted. A model that reads it has no tool with a side effect. Model output never triggers an action. Only typed, validated fields move on.
3. No tool for payments, orders or sending exists in code.
4. You confirm every deadline, amount and payee. No auto-confirm in v1.
5. Logs hold ids and numbers, never content. A test plants fake secrets and fails if they appear anywhere.
6. Code repo (GitHub) and data repo (local, no remote) are strictly separate. A test fails if the data repo ever has a remote.

**How the factory works.** A public GitHub repo that holds code, synthetic fixtures and design text only. You write an idea (an issue) or you review. An agent writes a spec PR, you approve, an agent writes a build PR with tests first. CI must pass. You merge by hand. Agents never hold a write token, never merge, and cannot edit CI or permission files without you. Nothing reaches your machine until you tag a release and run `lifeos update`. In v1 bug reports are manual: the runtime prints a content-free fingerprint and you paste it into an idea issue.

**What you must do soon.** Decide the items in section 6 marked "blocks Phase 0 or 1": cloud AI provider and per-class switches (D4), host and NUC hardware (D1, D5), ingest mailbox provider (D19), backup target (D15). Then run the week-1 spike: cloud OCR against the local fallback on 30 of your own letters.

**Biggest risks.** (a) OCR and extraction quality on German phone photos is unknown. The spike measures it. (b) Cloud processing is a real privacy trade-off. It needs the provider contract and your per-class choices. (c) Files as the only store mean no transactions. A bad write or a hand edit can break a note. Schema validation, git history and backups cover that. (d) The mail-in watcher is the first stored mailbox credential, and the model gateway holds the cloud credential. Container limits in 2.14 are required. (e) A host that sleeps or reboots delays reminders. "No morning brief by 09:00" means "system down". (f) Several legal, platform and provider statements are unverified (section 9).

---

## 2. Final architecture

### 2.1 Shape

One `core` service, a few helper modules, one data directory outside the repo. Helpers never import each other and never call each other. They talk to core only. Hand-offs between helpers are core records (a note, a deadline, a review item), never free text.

v1 is deliberately simple (see section 7). **Docker Compose from day one** (R2-3). No launchd, no Mac-only service. v1 may run on the Mac under Docker. The target is an Intel NUC at home as the data layer, reached over VPN. Python 3.12 or newer (assumed, not verified). Helpers are Python modules run by core's job runner, not separate processes or MCP servers. The containers are split by trust, not by helper (2.11).

### 2.2 Core services (v1 set)

Details in 02 §3. Changes from 02 and from revision 1 are marked.

| Service | v1 design | Change |
|---|---|---|
| Document store | **Files only** (2.12). `files/` originals, `raw/` full text, `notes/` summary plus frontmatter. No app SQLite. No Paperless-ngx. | Rev 2: replaces Paperless client and SQLite facts |
| Knowledge base | qmd indexes `notes/`, `raw/` and the owner's own `.md` notes. Its SQLite index is a rebuildable cache (`lifeos reindex`). Citations (note, page, snippet) on every answer. Query carries a class ceiling that the gateway enforces. | Rev 2: replaces FTS5 |
| Deadlines | Read from note frontmatter. Computed dates come from a rules module in plain code (2.8). A model never computes a date that drives a reminder. | Rev 2: source is frontmatter, no table |
| Notifications | Self-hosted ntfy, generic push text, details only in the local web UI. Reminder policy in 2.9. Ack, snooze and done are written back to the note's frontmatter. | Write-back added |
| Identity and permissions | One owner. `permissions.yml` per helper lists agents with role and tools. A test-time check rejects a reader with an act tool. No runtime broker in v1. | Same |
| Audit log | Append-only JSONL, one line per egress or state change, ids and hashes only. No hash chain. | Rev 2: JSONL file, adds cloud calls and reminder acks |
| Ingestion | Quarantine, checks, local OCR, class routing, optional cloud extraction, validate, review queue, write notes (2.7, 2.13). Sources: upload page, drop folder, mail-in (2.14). | Rev 2: cloud step and mail-in |
| Model gateway | The only code that talks to a model. Routes by data class and per-class switch, writes an audit line, masks where text allows. One container, the only holder of the cloud credential (2.13). | Rev 2: cloud is on, behind switches |
| Scheduler | One loop. No job table: reminder state is derived from frontmatter plus the audit log. Catch-up after downtime from the last audit "run" line. | Rev 2: no DB |
| Config and secrets | `config.toml`, `policy.toml`, schema-validated, fail closed. Secrets are Docker secrets or env files with mode 600, never in the data repo or code repo. | Rev 2: credentials now exist (2.11) |

### 2.3 Data classes and model policy

Class table is from 02a §4.3. Owner identity data has its own row, and masking happens at the gateway, not at storage (R1-7). Revision 2 replaces "cloud off" with a **per-class switch** in `policy.toml`.

| Class | Examples | Local store | Cloud switch default |
|---|---|---|---|
| C0 Secrets | passwords, PINs, TANs, tokens | Never stored by life-os | `block` |
| C1 Identity | ID scans, passport, standalone identity documents | Local files | `block` (local OCR only) |
| C2 Health | medical letters, Krankenkasse | Local files | `block` (local OCR only, owner fills fields) |
| C3 Bank and broker | transactions, depot, tax reports | Local | `block` in v1 (no such imports before Phase 3). Decide at Phase 3 (D4) |
| C4 Tax and employer | Steuerbescheid, payslips | Local | `allow` (needed for the MVP). Owner confirms in D4 |
| C5 Contracts, general letters | rent, phone, energy, non-health insurance, invoices | Local | `allow` |
| C6 Public or synthetic | fixtures, public forms | Local | `allow` |
| Owner's own notes (`own/`) | free `.md` notes | Local, indexed | `block` unless the note says `cloud: ok` |

Switch values: `allow` (full text or image may go to the provider), `redacted` (gateway masks IBAN, Steuer-ID, Steuernummer, ID numbers in text before sending; not possible for images), `local` (stays on the host, local tools only), `block` (nothing is processed beyond local OCR and the file is stored).

Rules:
- Unclassified means the most restrictive class **after** the intake routing in 2.13 has run. Derived data inherits the highest class of its sources. Re-class upward by code, downward only by the owner.
- Class is derived from the note `type` through a table in code. It is not a frontmatter field.
- Incidental identifiers inside an allowed letter (your name, address, IBAN, Steuernummer) go to the provider with the letter. The text-only `redacted` mode can mask the rest. This is a consequence of cloud OCR, and the owner accepts it in D4.
- Redaction of third-party names is NER and unreliable. It is labelled best effort (R1-16).
- Retrieval for Q&A removes notes above the allowed class before the prompt is built. A blocked-class match is shown as a local link only.
- If a class is `block` or `local` and no local tool can do the job, the job fails with a typed error and the note is created as a draft for manual entry. There is no silent fallback to cloud.
- Local fallback: `ocrmypdf` with Tesseract (German) for text. No local LLM in v1.

### 2.4 Orchestration

- **Deterministic router, no LLM supervisor.** A request maps to one helper by UI section, slash command or keyword. An optional local classifier may return only a helper name from a fixed list and has no tools.
- **Readers and actors.** A reader agent sees untrusted text and has only local read tools plus "write typed proposal". An actor never sees raw untrusted text. Documented per agent in `permissions.yml` (section 2.6).
- **v1 uses structured-output model calls, not agent loops.** The MVP needs "extract these fields as JSON", not tool-using agents. No agent framework in v1. The `AgentRunner` interface and the Pydantic AI spike are cut; revisit when a helper needs a real tool loop (Phase 3 or later).
- **MCP:** not used as an internal layer in v1. Third-party MCP servers are not used by default.
- Triggers: event (document arrives, review confirmed), timer (reminders, brief, backup, health), owner (UI question).

### 2.5 Helper catalog

Full tables in 02 §4. Summary with v1 status:

| Helper | Phase | Roles | Act tools | Notes |
|---|---|---|---|---|
| Document | 1 | reader (extractor, Q&A) | none | Calls the model only through the gateway. Class switches apply. Takes uploads and forwarded mail (2.14) |
| Daily brief | 1 | code view | none | Model may only phrase, with the push-text ceiling |
| Ops | 1 | code only | none | Backup age, disk, queue, model server, "brief missing" |
| Contract | 2 | reader; actor (letter drafter from validated fields only) | `render_cancellation_letter` writes a PDF to an outbox. No send tool. | A view on the document store plus a `contracts` table |
| Subscriptions, Warranty | 2 | reader | none | Subscriptions starts from the contracts list |
| Financial | 3 | one folder, three agents: `import` (code, no model, no network), `sync` (optional, not in v1-v2), `analyst` (reader) | none | Read only. No order or payment endpoint exists. Advice carries "not investment advice" |
| Mail-in (ingest) | 1 | code only, no model | none | Own container. Fetches forwarded `.eml` from the ingest mailbox, hands files to quarantine (2.14) |
| Mail triage (full inbox) | 4 | reader only | none | Highest injection exposure. No send credentials in the process |
| Health, Housing, Vehicle, Tariff watch, Developer admin | 4 | reader | none | Health: class switch stays `block` or local only |
| People memory | not planned | | | |

### 2.6 `permissions.yml` and protection of the permission files

Format (R1-3): one file per helper folder.

```yaml
helper: financial
agents:
  - name: import
    role: actor        # code only, no model
    reads: [C3]
    tools: [{name: parse_file, kind: read}]
    network: none
  - name: analyst
    role: reader
    reads: [C3, C4]
    tools: [{name: query_transactions, kind: read}, {name: write_note, kind: write_local}]
```

The patch gate keys on the folder (`helper:financial`). Roles are per agent inside the file. Financial stays one folder (R1-3 option b).

Protection (R1-4):
- `helpers/*/permissions.yml`, `config/policy.toml` defaults and `tests/security/permissions.lock` are **high-risk** in CODEOWNERS and the patch gate.
- Contract tests compare each `permissions.yml` to the committed `permissions.lock`. Only a high-risk PR (owner reads it) may change the lock. An agent widening its own rights therefore fails CI or lands as a labelled high-risk PR.
- `core/permissions/**`, `.github/**`, `CODEOWNERS`, `AGENTS.md`, `evals/baselines/**` stay high-risk as in 03 §6.1.

### 2.7 Ingestion and the review UI

**Paths (R1-11, revised).** (1) Upload page: plain server-rendered HTML form with `<input type="file" accept="image/*,application/pdf" capture>`, reached over the VPN with HTTPS, plus a "nur lokal" checkbox. No PWA or Web Share Target (not supported on iOS Safari, believed). (2) Drop folder on the host. (3) **Mail-in (Phase 1):** you forward a mail as `.eml` attachment to the ingest address (2.14). (4) Scanner app to a synced folder is optional. Chat bots are not used for documents.

**Grouping and backlog (R1-20).** One upload form submission = one document, with several photos as pages, in the owner's order. Hash dedupe only handles identical files. Bulk import of the old backlog runs in `historic` mode: it extracts facts but creates no reminders for past dates and asks once for each deadline still in the future.

**Pipeline.** quarantine, checks (type, size, no scripts), local OCR with Tesseract (always, cheap), class routing (2.13), then per the class switch: cloud vision or text extraction with a schema, or stop at local text. Then validate the typed fields, write `files/` + `raw/` + a `notes/` draft, review queue. Every step logs ids only. A file that fails schema validation goes to `review/` with a reason, never to reminders.

**Document types for the MVP (R1-20):**

| `doc_type` | Fields | Creates deadline |
|---|---|---|
| `steuerbescheid` | Bescheiddatum, Bekanntgabe/received date, Steuerjahr, Nachzahlung or Erstattung amount, payment due date | Einspruch, payment |
| `rechnung` | sender, invoice no., amount, due date, IBAN | payment |
| `mahnung` | sender, reference, amount, new due date | payment |
| `kuendigung_vertrag` | counterparty, contract no., term end, notice period, price | cancellation (computed) |
| `versicherung` | insurer, policy no., renewal date, price | renewal, cancellation |
| `sonstiges` | sender, date, free-text summary | none (owner may add) |

Health, rent and bank statements are filed as `sonstiges` in the MVP. The routing in 2.13 still assigns class C2 or C3 from local text and `type` hints, so they do not reach a cloud model when the switch says `block`.

**Review UI (R1-21).** One small server-rendered web app (Python), German UI text. Login: one password plus session timeout, over the VPN. Four screens: (1) Upload, (2) Review (page image beside each value, confirm or edit), (3) Deadlines (confirm, done, snooze), (4) Ask (question, plain-text answer with local citation links). Output is rendered as plain text only. CSP `default-src 'self'`. No remote images or external links from model output (R1-13).

### 2.8 Deadline rules (MVP)

A rules table in code, one row per rule: rule id, formula, statute link, "owner verified on <date>" (R1-17). A rule that is not marked verified shows "Rule not verified" in the review UI. Statutes are fetched before Phase 2; for the MVP the owner verifies these three:

| Kind | Formula (believed, to verify) | Inputs |
|---|---|---|
| Einspruch gegen Steuerbescheid | One month after Bekanntgabe (§355 AO). If sent by post, Bekanntgabe is the third day after posting (§122 AO). Deadline on a weekend or holiday moves to the next working day (§108 AO). | `received_at` (owner confirms at upload), Bescheiddatum |
| Zahlungsfrist (Rechnung, Mahnung) | Date stated in the letter. If a period ("14 Tage") is stated, count from `received_at` or invoice date as the letter says. | stated date or period |
| Kündigung | Term end minus notice period. Notice must usually arrive before the date (Zugang), so the lead time adds a safety margin (default 7 days). | term end, notice period, notice rule |

Nebenkostenabrechnung (12 months) is **not** an Widerspruch. It is an Einwendungsfrist for the tenant (§556 Abs. 3 BGB, believed). It belongs to the Housing helper in Phase 4.

Other rules:
- `received_at` is asked at upload (default today). The owner can correct it.
- Holidays: the Python `holidays` library, state set in config (federal state). Not verified for the owner's state.
- Rules module has unit tests and fault injection (DoR item 6, section 4.2). A deadline from a model starts `proposed`. Only `confirmed` deadlines drive reminders.
- Past deadlines found at import are shown as "missed", never silently dropped.

### 2.9 Reminder policy (R1-23)

Starting values, configurable:

| Kind | Reminder lead times | Repeat |
|---|---|---|
| Einspruch | 14, 7, 3, 1 days before, and on the day | Daily until acknowledged from 3 days before |
| Zahlung | 7, 3, 1 days before, on the day | Daily until acknowledged from 1 day before |
| Kündigung | 90, 30, 14, 7 days before, and the margin date | Daily from 7 days before |
| Other | 7 days, 1 day | none |

- Actions on a reminder: done, snooze (1 day, 3 days, until a date), dismiss with a reason.
- Quiet hours (default 22:00 to 07:00). Exception: an item due within 24 hours rings through.
- Unacknowledged reminders escalate: push, then push with high priority after 4 hours.
- Reminders missed while the machine slept are sent on the next start (catch-up) with "verspätet".
- A reminder counts as delivered only after ntfy confirms.
- **Dead-man rule (R1-1):** the Daily brief is sent at 09:00. If the owner has not seen it by 09:00, treat the system as down: check the host (NUC or Mac). Optional later: an external heartbeat service that alerts when the machine stops pinging. Not in v1.

### 2.10 Runtime contract (one version, reconciled with 03)

03 §12 lists nine assumptions. This is the final contract. Field-level detail stays in 02 §8, with the changes below applied.

| # | Item | Final rule |
|---|---|---|
| 1 | Log schema | JSON lines, versioned, event codes from a registry, only registered typed fields (ids, enums, numbers, hashes). No free-text logging API. No exception messages. 02 §8.1. |
| 2 | Log scope | The contract covers more than the app log (R1-12): containers log JSON lines to stdout only, with the Docker `json-file` driver and size limits; Python tracebacks go through the same filter; third-party log levels (ntfy, qmd, gateway SDK) at warn; no crash-report upload. On a Mac host add `.metadata_never_index` and a Time Machine exclusion for the data dir. The canary test greps all of these. |
| 3 | Error report (v1) | Versioned schema: version, helper, exception class (allowlisted), up to 3 in-repo `file:function` frames, fingerprint, `count`, first and last seen. The field is `count` everywhere (`count_hint` is dropped, R1-5). |
| 4 | Fingerprint | `sha256(exception_class | frame1 | frame2 | frame3 | helper)`, 12 hex chars, one shared function in `core/runtime/`. |
| 5 | `external_only` reports | Reports with zero in-repo frames are marked `external_only`, are never auto-sent, and never reach the schema workflow (R1-5). |
| 6 | Reporter | **v1: `lifeos report --dry-run` only.** It prints the exact JSON. The owner pastes fingerprint and frames into an `idea` issue. No bot token, no schema workflow in v1 (R1-15). |
| 7 | Redaction layers | L1 by construction (registered fields), L2 pattern scrubber as defence in depth, L3 report allowlist, L4 canary tests. 02 §8.3. |
| 8 | Config | Defaults in code, `config.toml`, `policy.toml`, env for tests. Schema-validated, unknown key stops the service. Secrets only as references. 02 §8.4. |
| 9 | Data directory | One data dir outside the code repo, mounted into containers (2.12). Disk encryption: FileVault on the Mac, LUKS on the NUC (D3). Encrypted restic backups (2.11). No app-level encryption in v1. |
| 10 | Commands | `lifeos migrate`, `backup`, `restore --verify`, `update`, `rollback`, `smoke`, `health [--level live,ready,deep]`, `eval --local`, `report --dry-run`, `reindex` (rebuild qmd cache), `validate` (check every note against the schema, list rejects). |
| 11 | Health | Three levels as in 02 §8.6. The audit chain check is dropped. "Daily brief not sent" is a failed check. |
| 12 | Test hooks | `LIFEOS_ENV=test` (temp dir, fake clock, network deny, fixture-only guard), fake model with replay, canary support, permission contract suite, fault injection, deterministic seed. 02 §8.7. |
| 13 | Layout | One folder per helper, shared `core/`, `permissions.yml` per helper, plus `evals/extract/`. |
| 14 | Updater auth | Owner downloads the release bundle (compose file plus image tarballs) by hand and runs `lifeos update --from <file>`; the updater verifies the checksum and the signed tag. Image pull from a private registry needs a token and stays optional later. |
| 15 | Stack | Python 3.12 or newer (assumed). Docker Compose. |
| 16 | Local eval | `lifeos eval --local` prints scores to the terminal only. It runs real documents through the gateway, so it obeys the class switches. The factory never sees real-document scores unless the owner pastes them. |

### 2.11 Deployment, backup, network

- **Where it runs (R2-3):** Docker Compose, same files on every host. v1 may run on the owner's Mac (Docker Desktop or Colima, sleep disabled at night). **Target: an Intel NUC at home** as main storage and data layer, reached over a VPN. A cloud VM is no longer rejected, but the NUC is preferred because the data stays at home. Reminders go live only on an always-on host (Phase 1c).
- **Containers (target; v1 may merge `worker` into `core`):**

| Container | Holds | Network | Mounts |
|---|---|---|---|
| `core` (UI, scheduler, note writer, helpers) | UI password, ntfy token | Internal only. No internet | data dir read/write |
| `gateway` (model gateway) | **Cloud model credential** (invoke-only) | Outbound to the provider endpoint only | no data dir. Receives requests from `core` over the internal network |
| `worker` (OCR, PDF and image parsing) | nothing | none | `inbox/` read, `candidates/` write |
| `ingest` (IMAP watcher, 2.14) | **Ingest mailbox credential** | Outbound to the IMAP host and port only | `inbox/` write only |
| `search` (qmd) | nothing | none | data dir read, cache volume write |
| `ntfy`, `proxy` (TLS) | ntfy token | proxy: VPN interface only | none |

- **Boundary rules (replace "v1 holds no credentials"):** v1 now holds two outside credentials, the cloud model credential and the ingest mailbox credential. Each lives in one container only. `core` has no internet route. No container mounts the Docker socket. Containers run non-root, read-only root filesystem, `cap_drop: ALL`, with CPU and memory limits. Bank, broker and ELSTER credentials stay out of v1 and v2. FinTS or full-inbox IMAP gets its own container before it is added (gate for Phase 3 sync and Phase 4 mail triage).
- **Encryption (D3):** disk encryption of the host (FileVault on the Mac, LUKS on the NUC) plus restic-encrypted backups. LUKS needs an unlock after reboot. TPM auto-unlock may avoid that (believed, not verified). Without it, a reboot stops reminders until you unlock, and the dead-man rule catches it.
- **Backups (R2-2):** restic of the **whole data dir** (`files/`, `raw/`, `notes/`, `own/`, `audit/`, and the data git repo's `.git`). The qmd cache is excluded because it is rebuildable. Target is an owner decision (D15): a local disk, or an encrypted cloud bucket. Default: both, nightly local plus weekly offsite. restic encrypts client side. Backup key stored offline. Restore test in Phase 0 and twice a year. Backup age is a health check.
- **History (R2-2):** `notes/` and `raw/` (and `own/`) are a **local git repo with no remote**. `files/` and `audit/` stay out of git. `.gitignore` in the data dir lists them. Core commits after each write batch. Commit messages carry ids only. A guard fails when the data repo has any remote: `lifeos health` and every commit check `git remote` is empty and no `remote.*`, `url.*.pushInsteadOf` or push hooks exist, and a CI test does the same on a fixture data repo. Limit: git history and restic snapshots keep deleted content. Deleting a document for good means a history rewrite plus pruning backups (shortcut: manual procedure, document it before Phase 2).
- **Separation:** the code repo (GitHub) never contains the data dir. The data repo never has a remote. `fixtures-clean` and `secrets-scan` guard the code repo. The data dir path is never mounted into the factory's CI.
- **Network:** services listen on the internal Docker network. The proxy listens on the VPN interface only (WireGuard or Tailscale, owner chooses). No inbound port is open to the internet, and no inbound SMTP to the host: the ingest mailbox is hosted by a mail provider and fetched outbound. Outbound: gateway to the model provider, ingest to the IMAP host, ntfy upstream if the iOS setup needs it (R1-8, believed), and GitHub only for an optional `lifeos update` token.
- **Notifications (R1-8):** self-hosted ntfy. Away from home the phone needs the VPN to reach it. Push text is generic ("1 Frist wartet").

### 2.12 Markdown store (R2-1)

Markdown files are the single source of truth. No app SQLite. No two-way sync with any database. The qmd SQLite index is a rebuildable cache.

```
data/
  files/YYYY/<slug>.<ext>     originals (pdf, jpg, .eml). Not in git
  raw/<slug>.md               full extracted text, all pages. In git
  notes/<slug>.md             summary + strict frontmatter. In git
  own/**/*.md                 owner's own notes, indexed, no schema. In git
  review/                     rejected or invalid files plus <slug>.reason.json
  inbox/, candidates/         quarantine and worker output (transient)
  audit/YYYY-MM.jsonl         append-only audit log. Not in git
  .lifeos/schema.json         schema version for `lifeos migrate`
```

`<slug>` is `YYYY-MM-DD-<sender>-<type>-<8 hex of file sha256>`. The hash suffix gives duplicate detection by scanning names, so no DB is needed.

Note frontmatter (schema-validated, unknown keys rejected):

```yaml
---
type: steuerbescheid      # enum: steuerbescheid|rechnung|mahnung|kuendigung_vertrag|versicherung|sonstiges
from: "Finanzamt X"       # string, length and charset limited
date: 2026-11-03          # letter date, ISO
deadline: 2026-12-07      # ISO date or empty
deadline_kind: einspruch  # einspruch|zahlung|kuendigung|other|none
amount: 412.50            # decimal EUR or empty
status: draft             # draft|confirmed|done
snooze: 2026-11-25        # ISO date or empty. Reminders pause until then
source: upload            # upload|folder|mail
raw: raw/2026-11-03-finanzamt-x-steuerbescheid-ab12cd34.md
---
```

Rules:
- `raw/<slug>.md` has its own small frontmatter: `file` (path under `files/`), `sha256`, `pages`, `extractor` (`cloud` or `tesseract`), `model_id`. It links the note to the original. This is an addition to the owner's field list. The owner confirms it in review.
- Validation rejects: unknown keys, bad enum or date, `status: confirmed` with `deadline_kind` other than `none` but no `deadline`, a missing `raw` file, a slug that differs from the file name. Rejected files move to `review/` with a reason. Reminders and qmd ignore `review/`.
- Only core writes notes, under a file lock. It writes to a temp file, validates, then renames. Owner edits in an editor are allowed. They are validated on the next scan. A hand edit that breaks the schema goes to `review/`.
- Model-written text lives only in the note body and `from`. It is untrusted and rendered as plain text. Frontmatter values come from typed, validated fields.
- Reminder job: reads `notes/` frontmatter. Only `status: confirmed` with a `deadline` drives reminders. Ack, snooze and done are written back to the note (`snooze`, `status`) and logged to the audit JSONL. Shortcut: an acknowledgement has no own field. It is stored as `snooze` until the next lead time. Add an `acked` field only if the schema review asks for it.
- One deadline per note. A letter with two deadlines (for example Einspruch and payment) becomes linked notes with the same `raw`, one per deadline. Open question 11.
- Audit log: append-only JSONL, one file per month, ids and hashes only. Optional on Linux: `chattr +a` (believed).
- Search: qmd (https://github.com/tobi/qmd) indexes `notes/`, `raw/`, `own/`. `lifeos reindex` deletes and rebuilds its cache. Its features, runtime, licence and German quality are **not verified**. If it fails the spike, the fallback is a plain grep over the files (shortcut: slow but correct).
- Owner's own notes in the data dir are indexed. They are never read by the reminder job. Cloud switch for `own/` is `block` by default (2.3).

### 2.13 Model gateway and cloud AI (R2-4)

NUC holds the data. Inference uses cloud models. This replaces "local only, cloud off". Requirements for the provider (all **not verified**, check the contract text):
- EU region only. Example: AWS Bedrock in `eu-central-1`. Whether the needed vision model runs in that region, or only through cross-region routing, is unknown.
- No training on your data. No retention beyond what the contract says.
- A signed data processing agreement (DPA, Art. 28 DSGVO) is in place before the first real letter is sent.
- Invoke-only credential, a spend cap and a budget alert at the provider.

Gateway rules:
- **Backends (Rev 2.1).** The gateway has one interface and two possible backends: a direct provider (AWS Bedrock `eu-central-1`) and `kiro-cli` headless on the NUC. Chain: gateway (class switch, masking, audit) -> `kiro-cli` -> Kiro cloud service -> model. Every rule below applies to both. The switch can name a backend per class (D4).
- **Kiro reader agent.** Letter and mail calls run `kiro-cli` with agent config `reader`: no tools (no shell, no file write, no MCP, no web), fixed max turns, structured output that the gateway validates against the schema. Output that fails validation is dropped and the note stays a draft. Agent configs: `reader` (no tools, sees untrusted content) and `actor` (factory and helper agents with tools, never see raw letters or mail). The configs are high-risk paths (CODEOWNERS and the permission lock). A test starts `reader` with a planted injection letter and asserts zero tool calls. Kiro Crew's own gateway may run on the NUC for chats and helpers, but never as the untrusted-content reader.
- **Kiro container.** `kiro-cli` runs in the `gateway` container (or a sibling with the same limits). It holds the Kiro sign-in as the cloud credential and has no data dir mount. Egress goes to Kiro endpoints only (host list not verified).
- It is the only caller of any model. `core`, helpers and the factory never hold the credential.
- Each call carries `{doc_id, class, purpose}`. The gateway looks up the class switch in `policy.toml`, refuses on `block` or `local`, masks on `redacted`, and writes an audit line: time, doc id, class, provider, model id, bytes, result code. No content.
- **Read/act split stays.** A model call returns typed data (JSON against a schema) or plain text for display. Nothing in a model output triggers a tool, a send, a file move or a reminder. Core validates, then a human confirms.
- The gateway has no tools, no web access and no way to follow links. Prompts put the untrusted text in a marked data block.

Intake routing (before any cloud call), because the class is not known when a file arrives:
1. Local Tesseract text for every file.
2. A rule classifier in code (keywords such as Arzt, Diagnose, Krankenkasse; ID-document patterns; sender rules; upload "nur lokal"; mail tag `+local`) sets a provisional class. Nothing matched means C5.
3. The class switch decides. `allow`: cloud extraction. `block` or `local`: the note is a draft with local text and empty fields.
4. The owner can override the class upward at any time in the review UI.
Limit: a health letter without any keyword reaches the cloud. Mitigation: the "nur lokal" checkbox, the review step, and D21 (confirm class before every cloud call during the spike).

DSGVO and threat model updates (replace the "cloud off" statements in 02a §3 and §4):
- Sending letters to a cloud model is a **disclosure to a processor**. It needs the DPA, the EU region and a purpose limit. Letters contain third-party data (landlord, employer, doctor). Whether the household exemption still applies is unverified (section 9).
- An EU region does not remove the question of access by non-EU parent companies (believed). It is a residual risk the owner accepts or avoids by class switches.
- New threats and controls: prompt injection in a letter (read/act split, typed output); credential theft of the model key (invoke-only, spend cap, no key outside `gateway`); data in provider logs (contract, not verified); misclassification (rules plus owner override); cost abuse (cap and alert); parser exploits in PDFs and images (the `worker` container has no network).

### 2.14 Mail-in (R2-6)

You forward relevant mails to a dedicated address, for example `ingest@example.com`. This is the first stored mailbox credential. The mail provider is open (D19), and so is whether it supports plus-tags.

Rules:
- **Forward as attachment** (`.eml`, `message/rfc822`) so the original sender and date survive. Only `.eml` attachments are processed. The outer body is ignored. Other attachment types on the outer mail are dropped.
- **Sender check:** accept only if the outer mail passes SPF and DKIM and its envelope or From address is on an allowlist of your own addresses (D20). The watcher reads the `Authentication-Results` header of your own provider, not headers set by the sender. Everything else is moved to `Rejected` and an ntfy line says "1 Mail abgelehnt". No reply is sent, ever.
- The authenticity of the **inner** mail is not checked. Its text and attachments are untrusted data. It goes through the same pipeline as a letter: local OCR or text extraction, class routing, typed extraction, review.
- **Plus-tags** `ingest+tax@`, `ingest+contract@`, `ingest+local@` are routing hints only. A tag may suggest a `type` or force `local`. It can never lower a class, skip review or auto-confirm.
- Limits: mail size, MIME depth, attachment count and type allowlist, rate cap per day, dedupe by Message-ID plus file hash. HTML is never rendered and links are never fetched.
- Phase 1 includes forwarded letters and bills. Full inbox triage stays Phase 4.

What the `ingest` container must enforce:
- Holds only the ingest mailbox credential. That mailbox is a separate account with SMTP sending disabled if the provider allows it (not verified). The watcher code has no SMTP client and no send path, and a static test checks that.
- IMAP permissions used: read and move (to `Processed` or `Rejected`). No delete, no expunge, no flag changes beyond seen.
- Egress allowed to the IMAP host and port 993 only. No other route. Mounts `inbox/` write-only. It cannot read `notes/`, `raw/` or `files/`, and it cannot reach `gateway` or `core`.
- Non-root, read-only root, `cap_drop: ALL`, limits on memory and time. It parses MIME structure only and writes bytes to quarantine. It never executes or opens attachments. All parsing of PDFs and images happens in `worker`.
- Credential rotation is documented. A failed login raises an Ops alert, and the watcher never retries in a tight loop (account lock risk).

---

## 3. Data access per provider (short, from 02a)

Default rule: **v1 and v2 import bank and broker files. No bank, broker or ELSTER credentials stored.** The only outside credentials are the cloud model key and the ingest mailbox (2.11).

| Source | Method | Unattended | Status in this design | Legal or platform limit |
|---|---|---|---|---|
| Any bank | Owner downloads CSV or PDF statements, drops file | No | Phase 3 default | None beyond own-data use |
| FinTS banks | FinTS read-only | Only between TAN renewals (about 90 days, bank-specific) | Optional pilot after Phase 3, one bank, in a container. Needs a registered product ID from Deutsche Kreditwirtschaft (accepted for single-user use: not verified) | PIN lock risk. No write endpoints |
| A German direct bank's REST API | OAuth plus TAN session per sync | No | Not in v1-v2. Import first | Token has no read-only scope. Code must allow-list read endpoints only |
| A neo-broker | Official PDF/CSV exports through Document helper | No | Phase 3 | An unofficial client library uses a private API, may breach ToS, account-lock risk. Off by default, separate user |
| Aggregators (finAPI, Tink, GoCardless) | none | n/a | Not used | New GoCardless sign-ups closed. B2B terms. Cloud sees all data |
| Other brokers | Export files, one importer per format | No | Phase 3, per format | |
| ELSTER / ERiC | Prepare numbers and checklist. Owner enters and submits in ELSTER | No | Prepare only | ERiC needs developer registration, certificate, annual updates. No entitlement to an account |
| Mail-in (forward to ingest address) | IMAP fetch of one dedicated mailbox, read and move only | Yes | **Phase 1**, `.eml` forwarded by the owner, allowlist plus SPF/DKIM (2.14) | Provider terms and plus-tag support unverified. First stored mailbox credential |
| Mail (full inbox IMAP) | Read-only, app password or OAuth | Yes | Phase 4, not v1 (R1-9) | Biggest injection surface. Provider policies unverified |
| Calendar | CalDAV or ICS read. Write to a dedicated calendar after owner OK | Yes | **First supported method**, Phase 2 or later (R1-9) | Event text is untrusted |

Legal notes (not legal advice, 02a §3):
- **Investment advice (WpIG, KWG):** advice to others is regulated. A tool for your own money, never shared, is outside that. Condition: personal use only. Enforcement is technical: no trade or payment scope, advisory output with disclaimer.
- **Tax (StBerG):** handling your own tax is allowed. Same condition. Prepare-only keeps you as the one who submits.
- **DSGVO (revised):** the household exemption (Art. 2(2)(c)) may fit private use, but sending letters with third-party data to a cloud model is a disclosure to a processor. Revision 2 uses an EU region, a DPA, no-training terms and per-class switches (2.13). Health and identity classes stay local by default. Not legal advice and not verified.
- None of this was verified against statute or BaFin text (section 9).

---

## 4. Factory

Detail in 03. This section is the v1 version after the R1 cuts.

### 4.1 Repo layout

Public GitHub repo `life-os` (GitHub Free, rulesets enforced), monorepo. The repo holds code, synthetic fixtures and this design text only. No real data, ever:

```
core/ helpers/<name>/ docs/{design,specs,adr}/ tests/{unit,contract,security,fixtures,fixturegen}/
evals/{ocr,qa,extract,baselines}/ .github/{workflows,ISSUE_TEMPLATE,CODEOWNERS} AGENTS.md
```

- Helpers import only from `core/`. Test data lives only in `tests/fixtures/`. Runtime data never in the repo, and the data repo never has a remote (2.11).
- `tests/security/corpus/` holds hostile (injection) letters. It is high-risk in CODEOWNERS. Agent tool configuration denies file reads in that path; tests read it only as program input (R1-14). Limit: an agent can still run a test that prints it. Upgrade: generate the corpus at test time from `fixturegen` if this proves leaky.

### 4.2 CI

All workflows use `permissions: {}` at top, every action pinned to a full commit SHA, no `pull_request_target`, untrusted values passed through `env:` only.

**v1 required checks:** `lint`, `types`, `unit` (includes contract and permission-lock tests), `security-tests` (injection corpus, egress deny, canary), `fixtures-clean`, `secrets-scan`, `sast` (semgrep, bandit), `deps` (pip-audit only), `workflow-lint` (actionlint, zizmor, SHA check), `evals-det` (OCR and extraction on synthetic scans).

**Cut from v1 (R1-E):** `evals-llm` with 3 runs, CodeQL, dependency review, SBOM and attestation, licence check, advisory reviewer agent, Copilot fallback, bug bot and schema workflow, `factory-state` ledger branch.

**Definition of ready (reconciled, R1-6).** Which items are needed when:

| # | Item (03 §11) | Needed for |
|---|---|---|
| 1 | Fixture generator | Phase 0 |
| 2 | `fixtures-clean` with a known-bad sample | Phase 0 |
| 3 | Unit and contract tests for `core/` | Phase 0 (thin core), grows with Phase 1 |
| 4 | Security tests (injection corpus, canary, egress) | Phase 0 |
| 5 | Eval harness and first baselines | Phase 1a |
| 6 | Fault injection on the deadline engine | **Before reminders go live** (Phase 1c) |
| 7 | Agent dry run (toy issue through spec, build, publish, CI, review, stop label) | **Before the factory is switched on** (end of Phase 1a) |
| 8 | Release dry run (tag, update, smoke, rollback) | Phase 1c, before first real release |

### 4.3 Idea or bug to PR loop

```
idea issue (owner) -> spec PR (agent) -> owner approves -> build PR (agent, tests first) -> owner reviews + merges
```

1. Owner opens an `idea` issue (one paragraph, helper, data touched, size S/M/L). Only the owner's issues start agents.
2. Owner adds `agent:spec` (M and L need a spec; S may go straight to `agent:build`). Agent opens a spec PR in `docs/specs/`.
3. After merge of the spec, `agent:build`. Agent writes failing tests from the acceptance list, then code. Output is a patch.
4. A separate publish job applies the patch and opens the PR. PR template: linked issue, spec, tests, eval delta, files outside the helper, risk labels.
5. CI, then the owner reviews and merges. Max 3 agent PRs open.

**Bugs in v1 (R1-15).** The runtime catches errors and writes a local incident. `lifeos report --dry-run` prints the allowlisted report. The owner opens an `idea` issue and pastes fingerprint and frames. There is no bot token and no auto bug issue. OCR and extraction bugs that need real data are measured locally with `lifeos eval --local` and described by the owner in words. Revisit auto bug flow after Phase 3, with data on how often manual reports occur.

### 4.4 Agent runner

`kiro-cli` headless in our own GitHub-hosted workflow (one runner, split jobs). Flags for tool allowlist, max turns, max tokens and agent file are **not verified**; a 5-issue pilot before trust (03 §6). Self-hosted runners are rejected. Cloud agents that read raw issue text are not used.

### 4.5 Guard rails

| Rail | Control |
|---|---|
| No self-merge | Ruleset on `main` (GitHub Free, public repo): PR required, required checks, linear history, squash only, no force push, no bypass for agents or the App. Auto-merge off. Phase 0 uses 0 required approvals, because an author cannot approve their own PR and Phase 0 PRs come from the owner. From Phase 1a, when the App opens PRs, change to 1 approval with CODEOWNERS and record the choice. Which ruleset features the Free plan offers is verified by trying (done-when 3). |
| No write token in agent job | Agent job: `contents: read`, model key only, no web, no `curl`. Publish job: GitHub App token, this repo only. |
| Publish job runs no patch code (R1-14) | Only `git apply` of a validated patch. No hooks, no scripts, no build step from patch content (`core.hooksPath` pointed at an empty dir). Then push and open PR. |
| Patch gate (plain script) | No changes to `.github/**`, `CODEOWNERS`, `AGENTS.md`, rules. No new binaries. Size limit. Paths limited to the issue's `helper:*` plus `core/`, `tests/`, `docs/`. **High-risk label** for `core/permissions/**`, `helpers/*/permissions.yml`, `config/policy.toml`, `tests/security/permissions.lock`, `evals/baselines/**`, egress code (R1-4). |
| No real data in GitHub | **The repo is public.** Git history is permanent and forks keep copies, so the first push happens only after a scan of the whole tree and all history from a fresh repo, with the owner's configured commit identity. Local gates: pre-commit hooks, a pre-push hook and `make privacy-scan` with a private deny list that is never committed. CI gates: `fixtures-clean`, `secrets-scan` (gitleaks plus generic regexes), which cannot see the deny list. CI is therefore not a full guard. Files under `docs/` and `tests/fixtures/` need a `synthetic` marker or an allowlist entry. CI logs print ids only. No artifacts except coverage, retention 1 day. |
| Dependencies | Actions by SHA. Dependabot PRs. Agent may add a dependency only with owner label `dep-change`. |
| Loop and spend | Job timeout 30 min, max turns, max tokens, concurrency per issue, WIP 3. Spend cap at the model provider (hard layer). `agent:stop` label and `FACTORY_ENABLED=false`. No ledger branch in v1. |
| Review fatigue | PR under about 400 changed lines, PR template, risk labels. |

Owner's own changes: a bypass for `docs/` and `.github/` fixes only if the Free plan supports it (not verified), logged.

### 4.6 Release

Main is never deployed. Only a tag.
1. Owner creates a **signed tag** `vX.Y.Z`. A tag ruleset allows only the owner.
2. Release workflow reruns CI and evals on the tag, builds the package, publishes checksums and generated notes (merged PRs, migrations). **No SBOM in v1.** Attestation is possible on public repos and is optional, not blocked (believed). An approval click in a `release` environment is optional and depends on the plan (not verified); the owner's signed tag is the gate.
3. The owner downloads the bundle (compose file plus image tarballs) and runs `lifeos update --from <file>`. It verifies the checksum and the signed tag, shows the changelog and migrations, takes a restic snapshot, loads the images, migrates (note-schema migrations rewrite frontmatter as one commit in the data repo; expand then contract), runs the smoke test on synthetic fixtures, then points Compose at the new tag.
4. No auto-update. `lifeos rollback` points Compose back, reverts the migration commit in the data repo and restores the snapshot if needed. Keep 3 releases and 3 snapshots. A failed smoke test rolls back by itself.

### 4.7 Weekly owner routine

About 30 to 45 minutes, one slot. Read the factory report issue (spend, runs, stuck items), review PRs (specs first), clear `needs-human`, set labels on new ideas up to WIP 3, optionally tag a release. Monthly: spend cap, token rotation, Dependabot, baseline drift. 03 §13.

---

## 5. Answers to review-r1, by number

"Resolved" means this file decides it. "Owner" means it stays an owner decision (see section 6).

**Revision 2 note:** these answers were written for revision 1. Revision 2 (section 10) changed the premises of points 1, 2, 7, 9, 12, 16 and 22. Each of those rows ends with a "Rev 2" sentence. Where an answer and section 2 differ, section 2 and section 10 win.

### A. Contradictions

| # | Resolution |
|---|---|
| 1 | **Resolved.** FileVault plus restic-encrypted backups only. 02a §4.4 app-level encryption is dropped for v1. No volume that needs an unlock, so services resume after login. Missing Daily brief by 09:00 means "system down" (2.9, 2.11). Owner confirms in D3. **Rev 2:** the host may be a NUC. Disk encryption is LUKS there (D3), with the same unattended-reboot caveat (2.11). |
| 2 | **Resolved.** On a Mac the boundary is code review, permission files, tests and the audit log. v1 holds no bank or mail credentials, so the gap is not exploitable by credentials. Containers are required before FinTS or IMAP (2.11). 02a §4.6.2 and §4.7.5 are read as targets, not v1 guarantees. **Rev 2:** containers are now the base (2.11). v1 does hold two outside credentials, the cloud model key and the ingest mailbox. Each is confined to one container. |
| 3 | **Resolved.** `permissions.yml` lists `agents: [{name, role, tools}]`. Financial stays one folder with three agents. The patch gate keeps keying on `helper:*` (2.6). |
| 4 | **Resolved.** `helpers/*/permissions.yml`, `config/policy.toml` and `tests/security/permissions.lock` are high-risk. Contract tests compare against the lock. Only a high-risk PR changes the lock (2.6, 4.5). |
| 5 | **Resolved.** `external_only` reports are never auto-sent (moot in v1: reporter is dry-run only). `count_hint` renamed `count` (2.10 rows 3 and 5). |
| 6 | **Resolved.** Phase 0 is built by the owner with an interactive agent. The factory is switched on at the end of Phase 1a after the agent dry run (item 7). Item 6 (fault injection) is required before reminders go live. See the DoR table in 4.2. |
| 7 | **Resolved.** C1 stays clear in the local store and local models. Masking happens only in the gateway before any cloud call. Owner identity data added as a C1 row (2.3). **Rev 2:** class table now has a per-class cloud switch. Incidental identifiers in an allowed letter go to the provider (2.3). |
| 8 | **Resolved as one decision.** Push and phone access merge into D2: VPN, ntfy self-hosted, generic push text. Not independently verified for iOS (section 9). |
| 9 | **Resolved.** Mail and calendar in 02a are relabelled "first supported method" (section 3). Mail is Phase 4. **Rev 2:** forwarding letters to an ingest address moves to Phase 1 (2.14). Full inbox triage stays Phase 4. |

### B. Wrong premises and security gaps

| # | Resolution |
|---|---|
| 10 | **Resolved, D9 closed.** The repo is public on GitHub Free with rulesets enforced. SBOM dropped, attestation optional. Signed tag plus checksum. Phase 0 verifies by trying that the ruleset blocks a direct push and that required checks work. If they do not, rail 1 does not enforce and Phase 0 is not done. |
| 11 | **Resolved.** Plain HTML upload form with `capture`, over VPN with HTTPS. Path E (drop folder) added (2.7). |
| 12 | **Resolved.** Contract row 2 in 2.10 covers launchd stderr, tracebacks, third-party log levels, Spotlight exclusion, Time Machine exclusion. Canary test greps all of them. **Rev 2:** launchd and Paperless wording replaced by container logs (2.10 row 2). |
| 13 | **Resolved.** Plain text rendering, CSP `default-src 'self'`, citations as local links only (2.7). |
| 14 | **Resolved.** Corpus path denied to agent file reads and tests read it as input. Fallback: generate at test time. Publish job rule "`git apply` only" added in 4.5. |
| 15 | **Resolved.** v1 reporter is `--dry-run` only. Manual paste into an idea issue. No bot token, no schema workflow (4.3). |
| 16 | **Resolved.** Cloud is off in the MVP. Redaction is labelled best-effort for any later cloud use (2.3). 02a §4.9 should be read with that label. **Rev 2:** superseded. Cloud is on behind per-class switches (2.13). Redaction stays best effort. |
| 17 | **Resolved as a process.** The rules module keeps rule, formula, statute link, "owner verified on <date>". The Einwendungsfrist correction and the Einspruch rule are in 2.8. Statute texts are fetched before Phase 2. Statements stay "believed" until then. |
| 18 | **Resolved by point 2.** |

### C. Missing before an MVP

| # | Resolution |
|---|---|
| 19 | **Resolved.** Kinds: Einspruch, Zahlungsfrist, Kündigung. `received_at` set by owner at upload. Holiday source: `holidays` library. Lead times, snooze, done in 2.8 and 2.9. |
| 20 | **Resolved.** Six types with fields and deadline mapping (2.7). Multi-photo grouping by the upload form. Backlog import in `historic` mode. |
| 21 | **Resolved.** One server-rendered web app, password and session over VPN, four screens, German text (2.7). |
| 22 | **Resolved as a gated task.** Week-1 spike: 30 real letters, local only, measure OCR error and date, amount, sender F1. The owner sets thresholds. Below threshold, everything goes to review. Model and hardware are chosen after the spike (D5). Blocks Phase 1. **Rev 2:** the spike now compares cloud vision OCR and extraction with the Tesseract fallback. It needs the provider and DPA first (D4). No local LLM or GPU hardware is needed. |
| 23 | **Resolved.** Reminder table, repeat, escalation, quiet-hour exception (2.9). |

### D. Top owner decisions

All twelve R1 defaults are adopted as recommended defaults in section 6 (D1 to D12). They stay owner decisions until the owner approves this file.

### E. Cut from v1

All cuts are adopted:

| Cut item | Where applied |
|---|---|
| Process per helper, own OS user, tool broker with tickets, MCP internal layer, `AgentRunner`, Pydantic AI spike | 2.1, 2.2, 2.4. `permissions.yml` and read/act separation stay as a test-time check |
| Hash-chained audit log | 2.2 (append-only file) |
| Extra helpers except Daily brief and Ops | 2.5. Contract, Financial, Mail stay on the roadmap |
| Vector search at first | 2.2 (FTS5 first) |
| Paperless adapter for a second backend | 2.2 (thin client) |
| Factory: bug bot, schema workflow, ledger branch, advisory reviewer, Copilot fallback, `evals-llm`, CodeQL, SBOM, attestation, licence check | 4.2 |
| Kept: PR gate, `fixtures-clean`, `secrets-scan`, SHA pinning, provider spend cap, stop label | 4.2, 4.5 |
| Thin vertical slice first | Phase 1a (section 8) |

### Review-r0 items still relevant

R0 points 1-6 (work split) are moot. R0 points 9-15 (PSD2, bank APIs, brokers, ELSTER, advice law, DSGVO, injection) are applied in section 3 and 2.3. R0 16-20 (repo visibility, token scope, release, loop caps, test base) are applied in section 4. R0 21-26 (helper ideas, shared core, notifications, ingestion, roadmap, German) are applied in sections 2 and 8.

### Contradictions resolved (table)

| Point | Files | Resolution |
|---|---|---|
| Encryption vs unattended reminders | 02a §4.4, 02 §3.1, 02 §3.9, 02 §6.1 | FileVault plus restic only. No unlock step. 09:00 brief as dead-man. |
| Process isolation vs Mac runtime | 02 §2, 02 §6.1, 02 §6.5, 02a §4.6, 02a §4.7 | Isolation is a target. Rev 2: Compose containers, two outside credentials, one per container. Own container before FinTS or full-inbox IMAP. |
| Reader/actor roles vs one file per helper | 02 §3.5, 02 §4.1, 03 §2 | `agents` list inside `permissions.yml`. One folder per helper. |
| Permission file editable by agents | 03 §4, 03 §8, 02 §8.7 | High-risk paths plus `permissions.lock`. |
| Report schema vs schema check | 02 §8.1, 02 §8.2, 03 §5.4 | `count` field. `external_only` never auto-sent. No schema workflow in v1. |
| Definition of ready vs Phase 0 | 03 §11, 02 §10 | Items staged by phase (4.2). Owner builds Phase 0. |
| C1 masking vs features | 02a §4.3, 02 §3.2, 02 §3.7 | Clear locally, masked at the gateway for cloud only. |
| ntfy vs closed network | 02 §3.4, 02 §6.5 | VPN plus ntfy as one decision. |
| "v1" labels | 02a §1, 02 §10 | Relabelled "first supported method". |
| Tool names vs stack | 03 intro, 02 §0 | Python 3.12 assumed. One stack. |
| Agent framework | 02 §5.4, 03 §6 | No framework in v1. Revisit in Phase 3. |
| Audit log tamper evidence | 02a §4.8, 02 §3.6, 02 §8.6 | Append-only file. Chain and chain check dropped. |
| Phase order | 01 §1.3, 02 §10 | 02's phases adopted. Mail triage in Phase 4. Daily brief and Ops in Phase 1. |
| Release provenance | 03 §9, 02 §8.8 | Signed tag and checksum. No attestation. Manual `--from` update. |
| Cloud redaction | 02a §4.3 C5, 02 §3.8 | Rev 2: cloud on behind class switches. Redaction best effort. |
| Updater token | 03 Q3, 02 §8.8 | Manual download default. Token optional later. |
| Log scope | 02 §8.1 | Extended to stderr, third-party logs, Spotlight, Time Machine. |
| Eval folders | 03 §2, 02 §7 | `evals/extract/` added. |
| SQLite store and FTS5 vs Markdown as source of truth | 02 §3.1, 02 §3.2, 02 §6.2, rev 1 2.2 | Rev 2: Markdown only. qmd cache rebuildable. Scheduler has no job table (2.12). |
| Paperless-ngx as archive and OCR | 01 §1.3, 02 §3.1, rev 1 D8 | Rev 2: dropped. `files/` plus `raw/` plus qmd plus review UI. |
| "Cloud off, local models only" vs cloud inference | 02a §4.3, 02 §3.8, rev 1 2.3 and D4 | Rev 2: cloud on behind per-class switches, EU region, DPA (2.3, 2.13). |
| C1 "never cloud" vs letters that contain identifiers | 02a §4.3, rev 1 2.3 | C1 means identity documents (blocked). Incidental identifiers in an allowed letter go with it. Owner accepts in D4. |
| "v1 holds no credentials" vs gateway key and ingest mailbox | rev 1 2.11, 02a §4.6 | Two credentials, each in one container (2.11, 2.14). |
| launchd and Mac-only vs Docker and NUC | 02 §6.1, 02 §6.2, rev 1 2.11 | Compose from day one. Mac allowed in v1. NUC target (2.11). |
| FileVault only vs NUC reboot | rev 1 R1-1 | LUKS on NUC. TPM auto-unlock unverified. Dead-man rule stays (D3). |
| Mail-in in Phase 4 vs Phase 1 | rev 1 2.7, 02a §2 | Forwarded `.eml` in Phase 1. Full inbox triage Phase 4 (2.14). |
| Local OCR model vs cloud vision | 02 §3.7, rev 1 R1-22 | Cloud vision first, `ocrmypdf`/Tesseract fallback and pre-scan. |
| Class stored per document vs fixed frontmatter fields | 02a §4.3, owner schema | Class derived from `type` by a code table, plus routing hints. Not a frontmatter field (2.3). |

---

## 6. Owner decisions

Recommended defaults are adopted in this design until you say otherwise. "Blocks" says what cannot start without the decision. **Rev 2** marks decisions changed or added by the owner's revision.

| ID | Decision | Options | Recommended default | Blocks |
|---|---|---|---|---|
| D1 | Where it runs (**Rev 2**) | Mac in Docker (v1); Intel NUC at home (target); cloud VM (allowed, not preferred) | Compose from day one. Mac for v1. NUC as main host once bought. Reminders go live on an always-on host | Phase 1c (reminders live) |
| D2 | Phone access and push | VPN + ntfy + HTML form; home Wi-Fi only; Signal later | VPN (WireGuard or Tailscale) to the NUC or Mac + self-hosted ntfy + HTML form | Phase 1a upload from phone |
| D3 | Encryption (**Rev 2**) | Disk encryption + restic; plus app-level layer; encrypted volume only | FileVault on the Mac, LUKS on the NUC with TPM auto-unlock if it works, otherwise manual unlock and the dead-man rule. restic always | Phase 0 (backup design) |
| D4 | Cloud AI backend and class switches (**Rev 2, 2.1**) | Backend: (a) Bedrock EU direct (`eu-central-1` as example); (b) Kiro via `kiro-cli`; (c) both: Kiro for helpers and factory, Bedrock EU for letters and mail. Per class: allow, redacted, local, block | Decide in the Phase 1a spike after checking Kiro's inference region and data terms for your plan. If they fall short (for example US only, or training allowed), letters and mail go to Bedrock EU (option c or a). C4, C5, C6 `allow`. C1, C2, C3, `own/` `block`. You accept that incidental identifiers travel with allowed letters. Spend cap at the provider | **Phase 1a spike** (no real letter leaves the host before this) |
| D5 | Hardware and quality thresholds (**Rev 2**) | NUC model, RAM, disk; OCR/extraction accuracy thresholds | NUC with enough RAM and disk for qmd and Docker (no GPU needed). You set thresholds after the 30-letter spike | NUC purchase. Phase 1a end |
| D6 | Bank data | File import; FinTS pilot; direct-bank REST API; unofficial broker client | File import only in v1-v2. FinTS pilot only after Phase 3 | Phase 3 importer list |
| D7 | ELSTER | Prepare only; ERiC submission | Prepare only | Phase 3 tax worksheet |
| D8 | Document store (**Rev 2**) | ~~Paperless-ngx~~ dropped. Files + qmd | Decided by owner: `files/` + `raw/` + `notes/` + qmd. Confirm qmd in the spike | Phase 1a |
| D9 | GitHub plan | **Closed.** Public repo on GitHub Free, rulesets enforced | Decided. Phase 0 verifies the ruleset by trying a direct push | Nothing |
| D10 | Bug reporting | Manual dry-run; auto bot | Manual dry-run | Nothing in v1 |
| D11 | Auto-confirm | None; per-field rules | None for deadlines, amounts, payees | Phase 1b |
| D12 | Personal use only | Hard rule (incl. other household members); allow household | Hard rule | Legal position in section 3 |
| D13 | Agent runner and spend cap | kiro-cli headless; other; monthly cap amount | kiro-cli headless. You set the cap at the provider | Factory switch-on (Phase 1a end) |
| D14 | Owner login | Password + session; passkey | Password + session timeout over VPN | Phase 1a UI |
| D15 | Backup target and recovery note (**Rev 2**) | Local disk; encrypted cloud bucket (EU); both | Both: nightly to a second local disk, weekly to an encrypted EU bucket. restic key stored offline | Phase 0 restore test |
| D16 | Release approval click | Signed tag only; plus `release` environment click | Signed tag only unless the plan supports the click | First release (Phase 1c) |
| D17 | Which helpers stay on the roadmap | Vehicle, housing, health | Cross out what is not used | Phase 4 planning |
| D18 | Region and holidays | State for holiday logic | The owner's state (config) | Phase 1b deadlines |
| D19 | Ingest mailbox provider and DNS (**Rev 2**, was mail and calendar) | Provider for `ingest@example.com`; plus-tag support; a separate account with SMTP off. Calendar provider decided at Phase 2 | Pick a provider that gives a separate mailbox, SPF/DKIM/DMARC for your domain, IMAP, and plus-tags | Phase 1b (mail-in) |
| D20 | Ingest sender allowlist (**Rev 2**, new) | Which of your own addresses may forward; other people excluded by D12 | Your own addresses only. Everything else is rejected | Phase 1b |
| D21 | Class confirmation before cloud (**Rev 2**, new) | Auto-route by rules (with "nur lokal" box); confirm class on every upload; all local | Confirm class on every upload during the spike and the first weeks, then auto-route | Phase 1a spike |

---

---

## 7. v1 cut list (deliberately not in v1)

- Cloud inference for C1, C2, C3 and `own/` notes (default `block`). Any credential for bank, broker or ELSTER. Any mail send path. Full-inbox mail access.
- An app database of any kind (SQLite, Postgres). Paperless-ngx. Two-way sync with any DB. A local LLM or GPU.
- FinTS, direct-bank REST APIs, unofficial broker clients, aggregators, ERiC submission, trading or payments.
- Mail triage of the full inbox, calendar write, Health, Housing, Vehicle, Tariff watch, People memory.
- Auto-confirm of extracted values.
- Process per helper, per-helper OS user, tool broker with tickets, MCP layer, agent framework, Pydantic AI.
- Hash-chained audit log. App-level encryption.
- Own embedding pipeline (qmd's own search is used as is, if it passes the spike). A second document store backend.
- A remote for the data repo. Git storage for `files/`.
- PWA, Web Share Target, chat-bot upload. Launchd services.
- Factory: auto bug bot, schema workflow, `factory-state` ledger branch, advisory reviewer agent, Copilot fallback, `evals-llm`, CodeQL, SBOM, attestation, licence check, self-hosted runner.
- Auto-update. External heartbeat service. Multi-user. A separate container per helper.

---

## 8. Phased roadmap

Each phase has a "done when" you can check. Rev 2 changes are marked.

### Phase 0: factory skeleton and test gate (owner builds, with an interactive agent)

Scope: repo and layout, `AGENTS.md`, CODEOWNERS with high-risk paths, ruleset on `main`, CI checks from 4.2, fixture generator (a few German letters and one `.eml`), canary and permission-lock tests, `core/runtime` basics (log API, config, fake clock, `smoke`, `report --dry-run`), **Compose skeleton that starts on the Mac, data dir layout with the note schema and `lifeos validate` (Rev 2), data repo init with the no-remote guard (Rev 2), restic backup and restore test**, and the privacy guard for the public repo (4.5). Exception, stated once: the first commit is pushed directly, because no ruleset exists yet. The precondition is a clean scan of the whole tree and history. The first required check is `secrets-scan`. The other required checks join the ruleset in a later PR, after they have run once (a ruleset can only require checks that already exist).

Done when:
1. A toy PR from an interactive agent runs all required checks green on GitHub.
2. A known-bad fixture makes `fixtures-clean` fail. A planted canary in a log makes the canary test fail. Widening a `permissions.yml` without changing the lock fails CI.
3. The ruleset blocks a direct push to `main`, and an agent cannot merge (verified by trying).
4. `docker compose up` on a clean checkout starts `core` and `ntfy` and passes `lifeos smoke` on synthetic fixtures. **(Rev 2)**
5. A note with an invalid frontmatter key lands in `review/`, and a test fails if the data repo has a remote or a remote is added. **(Rev 2)**
6. `lifeos restore --verify` restores a restic snapshot into a scratch directory, rebuilds the qmd cache with `lifeos reindex`, and every note validates. **(Rev 2, replaces the old restore line)**
7. DoR items 1 to 4 are done.

### Phase 1: MVP, Document helper plus deadlines plus mail-in

**1a. Spike and thin slice.** Needs D4 (provider and DPA), D21 and D19 decided first. Week 1: spike on 30 real letters through the gateway, compared with the Tesseract fallback. You set thresholds (D5). qmd is tested on the resulting notes. Then the slice: upload, OCR, extract one doc type, confirm, deadline, push. Eval harness and baselines (DoR 5). Agent dry run (DoR 7). Factory switched on after it.

Done when: you photograph a real letter on your phone over the VPN, review it next to the page image, confirm a deadline and receive a push. The note is a valid Markdown file in `notes/`, `raw/` holds the text, `files/` holds the photo, and the data git repo has the commit. The audit JSONL shows exactly one cloud call for it, with no content. A letter marked "nur lokal" shows zero cloud calls. Spike report with thresholds exists. A toy issue passes the whole factory loop, including the stop label.

**1b. Widen and mail-in (Rev 2).** All six document types, grouping, `historic` backlog mode, rules module with the three verified rules, qmd Q&A with citations, Daily brief, Ops health. **Mail-in:** `ingest` container, allowlist, SPF/DKIM check, `.eml` pipeline, plus-tags, rejected-mail handling.

Done when: local eval scores are above your thresholds. Q&A refuses when the answer is not in your documents. Rules show "owner verified on <date>". A forwarded `.eml` from your allowlisted address becomes a draft note with the original sender and date. A mail from another address, or one that fails SPF/DKIM, lands in `Rejected` and creates no note. A static test shows the `ingest` image has no SMTP code and the compose file gives it no route except the IMAP host. A hostile-mail corpus (injection text, bad MIME) produces no tool call and no cloud call beyond the normal extraction.

**1c. Reminders live and host move.** Fault injection on the deadline engine (DoR 6). Release dry run (DoR 8). First signed tag and `lifeos update`. Reminders go live on an always-on host: the NUC if it exists, otherwise the Mac with your explicit OK.

Done when: a deadline set on the fake clock fires at the right lead times, survives a sleep gap with catch-up, escalates when not acknowledged, and quiet hours behave. Ack, snooze and done show up in the note's frontmatter and as a git commit. Missing brief at 09:00 is noticed. You ran one real update and one rollback. If the NUC is the host: a restic restore of the Mac data dir onto the NUC reproduces the same notes, and the phone reaches the UI over VPN. **(Rev 2)**

### Phase 2: Contract

Statute fetch for notice rules. Contracts as notes of type `kuendigung_vertrag` with a computed notice date, cancellation date with margin, cancellation letter PDF from confirmed fields, Subscriptions (manual list), Warranty. Calendar read-only if wanted. Procedure for deleting a document for good (git history and backups).

Done when: your contract list is built from real letters. Notice reminders fire at the right lead time. The letter PDF uses confirmed fields only. No send tool exists (test). The delete procedure was run once on a test document.

### Phase 3: Finance, read-only

Importers per bank and broker format (fixtures per format), portfolio-tool import or export, `analyst` agent, tax worksheet and checklist for one year, bank-message triage. Decide the C3 cloud switch (D4). Revisit the agent loop and framework here. Optional: one FinTS pilot, only in its own container with its own network rule.

Done when: importers pass fixtures per bank. A static test shows no order or payment endpoint exists. Advice output carries the disclaimer. The worksheet matches your manual figures for one year. C3 data reaches the gateway only if the switch allows it (test).

### Phase 4: Extras

Full-inbox mail triage (IMAP in its own container, read-only), Health (local only), Housing (Einwendungsfrist rule), Vehicle, Tariff watch, Developer admin. Revisit auto bug flow.

Done when, per helper: permission suite and injection corpus pass, and you confirm real use.

---

## 9. Sources, not verified, open questions

### Sources

This file is a merge plus the owner's revision 2. It cites the detail files; each lists its own sources with access date 2026-11-21:
- 01 §Sources: GitHub repos and API data, security write-ups on OpenClaw, Paperless-ngx discussions, Home Assistant threads, contract tool tests.
- 02a §5 (S1 to S22): FinTS registration, direct-bank API docs and forum, EBA SCA consultation, aggregator pages, unofficial broker client repos, ELSTER and ERiC pages.
- 02 §Sources: MCP release candidate post, ntfy docs, Telegram encryption page, Pydantic AI and OpenAI Agents SDK docs, restic, Ollama.
- 03 §Sources: kiro-action README, claude-code-action security doc, Codex GitHub Action docs, GitHub Copilot and Actions security pages (navigation only).
- review-r0.md, review-r1.md (reviewer statements marked "believed").
- Rev 2: qmd, [github.com/tobi/qmd](https://github.com/tobi/qmd), named by the owner. Not fetched.

No new web sources were fetched for this merge or for revision 2.

### Not verified

Platform and GitHub:
- Which ruleset, required-check and environment features GitHub Free offers on a public repo (bypass lists, environment rules). Verify by trying before relying on them.
- `GITHUB_TOKEN`-opened PRs do not trigger workflows (03, believed).
- Kiro CLI headless flags (tool allowlist, max turns, max tokens, agent file). Kiro spend controls.
- Whether egress allowlisting on hosted runners needs a third-party action.

Phone and runtime:
- iOS Safari does not support Web Share Target (R1-11, believed). `capture` input behavior on iOS.
- ntfy self-hosted on iOS needs the phone to reach the server, and what the upstream relay receives (R1-8).
- Which VPN fits. Python 3.12 or newer. Library licences (AGPL and others).
- Restic with the chosen offsite target. `holidays` library coverage for the owner's state.

Rev 2, search and storage:
- qmd: what it indexes, its runtime and hardware needs on a NUC, German search quality, licence, whether it has a keyword-only mode, and whether its cache can be fully rebuilt.
- Git behavior with many small commits and large `raw/` files. Time to `reindex` at your volume.
- `chattr +a` for the audit log on the chosen NUC OS.

Rev 2, cloud AI and mail:
- Kiro as backend: inference region, data retention and training terms per Kiro plan, `kiro-cli` headless auth on Linux, tool-free agent config flags (no shell, no write, no MCP, max turns), structured-output support and model pinning, rate limits and credits, the Kiro endpoint list for egress rules.
- Cloud provider facts: EU region availability of a vision model (for example Bedrock `eu-central-1`, or only cross-region routing), no-training terms, prompt retention and abuse-monitoring storage, DPA availability, pricing, rate limits.
- Whether an EU region still leaves access by non-EU parent companies (believed). Whether the household exemption still applies once a processor is used.
- Mail provider: separate mailbox with SMTP disabled, plus-tag support, `Authentication-Results` header format, IMAP move semantics, app-password or OAuth policy.
- NUC: TPM auto-unlock for LUKS, Docker on the chosen OS, power-loss behavior.

Legal and deadline rules (all from reviewer or writer knowledge, none fetched):
- §355 AO (one month), §122 AO (third-day rule), §108 AO (weekend shift) for Einspruch.
- §556 Abs. 3 BGB (Nebenkosten, 12 months, Einwendungsfrist).
- Kündigung: Zugang rule, notice periods per contract type, 30 November for car insurance.
- WpIG, KWG, StBerG position for self-use tools. DSGVO position with a cloud processor.

Data access (02a §7): FinTS product registration for single-user use, TAN frequency per bank, direct-bank API token lifetimes and terms, neo-broker ToS and export lists, ERiC terms for individuals, other broker export formats.

### Open questions

1. Is a Mac good enough until the NUC arrives, and when is the NUC bought? (D1, D5)
2. Which NUC model, RAM and disk? Any second disk for local backups? (D5, D15)
3. Which bank and broker export formats must the importers cover? (D6)
4. Do 30 letters exist that the owner accepts for the spike, given they go to the cloud provider?
5. What may appear on a lock screen? Fixed time for the Daily brief (default 09:00)?
6. May the factory read aggregate local eval scores, or does the owner copy them by hand? (Default: by hand.)
7. Can the chosen mail provider give a separate ingest mailbox? (D19)
8. The schema has one `deadline` per note. A Steuerbescheid has Einspruch and payment dates. Default: linked notes, one per deadline, same `raw`. Is that acceptable, or should the schema allow a list?
9. `raw/<slug>.md` carries `file`, `sha256`, `pages`, `extractor`, `model_id` in its own frontmatter. Is that addition to the field list acceptable?
10. Which note types may be sent to the cloud before the spike has results? (D4, D21)

---

## 10. Revision 2 (owner changes)

Requested by the owner on 2026-11-21. Section 2 and the later sections were edited in place. This table lists each change and what it replaced.

| # | Change | Replaced | Where |
|---|---|---|---|
| R2-1 | Markdown is the only source of truth: `files/`, `raw/`, `notes/` with strict YAML frontmatter, schema validation, invalid files to `review/`. qmd for search (rebuildable cache). Reminders read frontmatter and write ack, snooze, done back. Audit log is JSONL. Owner's own `.md` notes are indexed. No two-way sync. | App SQLite for facts, deadlines and jobs. FTS5 search. DB job table. Hash-chain-free audit file | 2.2, 2.12 |
| R2-2 | `notes/` and `raw/` in a local git repo with no remote, guarded by a test and a health check. `files/` outside git. restic encrypted backups of the whole data dir, target is the owner's choice. Code repo and data repo strictly separate. | Backups of "config, db, docs". No history of notes. | 2.11, D15 |
| R2-3 | Docker Compose from day one. Mac allowed in v1. Intel NUC at home as target data layer, reached over VPN. Cloud VM no longer rejected. | launchd services, "Mac, plugged in" as the default, cloud VM rejected | 2.1, 2.11, D1 |
| R2-4 | NUC holds data, inference uses EU cloud models with no training and a DPA. Gateway stays the only caller, with a per-class switch. DSGVO note and threat model updated. Read/act split stays. | "Local only, cloud off" for the MVP. Local model spike. | 1, 2.3, 2.13, 3, D4, D5 |
| R2-5 | Paperless-ngx dropped. Cloud vision OCR, `ocrmypdf`/Tesseract as fallback and pre-scan. Storage is `files/`, search is qmd, UI is the review UI. | Paperless client for OCR, storage and search. D8 | 2.2, 2.7, D8 |
| R2-6 | Mail-in via forwarded `.eml` to a dedicated address, IMAP watcher in its own container with one mailbox credential, SPF/DKIM plus sender allowlist, plus-tags as hints. Moved to Phase 1. Full inbox triage stays Phase 4. | Mail only in Phase 4 for bank PDFs, "v1 holds no credentials" | 2.5, 2.11, 2.14, 8 |
| R2-7 | Decision list rechecked. Changed: D1, D3, D4, D5, D8, D15, D19. New: D20 sender allowlist, D21 class confirmation before cloud. Roadmap done-when lines rewritten for Phase 0 and Phase 1. | Revision 1 decision rows and done-when lines | 6, 8 |
| R2-8 | Risks, cut list, contradictions table and not-verified list updated. The file states that it supersedes 01, 02, 02a and 03 where they differ. | Revision 1 lists | 1, 5, 7, 9 |
| R2-9 | **Revision 2.1:** Kiro added as an AI backend option behind the gateway: `kiro-cli` headless on the NUC with a tool-free `reader` agent config for letters and mail, and a separate `actor` config for factory and helper agents. D4 options are Bedrock EU direct, Kiro via `kiro-cli`, or both. Default: decide in the Phase 1a spike. Pros: one plan and bill, same tool as the factory runner, no separate cloud account. Cons: region and no-training terms per Kiro plan not verified (may be US); headless sign-in on the NUC; rate limits and credits; harder to pin model and output format. | D4 offered only a direct EU provider | 2.13, 6 (D4), 9 |

New things the owner should know:
- The cloud credential is the first stored credential. The ingest mailbox is the second. Both are listed in 2.11.
- Cloud OCR of an image cannot be masked. Class control for images depends on the intake rules and your "nur lokal" choice (2.13).
- Files as the only store give no transactions. The safeguards are single-writer locking, schema validation, git history and restic.
