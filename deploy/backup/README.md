# Backup & Restore (T-42)

Tägliches, **verschlüsseltes** Backup des Datenbestands und eine geübte
Restore-Prozedur. Deckt die zwei zustandsbehafteten Stores ab:

- **PostgreSQL** — `pg_dump` (custom format) → `db.dump`
- **MinIO** — `mc mirror` des Buckets (Anhänge + PDFs) → `objects/`

Beides landet in **einem** age-verschlüsselten Tar-Artefakt
`antrag-<UTC-Zeitstempel>.tar.age` im `backups`-Volume. Quelle: `deployment.md §4`,
`requirements R14.5/R16`.

## Verschlüsselung (age)

Der Backup-Host kennt **nur den Public-Key** (encrypt-only). Der private Key gehört
**off-host** und wird ausschließlich zur Restore-Zeit gestellt — fällt die VM, ist
der Backup-Inhalt ohne den separat verwahrten Key wertlos.

```bash
age-keygen -o age.key          # erzeugt private key-Datei + druckt "# public key: age1..."
```

- Public-Key → `BACKUP_AGE_RECIPIENT` in `deploy/.env`.
- Private `age.key` → **off-host** sicher verwahren (Passwortmanager / HSM / getrennter
  Host). NICHT ins Repo, nicht aufs Backup-Volume.

> GPG statt age ist möglich (`gpg --encrypt -r <key>` / `gpg -d`) — age ist hier der
> Default: ein Datei-Key, kein Keyring, kein Agent.

## Konfiguration (`deploy/.env`)

| Var | Default | Zweck |
|---|---|---|
| `BACKUP_AGE_RECIPIENT` | — | age-Public-Key; **leer ⇒ backup-Service startet nicht** |
| `BACKUP_RETENTION_DAYS` | `14` | ältere Artefakte werden geprunet (`0` = nie) |
| `BACKUP_CRON` | `17 2 * * *` | busybox-cron-Spec (täglich 02:17 UTC) |
| `BACKUP_AGE_IDENTITY` | `/secrets/age.key` | privater Key im Container (nur Restore) |
| `BACKUP_OFFHOST_RSYNC_TARGET` | — | optionaler rsync-Push off-host |

DB-/MinIO-Zugang kommt aus den bestehenden `POSTGRES_*` / `MINIO_*` (kein Duplikat).

## Betrieb

Der `backup`-Service läuft im **prod-Profil** und startet `crond`:

```bash
docker compose --profile prod up -d           # backup-Service inkl.
```

Manueller Lauf (z. B. vor einem Update):

```bash
docker compose --profile backup run --rm backup backup.sh
```

Artefakte liegen im `backups`-Volume (`/backups` im Container). Mit
`BACKUP_OFFHOST_RSYNC_TARGET` wird jedes Artefakt zusätzlich off-host kopiert.

## Restore (destruktiv — Runbook)

> **Restore überschreibt die laufende DB und den MinIO-Bucket.** `restore.sh` fragt
> nach (Eingabe `RESTORE`), sofern nicht `FORCE=1`. Vorher ein frisches Backup ziehen.

1. **Privaten age-Key bereitstellen** (off-host → Stack):
   ```bash
   cp /pfad/zum/age.key deploy/backup/secrets/age.key   # gitignored, ro gemountet
   ```
2. **Stack-Stand sichern** und App pausieren (api/worker), damit kein Schreibzugriff
   während des Restores passiert:
   ```bash
   docker compose stop api worker
   ```
3. **Artefakt wählen** (neuestes zuerst):
   ```bash
   docker compose --profile backup run --rm backup ls -t /backups
   ```
4. **Restore ausführen:**
   ```bash
   docker compose --profile backup run --rm backup \
     restore.sh /backups/antrag-<ZEITSTEMPEL>.tar.age
   ```
   (CI/Smoke nutzen `-e FORCE=1`, um die Rückfrage zu überspringen.)
5. **App wieder hochfahren + prüfen:**
   ```bash
   docker compose up -d
   ../scripts/smoke.sh
   ```
6. **age.key wieder entfernen** (gehört nicht dauerhaft in den Stack):
   ```bash
   rm deploy/backup/secrets/age.key
   ```

## Restore-Test (automatisiert)

`scripts/restore-smoke.sh` beweist die volle Runde in einem Wegwerf-Stack:
Testdaten säen → `backup.sh` → Daten zerstören → `restore.sh` → DB-Zeile **und**
MinIO-Objekt zurück? Räumt am Ende `down -v` ab.

```bash
scripts/restore-smoke.sh
```

In CI als **opt-in** Job `restore-smoke` (Label `run-restore-smoke`,
`workflow_dispatch` oder `RUN_RESTORE_SMOKE=true`) — analog zum e2e-Job, damit der
Standard-PR-Lauf schlank/grün bleibt. Restore-Drift (Schema vs. Dump) fällt so
periodisch auf, statt erst im Ernstfall.
