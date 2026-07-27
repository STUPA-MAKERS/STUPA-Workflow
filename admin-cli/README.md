# antragsplattform admin-cli

A full-screen terminal **command REPL** (prompt_toolkit, mouse + keyboard) that administers the
platform **directly against the Dockerized Postgres**. It gives you a scrolling log,
slash-commands with Tab-completion, inline selectors and forms, and click-to-pop-out record
details.

Manage:
- **Users** (principals): search, (de)activate, delete, view/grant/revoke role assignments.
- **Roles & permissions**: create / rename / delete roles, edit a role's permission set in a
  scrolling form.
- **OIDC group-mappings**: create / edit / delete `oidc_group → role [@ gremium]` mappings.
- **Audit log**: read-only, paged, filtered, with day separators, resolved actor names,
  color-coded actions and a full-JSON pop-out per entry.

> ⚠️ **Direct DB access bypasses the API.** It writes **no `audit_entry`** and skips the RBAC
> guards, for example the "admins cannot remove their own admin role" check. Every mutation asks
> for confirmation. Check the target twice. Rows created here carry `granted_by = 'admin-cli'`.

## Run

From the repo root:

```bash
./scripts/admin-cli.sh              # full-screen REPL
./scripts/admin-cli.sh --read-only  # writes disabled (browse only)
./scripts/admin-cli.sh --check      # test DB connectivity, then exit
```

On the first run the wrapper creates a dedicated venv in `admin-cli/.venv`. It updates that venv
whenever `pyproject.toml` changes. It then starts the installed `antragsplattform-admin` console
script.

## Database access (automatic)

Resolution order — the first one that answers wins:

1. **`$DATABASE_URL`** in the environment — explicit override.
2. **`deploy/.env`** — the stack's own `DATABASE_URL`, or the `POSTGRES_*` variables, rewritten
   to `localhost:<host port>`. The CLI drops the `+asyncpg` driver suffix. It replaces host and
   port with the postgres host-port published in `deploy/docker-compose.yml`
   (`127.0.0.1:5433:5432` → `5433`). This works out of the box on the VM. From another machine,
   forward the port first: `ssh -L 5433:127.0.0.1:5433 <vm>`.
3. **`docker compose exec postgres psql`** — the fallback when no direct connection works. It
   needs no psycopg and follows the same model as `scripts/remove-admin-role.sh`.

`/connect` retries the resolution at runtime. `/status` shows what is in use.

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

A command without arguments opens an **inline selector**: type to search, then use `↑/↓`, the
digits, Enter or Esc. A multi-field edit opens a **form**: `↑/↓` moves, `←/→` and Space cycle a
value, Enter applies. Every domain row in the log is clickable. Hover highlights the row. A
click **pops out the full record**, and an audit entry then shows its pretty-printed `data`
JSON. Esc closes the pop-out.

### Keys / mouse
`Tab` completes commands and arguments · `PgUp`/`PgDn` scroll the log · mouse wheel scrolls ·
`Ctrl-C` cancels the open panel (or clears the input) · `Ctrl-D`/`Ctrl-Q`/`/quit` exit.
The bottom toolbar shows the connection, the entity counts and the read-only/direct-db badge.
Its segments are clickable shortcuts.

## Notes
- The permission catalog is vendored in `antragsplattform_admin/permissions.py`. Keep it in sync
  with `backend/app/shared/permissions.py`. The role editor also shows any permission that the DB
  already holds, even when the vendored list misses it.
- `vote.cast` is human-only. The API never grants it. The permission form flags it and asks for
  an explicit confirmation before it writes the grant straight into the DB. Do not grant it.
