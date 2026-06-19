---
name: be-admin
description: Admin/config API — gremien, gremium-roles+memberships, application-types, the single global flow version, RBAC (roles/role-assignments/group-mappings/principals), webhooks, and versioned site-config/branding draft→activate (incl. public branding + PWA manifest). One permission per /admin/ page (admin.gremien/.types/.site/.roles/.users/.group_mappings/.gremium_roles, webhook.manage). Use when working on /admin routes, ConfigService, SiteConfigService, GremiumRoleService, Branding, or config versioning in backend/app/modules/admin.
---

# Admin / Config Surface — `backend/app/modules/admin`

**Does:** Server-authoritative CRUD for platform config — gremien & their per-gremium roles/memberships, application-types, the one global flow version, RBAC (roles, role-assignments, group-mappings, principal activation), webhooks, and versioned branding/site-config with a draft→activate lifecycle. Every mutation writes an audit entry in the same transaction; config-versioned entities (flow, site-config) also snapshot to `config_revision`.

**Key files:**
- `router.py` — three routers: `router` (prefix `/admin`, per-page permission gates), `public_router` (auth-free `/site-config` + `/manifest.webmanifest`), `authed_router` (auth-only `/gremien` dropdown source, no admin right). Declares all per-page permission `Depends` constants.
- `service.py` — `ConfigService`: gremien, application-types, global flow version, roles/assignments/group-mappings/principals, webhooks. Mapper helpers at bottom.
- `site_config_service.py` — `SiteConfigService`: branding draft/activate/restore + `public()` + `manifest()` (dynamic PWA manifest, single source of truth).
- `gremium_roles.py` — `GremiumRoleService` (per-gremium roles + time-bounded memberships, overlap invariant) plus RBAC resolver helpers `active_gremium_roles`, `gremium_ids_with_permission`, `gremium_member_ids`, `intervals_overlap`, and `FORCED_GREMIUM_ROLES`.
- `branding.py` — `Branding` Pydantic schema: logos (image-only, no SVG, magic-byte sniffed, 2 MB cap), footer columns/links, legal links, i18n freetexts. Security contract lives here.
- `models.py` — SQLAlchemy: `Gremium`, `GremiumRole`, `GremiumMembership`, `MailList`, `ApplicationType`, `Webhook`, `WebhookDelivery`, `SiteConfigVersion`.
- `schemas.py` — camelCase DTOs (`populate_by_name`, `serialization_alias` on Out models).

**Domain / data model:**
- `gremium` — committee. `slug` unique, `cd_variant` (stupa/asta/echo/makers/report → pytex CD), `default_lang`, vote-delegation knobs (`allow_vote_delegation`, `delegation_lead_minutes`, `delegation_allow_external`), `quorum_percent` (0–100, nullable, explicitly clearable via `model_fields_set`). Creating one auto-seeds forced gremium-roles.
- `gremium_role` — per-gremium role set, **separate** from global `role`. `(gremium_id, key)` unique. `permissions` JSONB from the 4-key gremium catalogue: `session.manage`, `vote.manage`, `vote.cast`, `protocol.write`. Forced roles `vorstand`/`manager` (all 4) + `member` (vote.cast only) exist in every gremium, not deletable, lazily backfilled on list.
- `gremium_membership` — time-bounded (`valid_from`/`valid_until`, half-open `[from,until)`) link principal→gremium_role. Invariant: at most one active role per (principal, gremium) at any instant; overlaps rejected, adjacent allowed. Role FK is `RESTRICT`.
- `application_type` — `key` unique, `name_i18n`, `has_budget`, `comparison_offers` JSONB, `retention_months` (DSGVO, nullable=global default), `active_form_version_id` (circular FK, use_alter). Delete is 409 if any application references it.
- `mail_list` — per-gremium recipients; canonical `name='protocol'` row holds extra protocol recipients (PUT replaces all rows).
- `webhook` — `name/url/events` (whitelist `EventName`), server-generated `secret` (32 bytes, HMAC signing, never returned), `active`. `webhook_delivery` — worker-written; status pending/ok/failed/dead, unique `(webhook_id, idempotency_key)`, pickup index `(status, next_at)`.
- `site_config_version` — versioned branding. `version` unique, partial-unique one `active` row (`WHERE active`), `branding` JSONB, `created_by`=OIDC sub. Draft = latest inactive version; activate flips `active`.
- Global flow: there is exactly **one** flow for all types (`flow_version` etc. live in `flow` module). Each save = a new immutable version; ALL running applications are re-pinned by state **key** to the newest version (dropped keys → initial state). Never deleted.
- RBAC rows (`role`, `role_permission`, `role_assignment`, `group_mapping`, `principal`) live in the `auth` module; admin only does their CRUD.

**API surface:**
- `GET /api/admin/config-schemas` — JSON-schemas for FE editors (any admin area).
- `GET|POST /api/admin/gremien`, `PATCH|DELETE /api/admin/gremien/{id}`, `GET|PUT /api/admin/gremien/{id}/mail-recipients` — gremien CRUD + protocol recipients (admin.gremien).
- `GET|POST /api/admin/gremien/{id}/roles`, `PATCH|DELETE /api/admin/gremium-roles/{id}` — per-gremium roles (admin.gremium_roles to write; list also allowed to admin.gremien).
- `GET|POST /api/admin/gremien/{id}/memberships`, `DELETE /api/admin/gremium-memberships/{id}` — memberships (admin.gremien).
- `GET /api/gremien` — auth-only gremien dropdown source (no admin right; `authed_router`).
- `GET|POST /api/admin/application-types`, `PATCH /api/admin/application-types/{id}`, `DELETE` (admin.types; delete needs admin.types_delete).
- `GET|POST /api/admin/flow-versions/global` — read/create the single global flow (read also allowed to flow.configure/budget.structure).
- `GET /api/admin/principals`, `PATCH /api/admin/principals/{id}` (activate/deactivate), `GET /api/admin/permissions` (key catalogue), `GET|POST /api/admin/roles`, `PATCH|DELETE /api/admin/roles/{id}` (admin.roles; admin/member protected).
- `GET|POST /api/admin/role-assignments`, `PATCH|DELETE /api/admin/role-assignments/{id}` (admin.users; create/delete fire assignment-changed mail in background).
- `GET|POST /api/admin/group-mappings`, `PATCH|DELETE /api/admin/group-mappings/{id}` (admin.group_mappings).
- `GET|POST /api/admin/webhooks`, `PATCH /api/admin/webhooks/{id}` (webhook.manage; list also flow.configure).
- `GET /api/admin/site-config`, `PUT /api/admin/site-config/draft`, `POST /api/admin/site-config/activate` (admin.site).
- `GET /api/site-config` (auth-free public branding, `Cache-Control: public, max-age=300`), `GET /api/manifest.webmanifest` (auth-free dynamic PWA manifest).

**Conventions & gotchas:**
- **One permission per admin page.** `admin.config` was split (migration 0017) into `admin.gremien/.types/.site/.roles`, then further per-page into `admin.users/.group_mappings/.gremium_roles/.delegations/.deadlines`. Reads shared across pages use `require_any_permission(...)` (see `_FLOW_READABLE`, `_ROLES_READ`, `_GREMIEN_OR_USERS` etc.) but writes always gate on the strict key. RBAC is enforced here (router `require_principal`); FE is UX-only.
- Two **separate** role systems: global `role`/`role_assignment` (16-permission catalogue from `app.shared.permissions.PERMISSION_CATALOGUE`) vs `gremium_role` (4-key session catalogue, resolved via active membership). Don't conflate. See [[admin-domain-rules]] (admin = all rights; vote-delegation is per-gremium).
- Self-lockout guards: an admin cannot remove/rewrite their **own** admin role assignment, cannot deactivate their own account; the global `member` role (gremium_id NULL) is unremovable.
- Config versioning: flow save (`create_global_flow_version`) and branding activate write a `config_revision` snapshot + linked audit entry — this is what the revert/restore path replays (`restore_branding`, `create_global_flow_version(action=...)`). See [[revert-feature-scope]] and `be-config-revision`.
- Global flow re-pins ALL applications by state **key** on every save (not version-pinned); removed keys fall back to the single initial state. Deactivate the old active version before inserting the new one (partial-unique `WHERE active`).
- Branding logos are validated server-side from decoded magic bytes (PNG/JPEG/WebP/ICO whitelist), **no inline SVG** (XSS), real byte size vs 2 MB cap (client `size` untrusted); footer/legal URLs reject `javascript:`/`data:`/`vbscript:`. i18n freetexts have length caps (auth-free public read).
- `webhook.secret` is generated server-side and never serialized in any Out DTO.
- All datetimes tz-aware UTC (`_parse_dt` normalizes; assignment `valid_from/until` are timestamptz since migration 0015). All error paths return `ProblemDetail` (problem+json): 400 malformed JSON, 422 schema, 404 not-found, 409 conflict.
- camelCase JSON via `_CamelModel` (`populate_by_name=True`); Out models use `serialization_alias`, In models use `alias`. Nullable-clearable fields (`quorumPercent`, `retentionMonths`) distinguish "absent" vs "null" via `payload.model_fields_set`.
- Webhook persistence deliberately lives in this module (not `modules/webhooks`) because admin CRUD is the only writer of the config; the delivery worker is in `webhooks`. See `be-webhooks`.
- `form-versions`, `notification-rules`/`mail-templates`, and `/admin/audit` are NOT here — they live in the forms, notifications, and audit modules respectively.

**Related:** be-auth, be-flow, be-forms, be-config-revision, be-audit, be-webhooks, be-notifications
