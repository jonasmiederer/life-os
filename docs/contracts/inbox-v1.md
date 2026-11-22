<!-- synthetic: true -->
# Inbox contract v1

The mail watcher (`core/mailwatch`) writes. The mail reader (another work item) reads.
The watcher never parses attachments. It only writes the bytes it received.

## Files

For each accepted mail, in `inbox/`:

| File | Content |
|---|---|
| `<id>.eml` | The raw outer mail, byte for byte |
| `<id>.json` | The sidecar (below) |

`<id>` is the lowercase hex sha256 of the raw `.eml` bytes.

Mode `0600`, owner uid `10001`. The reader must run as uid 10001, or it cannot read the files.

## Write order (the sidecar is the commit marker)

1. Write `<id>.eml.tmp`, then fsync.
2. Rename it to `<id>.eml`.
3. Write `<id>.json.tmp`, fsync, rename to `<id>.json`. This comes last.

A reader uses only ids that have a `.json`. A lone `.eml` or any `*.tmp` is an unfinished write: ignore it.
`inbox/.state` belongs to the watcher. Readers must not touch it.

## Sidecar keys

| Key | Type | Meaning |
|---|---|---|
| `v` | int | Always `1` |
| `id` | string | Same as the file name stem |
| `sha256` | string | Same as `id` |
| `size` | int | Byte size of the `.eml` |
| `received_at` | string | ISO 8601 UTC, e.g. `2026-11-22T10:00:00Z` |
| `plus_tag` | string or null | `tax`, `contract` or `local`. Null if absent or unknown. Optional: nothing may depend on it |
| `auth` | object | `dkim`, `dmarc`, `spf`, `from_domain` (strings, from the provider's header) |
| `message_id` | string or null | Outer Message-ID, max 256 chars. Not used for dedupe |
| `attachments_dropped` | int | Outer parts that are not text and not `message/rfc822` |

A new key means a new `v`. Readers reject a `v` they do not know.

## Not promised

- The inner mail is untrusted. Only the outer mail was authenticated.
- A reader may delete a pair after it has stored the content. The watcher keeps its own dedupe hashes.
