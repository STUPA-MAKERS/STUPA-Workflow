---
name: mcp
description: The antragsplattform_mcp MCP server — a standalone FastMCP package that exposes the platform HTTP API to agents as the logged-in user via OAuth2 Authorization-Code + PKCE browser grant, with ~130 typed tools (applications/flow/forms/votes/meetings/protocols/budget/RBAC/audit) and atomic flow_*/form_* graph ops. Use when working on MCP tools, server.py, OAuth token caching, browser-grant auth, graphops, wire schemas, or the antragsplattform-mcp console entry in /mcp.
---

# antragsplattform MCP Server — `mcp/`

**Does:** A standalone Python package (`antragsplattform_mcp`) running a FastMCP stdio server that lets agents act on the platform via its `/api` HTTP surface as the logged-in user. Authenticates with an OAuth2 Authorization-Code + PKCE browser grant (token cached/auto-refreshed); every action is still authorized server-side by the user's RBAC permissions ∩ the granted scope, and no tool can cast a ballot.

**Key files:**
- `antragsplattform_mcp/server.py` — the FastMCP app + all ~130 `@mcp.tool()` functions; thin wrappers that call `ApiClient`. Holds the server `_INSTRUCTIONS` text and `main()` stdio entry point.
- `antragsplattform_mcp/auth.py` — OAuth2 + PKCE browser grant (RFC 7636/8252): discovery, loopback `/callback` capture, code exchange, refresh, disk token cache. Synchronous; rejects cleartext non-loopback URLs.
- `antragsplattform_mcp/client.py` — async `ApiClient` (httpx) attaching the bearer token, retrying once on 401 after a forced re-login; raises `ApiError`. Token fetch runs in a worker thread so the event loop never blocks.
- `antragsplattform_mcp/config.py` — `Config.from_env()`: base URL (`ANTRAGSPLATTFORM_URL` or baked `_baked.py:BASE_URL`), `scope`, per-URL token cache path. `CLIENT_ID = "antragsplattform-mcp"`.
- `antragsplattform_mcp/graphops.py` — pure read-modify-write mutations on the flow-graph dict (`{states, transitions, layout}`) and on form-field lists; raise `ValueError` for clean tool errors before any write.
- `antragsplattform_mcp/schemas.py` — Pydantic `WireModel` request bodies in camelCase wire keys mirroring the backend; `dump_create` (exclude_none) / `dump_patch` (exclude_unset).
- `pyproject.toml` — package metadata; `[project.scripts] antragsplattform-mcp = server:main`; deps `mcp`, `httpx`, `pydantic`. Python ≥3.11.
- `README.md` — setup, scope→permission table, token-cache location.

**Domain / data model:** This package owns no DB; it speaks to the platform `/api`. Local types:
- `Config` (frozen dataclass): `base_url`, `scope`, `.api` (= `base_url + /api`), `.token_path()` → `~/.config/antragsplattform-mcp/token-<sha256(base_url)[:16]>.json` (dir mode 0700, file 0600). `DEFAULT_SCOPE` = `read applications:write votes:write budget:write meetings:write forms:write flows:write admin:write`.
- Token dict: `access_token`, `refresh_token`, `expires_at` (None = non-expiring); persisted atomically (temp file → `os.replace`).
- Wire schemas (`schemas.py`, `extra="allow"` for drift tolerance): `StateDef`/`StateDefPatch` (key, label i18n, kind `normal|vote`, config), `TransitionDef`/`TransitionDefPatch` (`from`/`to`, guard tree, actions, branch `pass|fail`, automatic), `FlowGroupDef` (nestable via `groupIds`, editor-only `layout.groups`), `FormFieldDef`/`FormFieldPatch` (type text…section, validation, options, visibleIf, compute), plus Gremium/Role/RoleAssignment/GroupMapping/ApplicationType/Webhook/DeadlinePolicy/BudgetNode/Expense/Transfer/Account/Meeting/MeetingVoteOpenBody/VoteCreate/Delegation/Substitute/NotificationSettings creates+updates.
- Flow graph shape (graphops): `states[]` keyed by `key`; `transitions[]` addressed by **integer index**; `layout.positions{key:{x,y}}` and `layout.groups[]` (acyclic, nesting via `groupIds`, each state/group in ≤1 parent). State renames cascade across transitions/positions/groups.

**API surface (tools → backend routes):**
- Auth/identity: `login`/`whoami` → `GET /auth/me`; `logout` (clears cache); `get_config_schemas` → `GET /admin/config-schemas`.
- Applications: `list_applications` `GET /applications`; `get_application`/`update_application`(PATCH `{data}`)/`delete_application`; `get_application_timeline`/`list_application_versions`/`get_application_form`; `create_application` `POST /applications`; `comment_application`/`list_comments`; `create_application_pdf` `POST .../pdf`; `get_job` `GET /jobs/{id}`; `list_tasks` `GET /applications/tasks`.
- Flow engine (apply): `list_transitions` `GET .../transitions`; `fire_transition` `POST /applications/{id}/transition {transitionId, note}`.
- Flow editing: `get_global_flow`/`set_global_flow` `GET|POST /admin/flow-versions/global`; atomic `flow_add_state`/`flow_update_state`/`flow_remove_state`/`flow_add_transition`/`flow_update_transition(index)`/`flow_remove_transition(index)`/`flow_set_positions`/`flow_set_group`/`flow_delete_group` (each re-reads, mutates via graphops, re-POSTs with `activate:true`).
- Forms: `get_latest_form_version`/`get_effective_form`/`create_form_version`/`set_active_form`; atomic `form_add_field`/`form_update_field`/`form_remove_field`/`form_move_field`.
- Votes: `get_vote`; `create_application_vote`; `open_vote`/`close_vote`/`cancel_vote` `POST /votes/{id}/{open|close|cancel}`. (No ballot-cast tool by design.)
- Meetings: `list_meetings`/`get_meeting`/`create_meeting`/`update_meeting`/`delete_meeting`; `get_attendance`/`set_attendance`; agenda `add_/update_/delete_agenda_item`, `reorder_agenda`, `list_assignable_agenda_items`; `create_meeting_vote`/`delete_meeting_vote`.
- Protocols: `get_or_create_protocol` `POST /meetings/{id}/protocol`; `update_protocol` PATCH `{markdown}`; `embed_protocol_votes`; `finalize_protocol` `POST /protocols/{id}/finalize` (**async render** — re-fetch until `status=final`).
- Delegations/substitutes: `list_/create_delegation`, `revoke_delegation`, `list_/create_/delete_substitute`.
- Budget: `list_budgets`(tree)/`create_/update_/delete_budget`; `get_budget_applications`; `list_/create_/update_fiscal_year`; `set_allocation`; `book_expense`/`list_budget_expenses`/`update_/delete_expense`; `create_budget_transfer`; `list_/create_/update_/delete_account`; `assign_application_budget`/`move_application_fiscal_year`.
- Admin/RBAC: gremien, gremium-roles, gremium-memberships, roles, role-assignments, principals, group-mappings, permissions, application-types, webhooks, deadline-policies, gremium mail-recipients, notification settings/preferences (all under `/admin/...`).
- Site config: `get_site_config`/`set_site_config_draft` (PUT draft)/`activate_site_config`.
- Audit: `list_audit` `GET /admin/audit` (keyset-paged via `before`); `verify_audit_chain` `GET /admin/audit/verify`.

**Conventions & gotchas:**
- **Hard rule:** there is intentionally no `cast_ballot` tool, and the server never grants `vote.cast` — agents manage votes but never vote.
- All rights are server-enforced: a 403 means the user lacks the permission (expected, not a bug). Read (`get_*`/`list_*`) before writing.
- **Atomic flow/form ops are preferred** over `set_global_flow`/`create_form_version`; each op re-reads the current document, applies one change via `graphops`, and POSTs a new **activated** version. Transition ops use the integer **index** from `get_global_flow`; `flow_update_transition`/`update_field`/`update_state` patches with an explicit `null` value **remove** that key (e.g. `guard: null` drops the guard).
- Wire keys are **camelCase** (backend accepts aliases); `schemas.py` uses `extra="allow"` so new backend fields pass through without code changes. Money amounts are decimal strings (`"1500.00"`); ids are UUID strings — but never surface raw UUIDs to humans (see `[[no-uuids-in-ui]]`).
- Auth security design: cleartext `http://` is rejected unless host is loopback (`localhost`/`127.0.0.1`/`[::1]`); PKCE `state` is CSRF-checked on the callback; token cache file is created mode 0600 atomically; on 401 the client forces one re-login and retries exactly once.
- `_baked.py` is injected when the package is downloaded from a running platform (auto-wires `BASE_URL` to `PUBLIC_BASE_URL`); a plain repo checkout has none, so `ANTRAGSPLATTFORM_URL` is required and `main()` fails fast if missing.
- `finalize_protocol` is async (arq render): re-poll the protocol; a fall back to `status=draft` means the render failed.
- Errors from the API are normalized to `ApiError(status, message)` using the platform's RFC-9457 problem-detail `detail`/`title`.

**Related:** be-auth, be-flow, be-forms, be-voting, be-budget, be-livevote, be-audit
