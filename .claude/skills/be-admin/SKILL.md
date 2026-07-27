---
name: be-admin
description: Admin/config API — gremien, gremium-roles+memberships, application-types, the single global flow version, RBAC (roles/role-assignments/group-mappings/principals), webhooks, and versioned site-config/branding draft→activate (incl. public branding + PWA manifest). One permission per /admin/ page (admin.gremien/.types/.site/.roles/.users/.group_mappings/.gremium_roles, webhook.manage). Use when working on /admin routes, ConfigService, SiteConfigService, GremiumRoleService, Branding, or config versioning in backend/app/modules/admin.
---

# Admin / Config Surface — `backend/app/modules/admin`

**Does:** Server-authoritative CRUD for the platform config. It covers gremien with their per-gremium roles and memberships, application-types, and the one global flow version. It also covers RBAC (roles, role-assignments, group-mappings, principal activation), webhooks, and versioned branding/site-config with a draft→activate lifecycle. Every mutation writes an audit entry in the same transaction. Config-versioned entities (flow, site-config) also snapshot to `config_revision`.

**Key files:**
- `router.py` — three routers: `router` (prefix `/admin`, per-page permission gates), `public_router` (auth-free `/site-config` + `/manifest.webmanifest`), `authed_router` (auth-only `/gremien` dropdown source, no admin right). Declares all per-page permission `Depends` constants.
- `service.py` — `ConfigService`: gremien, application-types, global flow version, roles/assignments/group-mappings/principals, webhooks. Mapper helpers at bottom.
- `site_config_service.py` — `SiteConfigService`: branding draft/activate/restore + `public()` + `manifest()` (dynamic PWA manifest, single source of truth).
- `gremium_roles.py` — `GremiumRoleService` (per-gremium roles + time-bounded memberships, overlap invariant) plus RBAC resolver helpers `active_gremium_roles`, `gremium_ids_with_permission`, `gremium_member_ids`, `intervals_overlap`, and `FORCED_GREMIUM_ROLES`.
- `branding.py` — `Branding` Pydantic schema: logos (image-only, no SVG, magic-byte sniffed, 2 MB cap), footer columns/links, legal links, i18n freetexts. The security contract lives here.
- `models.py` — SQLAlchemy: `Gremium`, `GremiumRole`, `GremiumMembership`, `MailList`, `ApplicationType`, `Webhook`, `WebhookDelivery`, `SiteConfigVersion`.
- `schemas.py` — camelCase DTOs (`populate_by_name`, `serialization_alias` on Out models).

**Domain / data model:**
- `gremium` — a Gremium (student-government body). `slug` unique, `cd_variant` (stupa/asta/echo/makers/report → pytex CD), `default_lang`, vote-delegation knobs (`allow_vote_delegation`, `delegation_lead_minutes`, `delegation_allow_external`), `quorum_percent` (0–100, nullable, explicitly clearable via `model_fields_set`). The service seeds the forced gremium-roles when it creates a gremium.
- `gremium_role` — per-gremium role set, **separate** from global `role`. `(gremium_id, key)` unique. `permissions` JSONB from the 4-key gremium catalogue: `session.manage`, `vote.manage`, `vote.cast`, `protocol.write`. Forced roles `vorstand`/`manager` (all 4) and `member` (vote.cast only) exist in every gremium. Nobody can delete them, and the list route backfills them lazily.
- `gremium_membership` — time-bounded (`valid_from`/`valid_until`, half-open `[from,until)`) link principal→gremium_role. Invariant: at most one active role per (principal, gremium) at any instant. The service rejects overlaps and allows adjacent windows. Role FK is `RESTRICT`.
- `application_type` — `key` unique, `name_i18n`, `has_budget`, `comparison_offers` JSONB, `retention_months` (DSGVO, nullable=global default), `active_form_version_id` (circular FK, use_alter). Delete is 409 if any application references it.
- `mail_list` — per-gremium recipients. The canonical `name='protocol'` row holds extra protocol recipients (PUT replaces all rows).
- `webhook` — `name/url/events` (whitelist `EventName`), server-generated `secret` (32 bytes, HMAC signing, never returned), `active`. `webhook_delivery` — worker-written. Status pending/ok/failed/dead, unique `(webhook_id, idempotency_key)`, pickup index `(status, next_at)`.
- `site_config_version` — versioned branding. `version` unique, partial-unique one `active` row (`WHERE active`), `branding` JSONB, `created_by`=OIDC sub. Draft = latest inactive version. Activate flips `active`.
- Global flow: there is exactly **one** flow for all types (`flow_version` etc. live in the `flow` module). Each save creates a new immutable version. That save re-pins ALL running applications by state **key** to the newest version (dropped keys → initial state). The system never deletes a version.
- RBAC rows (`role`, `role_permission`, `role_assignment`, `group_mapping`, `principal`) live in the `auth` module. The admin module only does their CRUD.

**API surface:**
- `GET /api/admin/config-schemas` — JSON-schemas for FE editors (any admin area).
- `GET|POST /api/admin/gremien`, `PATCH|DELETE /api/admin/gremien/{id}`, `GET|PUT /api/admin/gremien/{id}/mail-recipients` — gremien CRUD + protocol recipients (admin.gremien).
- `GET|POST /api/admin/gremien/{id}/roles`, `PATCH|DELETE /api/admin/gremium-roles/{id}` — per-gremium roles (admin.gremium_roles to write, admin.gremien may also list).
- `GET|POST /api/admin/gremien/{id}/memberships`, `DELETE /api/admin/gremium-memberships/{id}` — memberships (admin.gremien).
- `GET /api/gremien` — auth-only gremien dropdown source (no admin right, `authed_router`).
- `GET|POST /api/admin/application-types`, `PATCH /api/admin/application-types/{id}`, `DELETE` (admin.types, delete needs admin.types_delete).
- `GET|POST /api/admin/flow-versions/global` — read/create the single global flow (read also allowed to flow.configure/budget.structure).
- `GET /api/admin/principals`, `PATCH /api/admin/principals/{id}` (activate/deactivate), `GET /api/admin/permissions` (key catalogue), `GET|POST /api/admin/roles`, `PATCH|DELETE /api/admin/roles/{id}` (admin.roles, admin/member protected).
- `GET|POST /api/admin/role-assignments`, `PATCH|DELETE /api/admin/role-assignments/{id}` (admin.users, create/delete fire assignment-changed mail in background).
- `GET|POST /api/admin/group-mappings`, `PATCH|DELETE /api/admin/group-mappings/{id}` (admin.group_mappings).
- `GET|POST /api/admin/webhooks`, `PATCH /api/admin/webhooks/{id}` (webhook.manage, list also flow.configure).
- `GET /api/admin/site-config`, `PUT /api/admin/site-config/draft`, `POST /api/admin/site-config/activate` (admin.site).
- `GET /api/site-config` (auth-free public branding, `Cache-Control: public, max-age=300`), `GET /api/manifest.webmanifest` (auth-free dynamic PWA manifest).

**Conventions & gotchas:**
- **One permission per admin page.** Migration 0017 split `admin.config` into `admin.gremien/.types/.site/.roles`. A later per-page split added `admin.users/.group_mappings/.gremium_roles/.delegations/.deadlines`. Reads shared across pages use `require_any_permission(...)`, for example `_FLOW_READABLE`, `_ROLES_READ`, and `_GREMIEN_OR_USERS`. Writes always gate on the strict key. The router enforces RBAC through `require_principal`. The FE is UX only.
- Two **separate** role systems exist: global `role`/`role_assignment` (16-permission catalogue from `app.shared.permissions.PERMISSION_CATALOGUE`) and `gremium_role` (4-key session catalogue, resolved from the active membership). Do not conflate them. See [[admin-domain-rules]] (admin = all rights, vote-delegation is per-gremium).
- Self-lockout guards: an admin cannot remove or rewrite their **own** admin role assignment. An admin cannot deactivate their own account. Nobody can remove the global `member` role (gremium_id NULL).
- Config versioning: a flow save (`create_global_flow_version`) and a branding activate write a `config_revision` snapshot plus a linked audit entry. The revert/restore path replays that snapshot (`restore_branding`, `create_global_flow_version(action=...)`). See [[revert-feature-scope]] and `be-config-revision`.
- Every save of the global flow re-pins ALL applications by state **key**, so the pin is not version-based. Removed keys fall back to the single initial state. Deactivate the old active version before you insert the new one (partial-unique `WHERE active`).
- The server validates branding logos from decoded magic bytes (PNG/JPEG/WebP/ICO whitelist). It refuses **inline SVG** (XSS) and checks the real byte size against the 2 MB cap, because the client `size` is untrusted. Footer and legal URLs reject `javascript:`/`data:`/`vbscript:`. i18n freetexts have length caps (auth-free public read).
- The server generates `webhook.secret` and never serializes it in any Out DTO.
- All datetimes are tz-aware UTC. `_parse_dt` normalizes them, and assignment `valid_from/until` are timestamptz since migration 0015. All error paths return `ProblemDetail` (problem+json): 400 malformed JSON, 422 schema, 404 not-found, 409 conflict.
- camelCase JSON comes from `_CamelModel` (`populate_by_name=True`). Out models use `serialization_alias`, In models use `alias`. Nullable-clearable fields (`quorumPercent`, `retentionMonths`) tell "absent" from "null" through `payload.model_fields_set`.
- Webhook persistence lives in this module on purpose (not in `modules/webhooks`) because admin CRUD is the only writer of the config. The delivery worker sits in `webhooks`. See `be-webhooks`.
- `form-versions`, `notification-rules`/`mail-templates`, and `/admin/audit` are NOT here. They live in the forms, notifications, and audit modules.

**Related:** be-auth, be-flow, be-forms, be-config-revision, be-audit, be-webhooks, be-notifications
