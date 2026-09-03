---
name: be-backup
description: Whole-platform backup and restore — age-encrypted archives (pg_dump + attachment-bucket mirror) in their own MinIO bucket, a catalogue at /admin/backups, a nightly worker cron, retention with pinning, and an in-app restore that takes a safety copy first. Use when working on backups, restore, archives, the age key pair, backup.manage, or the Backup model in backend/app/modules/backup and backend/worker/backup.py.
---

# Backup / Restore — `backend/app/modules/backup`

**Does:** Takes and restores a backup of the whole platform from the web UI. One archive is an age-encrypted tar holding a `pg_dump --format=custom` of the database plus a mirror of the attachment bucket. Archives live in their own MinIO bucket. Every action is audited.

**Why in-app:** the shell scripts this replaced (`deploy/backup/`) could only be driven from an SSH session on the VM. The people who run this platform are a student government, not operators with a terminal.

**Key files:**
- `models.py` — the `Backup` catalogue row plus the archive member names. Metadata only; the archive is in MinIO.
- `archive.py` — pure layer: tar layout, age encrypt/decrypt (`pyrage`), the manifest. No DB, no subprocess, so the unit tests drive it directly.
- `service.py` — `BackupService`: catalogue CRUD, retention, `build_archive`, `apply_archive`, `verify_archive`, plus the `pg_dump`/`pg_restore` subprocess wrapper.
- `queue.py` — arq enqueue. The API never dumps or restores in a request.
- `router.py` — `/admin/backups`, gated by `backup.manage`.
- `worker/backup.py` — `create_backup`, `restore_backup`, `scheduled_backup`, `run_retention`.

## Traps

- **`backup.manage` is in `FORBIDDEN_PERMISSIONS`** (`modules/auth/oauth.py`), beside `vote.cast`. No OAuth agent token reaches a backup, an export or a restore, whatever the scope says. Its holder can read the whole database and replace it.
- **The private age key lives in the stack.** That is the price of restoring from a browser, and it is a real reduction against the old encrypt-only design. Use a key pair for the app ONLY; the disaster-recovery pair stays off host. `deploy/secrets/` is mounted read-only into `api` and `worker`.
- **A restore takes a `pre_restore` safety archive FIRST** and aborts entirely when that fails. No undo means no restore. A `pre_restore` row and a pinned row never count towards retention and are never pruned.
- **The restore audit entry lands in the RESTORED chain**, because the restore replaces `audit_entry` along with everything else. The safety archive is the only record of the state before it.
- **`pg_dump` must match the server major.** The backend image installs `postgresql-client-16` from PGDG; compose runs `postgres:16-alpine`. An older `pg_dump` refuses to run.
- **`pg_restore` is run with `tolerate_nonzero=True`.** `--clean` warns for every object the target does not have yet, which sets a non-zero exit even on a good restore.
- **Nothing buffers a whole archive.** `archive.py` works on file objects, and `build_archive` stages the bucket on disk first, so peak memory is one object. `tempfile` honours `TMPDIR`: a container with a small tmpfs there fails here first.
- **`iter_objects` skips an absolute, empty or traversing object key.** A crafted archive must not steer a restore into writing outside the bucket.
- The migration `f3b3f1a022b5` is idempotent, because `0001_baseline` runs `Base.metadata.create_all`. See the `conventions` skill.

## Config

`backup_age_recipient` (empty ⇒ every route answers 503 and the cron does nothing) · `backup_age_identity_file` (absent ⇒ restore and import are off, and the page now says so beside the disabled control rather than leaving it dead) · `backup_bucket` · `backup_retention_count` · `backup_url_ttl_seconds` · `backup_max_upload_bytes` · `backup_subprocess_timeout_seconds`. Setup and the operator callout: `deploy/README.md`.

## Frontend

`frontend/src/app/pages/admin/backups/`. The restore dialog demands the literal `RESTORE`; the API demands the same. The page reports `enabled`/`restoreEnabled` from the list response rather than offering buttons that always fail.

**Related:** `be-audit` (the action catalog), `be-files` (the object storage it walks), `be-auth` (the permission), `deploy` (the key pair and the volume the host backs up), `conventions` (the alembic rule).

**Key rotation:** an archive is readable only by the private key matching the recipient it
was encrypted TO. Changing `backup_age_recipient` does not re-encrypt anything, so every
archive written before the change stays bound to the old key and a restore with the new
identity in place fails to decrypt it. `deploy/README.md` carries the operator steps.
