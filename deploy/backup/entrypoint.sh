#!/usr/bin/env bash
# Entrypoint des backup-Service: schreibt eine Crontab aus $BACKUP_CRON und startet
# busybox-crond im Vordergrund. So läuft das Backup periodisch im eigenen Container
# (deployment.md §4: "Cron im worker oder separater Backup-Job" -> separater Job).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Mit Argumenten als einmaliger Lauf nutzen (One-Shot statt Cron-Daemon), z. B.:
#   docker compose --profile backup run --rm backup backup.sh
#   docker compose --profile backup run --rm -e FORCE=1 backup restore.sh <artefakt>
# backup.sh/restore.sh liegen via $PATH (/opt/backup) bereit.
if [[ "$#" -gt 0 ]]; then
  exec "$@"
fi

CRON_SPEC="${BACKUP_CRON:-17 2 * * *}"   # Default: täglich 02:17

# Beim Start einmal validieren, dass die Pflicht-Variable da ist -> früher, klarer
# Fehler statt erst um 02:17.
: "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT (age-Public-Key) nicht gesetzt}"

# Env in eine Datei sichern, die der cron-Job einliest (crond-Jobs erben die
# Service-Umgebung nicht).
export -p > /etc/backup.env

crontab_file="/etc/crontabs/root"
mkdir -p "$(dirname "${crontab_file}")"
cat > "${crontab_file}" <<EOF
${CRON_SPEC} . /etc/backup.env; ${HERE}/backup.sh >> /proc/1/fd/1 2>&1
EOF

echo "[backup] cron: '${CRON_SPEC}' — warte auf Lauf. Manuell: docker compose run --rm backup backup.sh"
exec crond -f -l 8
