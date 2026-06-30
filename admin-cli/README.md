# antragsplattform admin-cli

A fancy full-screen terminal UI (prompt_toolkit, **mouse + keyboard**) to administer the platform
**directly against the Dockerised Postgres** — the same access model as
`scripts/remove-admin-role.sh`.

Manage:
- **Users** (principals): search, (de)activate, delete, and view/grant/revoke their role assignments.
- **Roles & permissions**: create / rename / delete roles, toggle each role's permissions from the
  catalogue.
- **OIDC group-mappings**: create / edit / delete `oidc_group → role [@ gremium]` mappings.
- **Audit log**: read-only, paged, filter by action.

> ⚠️ **Direct DB access bypasses the API** → it writes **no `audit_entry`** and skips RBAC guards
> (e.g. the "admins cannot remove their own admin role" check). Every mutation asks for confirmation;
> double-check the target. Rows created here are tagged `granted_by = 'admin-cli'`.

## Run

From the repo root, on the host that runs the stack:

```bash
./scripts/admin-cli.sh              # full-screen TUI
./scripts/admin-cli.sh --read-only  # writes disabled (browse only)
./scripts/admin-cli.sh --check      # just test DB connectivity, then exit
```

The wrapper creates/updates a dedicated venv in `admin-cli/.venv` on first run (and whenever
`pyproject.toml` changes), then launches the installed `antragsplattform-admin` console script.

### Layout
Top tab bar switches section (Users / Roles / OIDC mappings / Audit). Users/Roles/OIDC are
**master-detail**: a left list of items + a right pane whose sub-tabs depend on the selection
(user → Roles / Actions; role → Permissions / Users / Actions; mapping → Actions). Moving the
list cursor updates the right pane live. Audit is a single full-width, paged, formatted table.

### Keys / mouse
- Click anything (tabs, sub-tabs, list rows, buttons). `Ctrl-←`/`Ctrl-→` switch section tabs,
  `Tab`/`Shift-Tab` move focus, `↑/↓` within lists, `Enter`/`Space` activate, mouse wheel scrolls
  the audit log. `F5` refresh, `Ctrl-Q` quit.

## Database access (auto-selected)

- **`DATABASE_URL` set** → direct connection via `psycopg` (e.g. when run inside a container or
  with a published Postgres port).
- **otherwise** → `docker compose -f $COMPOSE_FILE exec -T $POSTGRES_SERVICE psql` against the
  running stack. No host port needed. Credentials come from `POSTGRES_USER`/`POSTGRES_DB` or, if
  unset, are read from the container's environment.

Environment overrides: `COMPOSE_FILE` (default `deploy/docker-compose.yml`), `POSTGRES_SERVICE`
(default `postgres`), `POSTGRES_USER`, `POSTGRES_DB`, `DATABASE_URL`, `PYTHON`.

## Notes
- The permission catalogue is vendored in `antragsplattform_admin/permissions.py` — keep it in
  sync with `backend/app/shared/permissions.py`. The role editor also shows any permission already
  present in the DB even if missing from the vendored list.
- `vote.cast` is human-only (never grantable via the API). The editor flags it; the direct-DB path
  does not hard-block it — don't assign it.
