---
name: mcp
description: The antragsplattform_mcp MCP server, a standalone FastMCP package. It exposes the platform HTTP API to agents as the logged-in user via an OAuth2 Authorization-Code + PKCE browser grant. It holds 147 typed tools in antragsplattform_mcp/tools/*.py (applications/flow/forms/votes/meetings/protocols/budget/RBAC/audit) and atomic flow_*/form_* graph ops. Use when working on MCP tools, server.py, OAuth token caching, browser-grant auth, graphops, wire schemas, or the antragsplattform-mcp console entry in /mcp.
---

# antragsplattform MCP Server — `mcp/`

**Does:** A standalone Python package (`antragsplattform_mcp`) that runs a FastMCP stdio server. Agents act on the platform through its `/api` HTTP surface as the logged-in user. The package authenticates with an OAuth2 Authorization-Code + PKCE browser grant, caches the token and refreshes it automatically. The server still authorizes every action against the RBAC permissions of the user ∩ the granted scope. No tool can cast a ballot.

**Key files:**
- `antragsplattform_mcp/server.py` — the FastMCP app, the server `_INSTRUCTIONS` text and the `main()` stdio entry point. It declares NO tool of its own; it calls `tools.register_all(mcp)`.
- `antragsplattform_mcp/tools/` — the 147 tools, each a thin wrapper around `ApiClient`, split by domain: `session` (4), `applications` (15), `flow_forms` (19), `meetings` (31), `budget` (16), `finance` (9), `admin` (53). A tool carries `@group.tool`, and `tools/_common.py` holds the `ToolGroup` registrar plus the lazy `cfg()`/`api()` singletons. `tools/__init__.py` fixes the module order, which keeps the served tool list stable for agents.
- `antragsplattform_mcp/auth.py` — OAuth2 + PKCE browser grant (RFC 7636/8252): discovery, loopback `/callback` capture, code exchange, refresh, disk token cache. Synchronous. Rejects cleartext non-loopback URLs.
- `antragsplattform_mcp/client.py` — async `ApiClient` (httpx). It attaches the bearer token, retries once on 401 after a forced re-login and raises `ApiError`. The token fetch runs in a worker thread, so the event loop never blocks.
- `antragsplattform_mcp/config.py` — `Config.from_env()`: base URL (`ANTRAGSPLATTFORM_URL` or baked `_baked.py:BASE_URL`), `scope`, per-URL token cache path. `CLIENT_ID = "antragsplattform-mcp"`.
- `antragsplattform_mcp/graphops.py` — pure read-modify-write mutations on the flow-graph dict (`{states, transitions, layout}`) and on form-field lists. They raise `ValueError` for clean tool errors before any write.
- `antragsplattform_mcp/schemas.py` — Pydantic `WireModel` request bodies in camelCase wire keys that mirror the backend. Dump with `dump_create` (exclude_none) or `dump_patch` (exclude_unset).
- `pyproject.toml` — package metadata, `[project.scripts] antragsplattform-mcp = server:main`, deps `mcp`, `httpx`, `pydantic`. Python ≥3.11.
- `README.md` — setup, scope→permission table, token-cache location.

**Domain / data model:** This package owns no DB. It speaks to the platform `/api`. Local types:
- `Config` (frozen dataclass): `base_url`, `scope`, `.api` (= `base_url + /api`), `.token_path()` → `~/.config/antragsplattform-mcp/token-<sha256(base_url)[:16]>.json` (dir mode 0700, file 0600). `DEFAULT_SCOPE` = `read applications:write votes:write budget:write meetings:write forms:write flows:write admin:write`.
- Token dict: `access_token`, `refresh_token`, `expires_at` (None = non-expiring). The cache writes it atomically (temp file → `os.replace`).
- Wire schemas (`schemas.py`, `extra="allow"` for drift tolerance): `StateDef`/`StateDefPatch` (key, label i18n, kind `normal|vote`, config), `TransitionDef`/`TransitionDefPatch` (`from`/`to`, guard tree, actions, branch `pass|fail`, automatic), `FlowGroupDef` (nestable via `groupIds`, editor-only `layout.groups`), `FormFieldDef`/`FormFieldPatch` (type text…section, validation, options, visibleIf, compute), plus Gremium/Role/RoleAssignment/GroupMapping/ApplicationType/Webhook/DeadlinePolicy/BudgetNode/Expense/Transfer/Meeting/MeetingVoteOpenBody/VoteCreate/Delegation/Substitute/NotificationSettings creates+updates.
- Flow graph shape (graphops): `states[]` keyed by `key`, `transitions[]` addressed by **integer index**. The layout holds `layout.positions{key:{x,y}}` and `layout.groups[]` (acyclic, nesting via `groupIds`, each state/group in ≤1 parent). State renames cascade across transitions/positions/groups.

**API surface (tools → backend routes):**
- Auth/identity: `login`/`whoami` → `GET /auth/me` · `logout` (clears the cache) · `get_config_schemas` → `GET /admin/config-schemas`.
- Applications: `list_applications` `GET /applications` · `get_application`/`update_application`(PATCH `{data}`)/`delete_application` · `get_application_timeline`/`list_application_versions`/`get_application_form` · `create_application` `POST /applications` · `comment_application`/`list_comments` · `create_application_pdf` `POST .../pdf` · `get_job` `GET /jobs/{id}` · `list_tasks` `GET /applications/tasks`.
- Flow engine (apply): `list_transitions` `GET .../transitions` · `fire_transition` `POST /applications/{id}/transition {transitionId, note}`.
- Flow editing: `get_global_flow`/`set_global_flow` `GET|POST /admin/flow-versions/global` · atomic `flow_add_state`/`flow_update_state`/`flow_remove_state`/`flow_add_transition`/`flow_update_transition(index)`/`flow_remove_transition(index)`/`flow_set_positions`/`flow_set_group`/`flow_delete_group` (each re-reads, mutates via graphops, re-POSTs with `activate:true`).
- Forms: `get_latest_form_version`/`get_effective_form`/`create_form_version`/`set_active_form` · atomic `form_add_field`/`form_update_field`/`form_remove_field`/`form_move_field`.
- Votes: `get_vote` · `create_application_vote` · `open_vote`/`close_vote`/`cancel_vote` `POST /votes/{id}/{open|close|cancel}`. (No ballot-cast tool by design.)
- Meetings: `list_meetings`/`get_meeting`/`create_meeting`/`update_meeting`/`delete_meeting` · `get_attendance`/`set_attendance` · agenda `add_/update_/delete_agenda_item`, `reorder_agenda`, `list_assignable_agenda_items` · `create_meeting_vote`/`delete_meeting_vote`.
- Protocols: `get_or_create_protocol` `POST /meetings/{id}/protocol` · `update_protocol` PATCH `{markdown}` · `embed_protocol_votes` · `finalize_protocol` `POST /protocols/{id}/finalize` (**async render** — re-fetch until `status=final`).
- Delegations/substitutes: `list_/create_delegation`, `revoke_delegation`, `list_/create_/delete_substitute`.
- Budget: `list_budgets`(tree)/`create_/update_/delete_budget` · `get_budget_applications` · `list_/create_/update_fiscal_year` · `set_allocation` · `book_expense`(incl. invoice/payment dates, correspondent, note, paymentMethod, invoiceId)/`list_budget_expenses`/`list_expenses`(flat,paged)/`update_/delete_expense` · `create_budget_transfer` · `assign_application_budget`/`move_application_fiscal_year`.
- Invoices (#invoices): `list_/get_/create_/update_/delete_invoice` · `parse_invoice(file_path)` (ZUGFeRD/Factur-X → fields + `fileToken`) / `upload_invoice_file(file_path)` → pass `fileToken` to `create_invoice`.
- Binary downloads (invoice PDF, xlsx exports) and applicant magic-link / OAuth browser routes stay unexposed by design.
- Admin/RBAC: gremien, gremium-roles, gremium-memberships, roles, role-assignments, principals, group-mappings, permissions, application-types, webhooks, deadline-policies, gremium mail-recipients, notification settings (`/admin/notification-settings`) and per-user preferences (`/notifications/preferences`).
- Corporate design: `list_cd_variants`/`create_`/`update_`/`delete_cd_variant`, `add_cd_variant_vendored_logo`, `delete_cd_variant_logo` — all `admin.cd_variants`. `list_cd_variant_options` hits `GET /cd-variants` instead and takes `admin.gremien` OR `admin.cd_variants`, so a gremien admin can read `cdVariantId` without the CD permission. A logo **upload** has no tool (multipart); use the web UI or a vendored name.
- Site config: `get_site_config`/`set_site_config_draft` (PUT draft)/`activate_site_config`.
- Audit: `list_audit` `GET /admin/audit` (keyset-paged via `before`) · `verify_audit_chain` `GET /admin/audit/verify`.

**Conventions & gotchas:**
- **Hard rule:** the package has no `cast_ballot` tool by design. The server never grants `vote.cast`. Agents manage votes, but they never vote.
- The server enforces every permission. A 403 means the user lacks the permission. That is expected, not a bug. Read (`get_*`/`list_*`) before you write.
- **Prefer the atomic flow/form ops** over `set_global_flow`/`create_form_version`. Each op re-reads the current document, applies one change via `graphops`, and POSTs a new **activated** version. Transition ops use the integer **index** from `get_global_flow`. In `flow_update_transition`/`update_field`/`update_state`, a patch with an explicit `null` value **removes** that key (for example `guard: null` drops the guard).
- Wire keys are **camelCase**, and the backend also accepts aliases. `schemas.py` uses `extra="allow"`, so new backend fields pass through without code changes. Money amounts are decimal strings (`"1500.00"`). Ids are UUID strings, but never show a raw UUID to a human (see `[[no-uuids-in-ui]]`).
- Auth security design: the client rejects cleartext `http://` unless the host is loopback (`localhost`/`127.0.0.1`/`[::1]`). The callback checks the PKCE `state` value, which blocks CSRF. The client creates the token cache file atomically with mode 0600. On 401 it forces one re-login and retries exactly once.
- The platform injects `_baked.py` when a user downloads the package from a running instance. That file wires `BASE_URL` to `PUBLIC_BASE_URL`. A plain repo checkout has no `_baked.py`, so `ANTRAGSPLATTFORM_URL` is mandatory and `main()` fails fast when it is missing.
- `finalize_protocol` renders asynchronously (arq). Poll the protocol again. A return to `status=draft` means that the render failed.
- The client normalizes API errors to `ApiError(status, message)` from the RFC-9457 problem-detail `detail`/`title` of the platform.

**Related:** be-auth, be-flow, be-forms, be-voting, be-budget, be-livevote, be-audit
