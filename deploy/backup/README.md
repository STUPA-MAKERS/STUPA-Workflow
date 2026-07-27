# Backup and restore (T-42)

A daily, **encrypted** backup of the data plus a practiced restore procedure. It covers the
two stateful stores:

- **PostgreSQL** — `pg_dump` (custom format) → `db.dump`
- **MinIO** — `mc mirror` of the bucket (attachments and PDFs) → `objects/`

Both go into **one** age-encrypted tar artifact `antrag-<UTC timestamp>.tar.age` in the
`backups` volume. Sources: `deployment.md §4` and `requirements R14.5/R16`.

## Encryption (age)

The backup host knows **only the public key**, so it can encrypt but not decrypt. The private
key belongs **off host**. Supply it at restore time only. If you lose the VM, the backup
content is worthless without the key that you keep apart.

```bash
age-keygen -o age.key          # creates the private key file + prints "# public key: age1..."
```

- Public key → `BACKUP_AGE_RECIPIENT` in `deploy/.env`.
- Keep the private `age.key` safe **off host**: password manager, HSM or a separate host. Do
  NOT put it in the repository or on the backup volume.

> GPG works instead of age (`gpg --encrypt -r <key>` / `gpg -d`). age is the default here
> because it needs one key file, no keyring and no agent.

## Configuration (`deploy/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `BACKUP_AGE_RECIPIENT` | — | age public key. **Empty ⇒ the backup service does not start** |
| `BACKUP_RETENTION_DAYS` | `14` | the job prunes older artifacts (`0` = never) |
| `BACKUP_CRON` | `17 2 * * *` | busybox cron spec (daily at 02:17 UTC) |
| `BACKUP_AGE_IDENTITY` | `/secrets/age.key` | private key in the container (restore only) |
| `BACKUP_OFFHOST_RSYNC_TARGET` | — | optional rsync push off host |

The database and MinIO access come from the existing `POSTGRES_*` and `MINIO_*` values. There
is no second copy.

## Operation

The `backup` service runs in the **prod profile** and starts `crond`:

```bash
docker compose --profile prod up -d           # includes the backup service
```

Run it by hand, for example before an update:

```bash
docker compose --profile backup run --rm backup backup.sh
```

The artifacts stay in the `backups` volume (`/backups` in the container). With
`BACKUP_OFFHOST_RSYNC_TARGET` the job also copies every artifact off host.

## Restore (destructive — runbook)

> **A restore overwrites the running database and the MinIO bucket.** `restore.sh` asks first
> and waits for the input `RESTORE`, unless you set `FORCE=1`. Take a fresh backup before you
> start.

1. **Supply the private age key** (off host → stack):
   ```bash
   cp /path/to/age.key deploy/backup/secrets/age.key   # gitignored, mounted read-only
   ```
2. **Save the state of the stack** and pause the application (api and worker), so that
   nothing writes during the restore:
   ```bash
   docker compose stop api worker
   ```
3. **Choose an artifact** (newest first):
   ```bash
   docker compose --profile backup run --rm backup ls -t /backups
   ```
4. **Run the restore:**
   ```bash
   docker compose --profile backup run --rm backup \
     restore.sh /backups/antrag-<TIMESTAMP>.tar.age
   ```
   (CI and the smoke test pass `-e FORCE=1` to skip the question.)
5. **Start the application again and check it:**
   ```bash
   docker compose up -d
   ../scripts/smoke.sh
   ```
6. **Remove `age.key` again.** It must not stay in the stack:
   ```bash
   rm deploy/backup/secrets/age.key
   ```

## Restore test (automated)

`scripts/restore-smoke.sh` proves the full round in a throwaway stack. It seeds test data,
runs `backup.sh` and destroys the data. It then runs `restore.sh` and checks that the database
row **and** the MinIO object are back. At the end it cleans up with `down -v`.

```bash
scripts/restore-smoke.sh
```

In CI this is the **opt-in** job `restore-smoke`. Start it with the label
`run-restore-smoke`, with `workflow_dispatch` or with `RUN_RESTORE_SMOKE=true`. This matches
the e2e job and keeps the standard PR run short and green. Restore drift between schema and
dump therefore shows up regularly, and not for the first time in an emergency.
