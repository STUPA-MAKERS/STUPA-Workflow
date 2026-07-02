# antragsplattform admin-cli

A full-screen terminal **command REPL** (prompt_toolkit, mouse + keyboard) to administer the
platform **directly against the Dockerised Postgres** — a scrolling log, slash-commands with
Tab-completion, inline selectors/forms, and click-to-pop-out record details.

Manage:
- **Users** (principals): search, (de)activate, delete, view/grant/revoke role assignments.
- **Roles & permissions**: create / rename / delete roles, edit a role's permission set in a
  scrolling form.
- **OIDC group-mappings**: create / edit / delete `oidc_group → role [@ gremium]` mappings.
- **Audit log**: read-only, paged, filtered, with day separators, resolved actor names,
  colour-coded actions and a full-JSON pop-out per entry.

> ⚠️ **Direct DB access bypasses the API** → it writes **no `audit_entry`** and skips RBAC guards
> (e.g. the "admins cannot remove their own admin role" check). Every mutation asks for
> confirmation; double-check the target. Rows created here are tagged `granted_by = 'admin-cli'`.

## Run

From the repo root:

```bash
./scripts/admin-cli.sh              # full-screen REPL
./scripts/admin-cli.sh --read-only  # writes disabled (browse only)
./scripts/admin-cli.sh --check      # test DB connectivity, then exit
```

The wrapper creates/updates a dedicated venv in `admin-cli/.venv` on first run (and whenever
`pyproject.toml` changes), then launches the installed `antragsplattform-admin` console script.

## Database access (automatic)

Resolution order — the first one that answers wins:

1. **`$DATABASE_URL`** in the environment — explicit override.
2. **`deploy/.env`** — the stack's own `DATABASE_URL` (or `POSTGRES_*` variables), rewritten to
   `localhost:<host port>`: the `+asyncpg` driver suffix is stripped and host/port replaced with
   the postgres host-port published in `deploy/docker-compose.yml` (`127.0.0.1:5433:5432` → `5433`).
   Works out of the box on the VM; from elsewhere, forward the port first:
   `ssh -L 5433:127.0.0.1:5433 <vm>`.
3. **`docker compose exec postgres psql`** — fallback when no direct connection is possible
   (no psycopg needed; same model as `scripts/remove-admin-role.sh`).

`/connect` retries the resolution at runtime; `/status` shows what is in use.

Environment overrides: `DATABASE_URL`, `COMPOSE_FILE` (default `deploy/docker-compose.yml`),
`ENV_FILE` (default `<compose dir>/.env`), `POSTGRES_SERVICE` (default `postgres`),
`POSTGRES_USER`, `POSTGRES_DB`, `PYTHON`.

## Commands

```
/users [search]              list users
/user [term] [action]        show · roles · grant · revoke · activate/deactivate · delete
/roles                       list roles (permission + assignment counts)
/role [key] [action]         show · perms · rename · delete
/new-role [key]              create a role
/mappings                    list OIDC group-mappings
/mapping [group] [action]    show · edit · delete
/new-mapping                 create a mapping (form)
/audit [key=value …]         action= actor= target= limit=   (bare word = action filter)
/more                        load older audit entries
/status · /connect           connection info · reconnect
/clear · /help · /quit
```

Commands without arguments open an **inline selector** (type to search, `↑/↓`, digits, Enter,
Esc); multi-field edits open a **form** (`↑/↓` move, `←/→`/Space cycle, Enter applies). Every
domain row in the log is clickable: hover highlights it, a click **pops out the full record**
(audit entries show the pretty-printed `data` JSON), Esc closes.

### Keys / mouse
`Tab` completes commands and arguments · `PgUp`/`PgDn` scroll the log · mouse wheel scrolls ·
`Ctrl-C` cancels the open panel (or clears the input) · `Ctrl-D`/`Ctrl-Q`/`/quit` exit.
The bottom toolbar shows the connection, entity counts and the read-only/direct-db badge —
its segments are clickable shortcuts.

## Notes
- The permission catalogue is vendored in `antragsplattform_admin/permissions.py` — keep it in
  sync with `backend/app/shared/permissions.py`. The role editor also shows any permission
  already present in the DB even if missing from the vendored list.
- `vote.cast` is human-only (never grantable via the API). The permission form flags it and asks
  for explicit confirmation before granting it directly in the DB — don't.
