<!-- synthetic: true -->
# Mail watcher

Service `ingest-mail` (compose profile `mail`). Code: `core/mailwatch/`. Contract: `docs/contracts/inbox-v1.md`.

## What it does

Reads one IMAP folder over TLS (certificate and host name are always verified).
Accepted mail becomes `inbox/<id>.eml` and `.json`, and is moved to the processed folder.
All other mail is moved to the rejected folder and writes nothing.
It needs IMAP `MOVE` (RFC 6851). Without it the watcher stops with an ops error.
It never deletes, never expunges, and has no SMTP code. A static test enforces both.

## Settings (environment)

| Name | Meaning |
|---|---|
| `LIFEOS_MAIL_IMAP_HOST`, `LIFEOS_MAIL_USER` | Server and login name |
| `LIFEOS_MAIL_PASSWORD_FILE` | Docker secret file. The password is never read from the environment |
| `LIFEOS_MAIL_INGEST_ADDRESS` | The one address the watcher serves. Outer To or Delivered-To must name it |
| `LIFEOS_MAIL_FOLDER`, `_PROCESSED`, `_REJECTED` | The only folders the watcher opens or moves to |
| `LIFEOS_MAIL_AUTHSERV_ID` | authserv-id of your provider's Authentication-Results header |
| `LIFEOS_MAIL_ALLOWED_FROM` | Comma list of From addresses (D20) |
| `LIFEOS_MAIL_ALLOWED_DOMAINS` | Comma list of domains accepted in DKIM `header.d` |
| `LIFEOS_MAIL_TAG_HEADER` | Header for optional plus-tags. Default `Delivered-To` |
| `LIFEOS_MAIL_MAX_BYTES`, `_MAX_PARTS`, `_MAX_DEPTH`, `_DAILY_CAP`, `_POLL_SECONDS` | Limits |

## Accept rule

Checks run on the headers first. A mail that fails them is moved to the rejected folder after at most 64 KB
of headers were fetched. No MIME tree is built for it. All must hold:

1. Exactly one From, on the allowlist.
2. Outer To or Delivered-To names the ingest address (a `+tag` is ignored).
3. Exactly one Authentication-Results header carries the configured authserv-id (two or more: `auth_multi`).
   It has no quote, backslash or unbalanced comment (else `auth_parse`).
   It shows `dkim=pass` for an allowlisted `header.d`, and either `header.d` is aligned with From or `dmarc=pass`.
   SPF alone is not enough. Headers with other ids are ignored.
4. Size, boundary count, part count and depth are within limits. The boundary count is checked before the tree is built.

Plus-tags are optional hints. A mail without one is handled the same way.

Limits (environment): `LIFEOS_MAIL_MAX_BYTES` (default 10 MiB, enforced with a partial fetch),
`LIFEOS_MAIL_PASS_SECONDS` (default 120: one pass is cut off after this, then back-off).

## Owner test before real use

The code cannot tell whether your provider always adds its own Authentication-Results header.
If it sometimes does not, a header forged by the sender with the same authserv-id would be the only one.
Before enabling the service:

1. From an outside account, send a mail to the ingest address that carries a forged
   `Authentication-Results: <your authserv-id>; dkim=pass header.d=<allowed domain>; dmarc=pass` header.
2. Look at the stored mail's full headers. There must be two headers with your id. (The watcher then rejects it as `auth_multi`.)
3. Repeat from an account at the same provider, and from a mail that goes through a forwarding rule.
   If any path shows only the forged header, do not enable the service.

## What the credential can reach

The IMAP login may grant access to the whole account, not only the ingest folder.
The code opens only the three configured folders and never lists others. That is a code rule, not a server limit.
If your provider allows it, use a separate account for the ingest address
(for example a second account on the same domain) so a leaked credential reaches nothing else.

## Network

v1 shortcut: Docker cannot limit egress to one host. The service has an open outbound network.
It can reach any host and any port, including the provider's mail-sending ports.
The only control against sending mail is that the watcher code has no send path (a static test checks the code).
If the code were taken over, the credential could send mail. A firewall or egress proxy is a later work item.
Use a separate account, and turn off sending for it if the provider allows.

## Secret file

The container runs as uid 10001 and must be able to read the file named by `LIFEOS_MAIL_PASSWORD_FILE`.
On the host: `chown 10001 secrets/mail_password && chmod 0400 secrets/mail_password`.
If it cannot be read, the watcher exits with `bad_secret` and compose restarts it only five times.
The password must be ASCII.

## Folder upkeep

Nothing is deleted. The rejected and processed folders grow. Empty them by hand now and then.
Rejected mail costs one small header fetch each. A pass handles at most 100 mails.

## Credential rotation

1. Create the new password at the provider (or a new app-specific password).
2. Write it to the secret file named by `LIFEOS_MAIL_PASSWORD_FILE`.
3. `docker compose --profile mail up -d --force-recreate ingest-mail`.
4. Revoke the old password at the provider.
5. Check that the log shows `mailwatch.run` with `status=ok`.

A failed login backs off from 5 minutes, doubling up to 6 hours, and sends one ntfy alert per day.
The back-off is stored in `inbox/.state`, so a restart does not retry sooner.

## Alerts

- One ntfy per day for rejects, sent after the day ends: "N Mail abgelehnt".
- One ntfy per day when the daily accept cap is hit. The rest stay in the folder until the next day.
- One ntfy per day for connection or login trouble, and when `MOVE` is missing.

Logs hold counts, sha256 ids and reason codes only. Never subject, sender or address.
