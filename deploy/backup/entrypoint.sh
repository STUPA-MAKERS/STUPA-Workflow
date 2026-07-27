#!/usr/bin/env bash
# Entrypoint of the backup service. It writes a crontab from $BACKUP_CRON and starts
# busybox crond in the foreground. The backup then runs periodically in its own container.
# See deployment.md §4: "cron in the worker or a separate backup job" -> separate job.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# With arguments the container makes a single run instead of a cron daemon. For example:
#   docker compose --profile backup run --rm backup backup.sh
#   docker compose --profile backup run --rm -e FORCE=1 backup restore.sh <artifact>
# $PATH holds backup.sh and restore.sh under /opt/backup.
if [[ "$#" -gt 0 ]]; then
  exec "$@"
fi

CRON_SPEC="${BACKUP_CRON:-17 2 * * *}"   # default: daily at 02:17

# Check the mandatory variable at start. That gives an early and clear error instead of
# a failure at 02:17.
: "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT (age-Public-Key) nicht gesetzt}"

# Save the environment to a file that the cron job reads. A crond job does not inherit
# the environment of the service. `export -p` writes bash syntax (`declare -x …`), but
# busybox crond runs jobs with ash, which does NOT know `declare`. The crontab therefore
# starts the job under bash, which can source the file.
export -p > /etc/backup.env

crontab_file="/etc/crontabs/root"
mkdir -p "$(dirname "${crontab_file}")"
cat > "${crontab_file}" <<EOF
${CRON_SPEC} bash -c '. /etc/backup.env; ${HERE}/backup.sh' >> /proc/1/fd/1 2>&1
EOF

echo "[backup] cron: '${CRON_SPEC}' — warte auf Lauf. Manuell: docker compose run --rm backup backup.sh"
exec crond -f -l 8
