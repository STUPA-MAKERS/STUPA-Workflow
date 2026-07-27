---
name: be-application-types
description: Public read-only listing of application types (Antragstypen) — each binds an i18n name, a hasBudget flag, and an active form version that makes it submittable. Serves GET /api/application-types with a public view plus an admin view (key/gremiumId) gated by the form.configure permission. Use when working on the application-types list endpoint, ApplicationType submittability, or has_budget in backend/app/modules/application_types.
---

# Application Types (Antragstypen) — `backend/app/modules/application_types`

**Does:** Exposes the public, paged listing of application types offered for submission (`GET /api/application-types`). An application type binds an i18n name, a budget flag, and the currently active form version. A type is "submittable/active" only when it has an active form version. CRUD lives elsewhere, in the admin module.

**Key files:**
- `router.py` — `APIRouter` (tags `application-types`) with the single `GET /application-types`. It computes `is_admin = principal.has("form.configure")` and passes the `include_inactive` and `admin` flags to the service.
- `service.py` — `ApplicationTypesService(session)`. `list_types()` queries `ApplicationType`, filters `active_form_version_id IS NOT NULL` for the public view, orders by `key`, and builds a `Page`. `_to_item()` resolves the i18n name.
- `schemas.py` — `ApplicationTypeListQuery` (PageParams + `extra="forbid"`, `offset` capped at int4-max, `lang: Lang`) and `ApplicationTypeListItem` (camelCase aliases through `populate_by_name`).
- `__init__.py` — module docstring. It notes that the per-type form endpoint lives in the forms module and that config CRUD lives under `/api/admin/application-types`.
- Model lives in `app/modules/admin/models.py` → `ApplicationType` (NOT in this module).

**Domain / data model:** Entity `ApplicationType` (table `application_type`, `UUIDPkMixin` + `CreatedAtMixin`). Columns: `id`, `gremium_id` (FK `gremium.id` ON DELETE CASCADE, nullable), `key` (Text, unique), `name_i18n` (JSONB, default `{}`), `has_budget` (bool, default false), `comparison_offers` (JSONB, nullable). `retention_months` is a nullable int, and NULL means the global DSGVO default. `active_form_version_id` is a nullable FK to `form_version.id` ON DELETE SET NULL. It sets `use_alter=True` for the circular FK with form/flow versions. The DTO derives "active" from `active_form_version_id is not None`. The type carries no flow-version FK column here. The flow is the global versioned flow (see the flow module).

**API surface:**
- `GET /api/application-types` — public, paged list of submittable types. Query: `limit`, `offset` (≤ int4-max), `lang`. Returns `Page[ApplicationTypeListItem]`. Public fields: `id`, `name` (resolved i18n, falls back to `key`), `hasBudget`, `active`, `activeFormVersionId`. A principal with `form.configure` also gets inactive types and the admin fields `key` and `gremiumId` (otherwise `null`). Errors use the RFC-9457 `ProblemDetail` (422).
- Admin CRUD (create/update/delete, active-form selection) is NOT here. It lives at `GET/POST/PATCH /api/admin/application-types[...]` in the admin module (`be-admin`).

**Conventions & gotchas:**
- This module is read-only and unauthenticated at the route level. The "admin view" is opportunistic. It needs no auth. It only enriches the response when an authenticated principal carries `form.configure`. The gating permission string is hardcoded as `_ADMIN_PERMISSION = "form.configure"`.
- Public submittability means the type has an `active_form_version_id`. Without an active form nobody can file an application of that type, so the public list hides it (`include_inactive=False`).
- `name` is always a resolved string (`resolve_i18n(name_i18n, lang) or key`). The FE never sees the raw `*_i18n` map. This matches the [[no-uuids-in-ui]] and i18n-resolution convention.
- DTOs are camelCase-aliased (`hasBudget`, `activeFormVersionId`, `gremiumId`) with `populate_by_name=True`. Build instances with the alias kwargs, as the service does.
- `ApplicationTypeListQuery` uses `extra="forbid"`, so unknown query params give 422 (schemathesis negative-data conformance). `offset` is `le=2_147_483_647` only to avoid a DB OFFSET int4 overflow → 500.
- The total count uses `select(func.count()).select_from(stmt.subquery())` over the same filter. Keep the filter and the count in sync when you change the query.

**Related:** be-admin, be-forms, be-flow, be-applications
