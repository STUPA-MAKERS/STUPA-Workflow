#!/usr/bin/env bash
# Remove all admin role assignments from a principal, directly in the prod DB.
#
# Usage (on the prod host, from the repo root):
#   ./scripts/remove-admin-role.sh <principal-uuid>
#
# Runs psql inside the compose postgres service. Shows the matching rows and
# asks for confirmation before deleting. Note: this bypasses the API layer,
# so no audit_log entry is written and the "admins cannot remove their own
# admin role" guard does not apply — double-check the target.
set -euo pipefail

PRINCIPAL_ID="${1:?usage: $0 <principal-uuid>}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.yml}"

if ! [[ "$PRINCIPAL_ID" =~ ^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$ ]]; then
    echo "error: '$PRINCIPAL_ID' is not a UUID" >&2
    exit 1
fi

psql_run() {
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
        psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-$(docker compose -f "$COMPOSE_FILE" exec -T postgres printenv POSTGRES_USER)}" \
        -d "${POSTGRES_DB:-$(docker compose -f "$COMPOSE_FILE" exec -T postgres printenv POSTGRES_DB)}" "$@"
}

# The given UUID may be the principal.id or the OIDC sub (Keycloak user id).
MATCH="(p.id = '${PRINCIPAL_ID}' OR p.sub = '${PRINCIPAL_ID}')"

echo "== Principal =="
psql_run -c "SELECT id, sub, email, display_name, active
             FROM principal p WHERE ${MATCH};"

echo "== Admin role assignments to be deleted =="
psql_run -c "SELECT ra.id, ra.gremium_id, ra.granted_by, ra.valid_from, ra.valid_until
             FROM role_assignment ra
             JOIN role r ON r.id = ra.role_id
             JOIN principal p ON p.id = ra.principal_id
             WHERE r.key = 'admin' AND ${MATCH};"

read -r -p "Delete these assignments? [y/N] " answer
if [[ "$answer" != [yY] ]]; then
    echo "aborted"
    exit 1
fi

psql_run -c "DELETE FROM role_assignment ra
             USING role r
             WHERE r.id = ra.role_id
               AND r.key = 'admin'
               AND ra.principal_id = '${PRINCIPAL_ID}';"

echo "done"
