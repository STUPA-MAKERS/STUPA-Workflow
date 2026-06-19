---
name: be-application-types
description: Public read-only listing of Antragstypen (application types) — each binds an i18n name, a hasBudget flag, and an active form version that makes it submittable. Serves GET /api/application-types with a public view plus an admin view (key/gremiumId) gated by the form.configure permission. Use when working on the application-types list endpoint, ApplicationType submittability, or has_budget in backend/app/modules/application_types.
---

# Application Types (Antragstypen) — `backend/app/modules/application_types`

**Does:** Exposes the public, paged listing of application types offered for submission (`GET /api/application-types`). An application type binds an i18n name, a budget flag, and the currently active form version; a type is "submittable/active" only when it has an active form version. CRUD lives elsewhere (admin module).

**Key files:**
- `router.py` — `APIRouter` (tags `application-types`); single `GET /application-types`; computes `is_admin = principal.has("form.configure")` and passes `include_inactive`/`admin` flags to the service.
- `service.py` — `ApplicationTypesService(session)`; `list_types()` queries `ApplicationType`, filters `active_form_version_id IS NOT NULL` for the public view, orders by `key`, builds `Page`; `_to_item()` resolves the i18n name.
- `schemas.py` — `ApplicationTypeListQuery` (PageParams + `extra="forbid"`, `offset` capped at int4-max, `lang: Lang`); `ApplicationTypeListItem` (camelCase aliases via `populate_by_name`).
- `__init__.py` — module docstring; notes the per-type form endpoint lives in the forms module and config CRUD lives under `/api/admin/application-types`.
- Model lives in `app/modules/admin/models.py` → `ApplicationType` (NOT in this module).

**Domain / data model:** Entity `ApplicationType` (table `application_type`, `UUIDPkMixin` + `CreatedAtMixin`). Columns: `id`, `gremium_id` (FK `gremium.id` ON DELETE CASCADE, nullable), `key` (Text, unique), `name_i18n` (JSONB, default `{}`), `has_budget` (bool, default false), `comparison_offers` (JSONB, nullable), `retention_months` (int, nullable — NULL = global DSGVO default), `active_form_version_id` (FK `form_version.id` ON DELETE SET NULL, `use_alter=True` for the circular FK with form/flow versions, nullable). "active" in the DTO is derived: `active_form_version_id is not None`. There is no flow-version FK column on the type here; flow is the global versioned flow (see flow module).

**API surface:**
- `GET /api/application-types` — public, paged list of submittable types. Query: `limit`, `offset` (≤ int4-max), `lang`. Returns `Page[ApplicationTypeListItem]`. Public fields: `id`, `name` (resolved i18n, falls back to `key`), `hasBudget`, `active`, `activeFormVersionId`. A principal with `form.configure` additionally gets inactive types and the admin fields `key` and `gremiumId` (else `null`). Errors as RFC-9457 `ProblemDetail` (422).
- Admin CRUD (create/update/delete, active-form selection) is NOT here — it's `GET/POST/PATCH /api/admin/application-types[...]` in the admin module (`be-admin`).

**Conventions & gotchas:**
- This module is read-only and unauthenticated at the route level; the "admin view" is opportunistic — it does not require auth, it just enriches the response when an authenticated principal carries `form.configure`. The gating permission string is hardcoded as `_ADMIN_PERMISSION = "form.configure"`.
- Public submittability == has an `active_form_version_id`; without an active form a type cannot be used to file an application, so it's hidden from the public list (`include_inactive=False`).
- `name` is always a resolved string (`resolve_i18n(name_i18n, lang) or key`); the FE never sees the raw `*_i18n` map — consistent with [[no-uuids-in-ui]]/i18n-resolution convention.
- DTOs are camelCase-aliased (`hasBudget`, `activeFormVersionId`, `gremiumId`) with `populate_by_name=True`; build instances with the alias kwargs as the service does.
- `ApplicationTypeListQuery` uses `extra="forbid"` so unknown query params 422 (schemathesis negative-data conformance); `offset` is `le=2_147_483_647` purely to avoid DB OFFSET int4 overflow → 500.
- Total count uses `select(func.count()).select_from(stmt.subquery())` over the same filter — keep the filter and count in sync when changing the query.

**Related:** be-admin, be-forms, be-flow, be-applications
