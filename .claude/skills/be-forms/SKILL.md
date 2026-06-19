---
name: be-forms
description: Versioned per-application-type form definitions (form_version/form_field) stored as JSONB FormFieldDef, the effective-form merge (type fields + budget-pot extra fields), and the pure validation engine (validate_definition, validate_answers, extract_promoted) with visibleIf/compute JsonLogic and ReDoS-hardened patterns. Use when working on form versions, the form builder, answer validation, promoted fields, or positions/Kostenaufstellung in backend/app/modules/forms.
---

# Forms — `backend/app/modules/forms`

**Does:** Stores versioned form definitions (one active version per application type) as JSONB field rows, serves the "effective form" (type fields + optional budget-pot extra fields, split into wizard sections), and provides a pure (no-DB/no-HTTP) engine that validates definitions and applicant answers, computes derived fields, and extracts promoted values.

**Key files:**
- `models.py` — `FormVersion` + `FormField` SQLAlchemy tables (JSONB columns).
- `schemas.py` — request/response hulls (`FormVersionCreate`, `FormVersionOut`, `FormDraftOut`, `EffectiveFormOut`, `FormSectionOut`, `FormActiveSet`); `SECTION_LABELS` defaults. Field shape itself is `FormFieldDef` from `app.shared.config_schemas`.
- `service.py` — `FormsService`: DB CRUD for versions, `get_effective_form` (pins `form_version_id`, merges pot fields), `set_form_active`, `get_form_draft`, version bumping, config-revision snapshot + audit on create.
- `validation.py` — pure engine: `validate_definition`, `effective_form`/`_split_sections`, `validate_answers`, `extract_promoted`, `positions_total`, `system_title_field`, per-type validators, ReDoS-hardened `_pattern_matches`.
- `router.py` — FastAPI router (tags `forms`); mounted in `app/main.py`.
- `__init__.py` — empty.

**Domain / data model:**
- `form_version` (table `FormVersion`): `application_type_id` (FK → `application_type`, CASCADE), `version` (int, unique per type), `active` (bool — **partial-unique index `uq_form_version_one_active_per_type`: max one active per type**), `created_by`, `description_i18n` (JSONB Markdown, NC-Forms). `application_type.active_form_version_id` is the authoritative pointer.
- `form_field` (table `FormField`): belongs to a version (`form_version_id`, CASCADE), unique `(form_version_id, key)`. Columns mirror `FormFieldDef`: `key`, `type`, `label_i18n`, `help_i18n`, `required`, `validation` (JSONB), `visible_if`, `compute`, `options`, `order`, `is_pii`, `is_promoted`, `promote_target`.
- `FormFieldDef` (`app.shared.config_schemas`, the single source of truth): camelCase JSON aliases (`visibleIf`, `isPII`, `isPromoted`, `promoteTarget`). `FieldType` literal = `text, textarea, number, currency, date, select, multiselect, checkbox, file, table, markdown, computed, positions, section`. `validation` (`FieldValidation`): `minLen/maxLen/min/max/pattern/maxRows/minOffers/minPositions`.
- **Versioning is pin-not-mutate** (data-model §4): creating a version never edits old ones; running applications keep their `form_version_id` and render the pinned form. `get_effective_form(..., form_version_id=)` overrides the active version for pinned rendering.
- **Sections:** a `section`-type field is a marker only (label, no answer value); `_split_sections` breaks the field list into wizard steps. With no marker → one `main` section.
- **System title:** `effective_form` prepends a required `title` text field (`SYSTEM_TITLE_KEY`) to the first section unless the type already defines a `title` key. Not editable in the builder.
- **Budget pot extras:** when a `budget_pot_id` is supplied, that pot's `BudgetField`s become a `budget` section — only if the pot belongs to the type's gremium and the type `has_budget` (else 404, no existence leak).

**API surface:**
- `GET  /api/application-types/{type_id}/form` — public; effective form definition, optional `?budgetPotId=`.
- `GET  /api/admin/application-types/{type_id}/form-versions/latest` — perm `form.configure`; latest version as editable draft (raw fields, no merge).
- `POST /api/admin/application-types/{type_id}/form-versions` — perm `form.configure`; create version (definition validated server-side; 400 malformed JSON, 422 schema/definition error), optional `activate`.
- `PATCH /api/admin/application-types/{type_id}/form-active` — perm `form.configure`; `{active}` toggles the type on (reactivate newest) / off (clear `active_form_version_id`, lock new applications).

**Conventions & gotchas:**
- All error paths are RFC-9457 `ProblemDetail`; definition errors raise `FormDefinitionError` → re-wrapped as `ValidationProblem` (422). RBAC is enforced via `require_principal("form.configure")` from the session, never the body.
- `validate_definition` gates on save: no duplicate keys; `isPromoted` fields must be numeric (`number`/`currency`) since they promote into numeric targets like `amount`; `visibleIf`/`compute` must use only the JsonLogic whitelist (`validate_jsonlogic`); a `pattern` must compile.
- **JsonLogic `and`/`or` do NOT short-circuit** (all operands eval). `validate_answers` `_is_visible` therefore treats any eval error as *visible* (conservative — validates rather than silently skips). Whitelist ops: `== != > >= < <= and or not var + - * / in`.
- `validate_answers` collects **all** field errors (no fail-fast) → `AnswerValidationError(errors)`; `computed` fields are evaluated first (in field order) and feed later expressions; `section`/`computed` carry no answer value.
- **ReDoS hardening:** admin `validation.pattern` runs against applicant input behind two independent limits — input capped at `_PATTERN_MAX_INPUT_LEN` (4096, over-length = no-match) and a 1.0s wall-clock thread timeout (`_PATTERN_EXECUTOR`); failure/timeout → field marked invalid, never a 500/hang. `config_schemas._redos_prone` also rejects nested-quantifier patterns at definition time. See [[tailwind-preflight-off-borders]]-unrelated; relevant memory is `security.md` design only.
- **Positions / Kostenaufstellung** (`positions` type): each position needs ≥ `minPositions`, each ≥ `minOffers` (default 3) comparison offers, exactly one `preferred` offer, all offer `value`s finite and > 0. `positions_total` sums preferred values; `extract_promoted` implicitly promotes that sum into `amount` (additive across multiple `positions` fields, no `isPromoted` flag needed). Offer shape: `{label, value, preferred}` — see [[positions-field-shape]].
- External callers: `applications/service.py` (`get_effective_form` → `validate_answers` → `extract_promoted` on create/update) and `config_revision/reapply.py` (revert). `create_form_version` writes a `ConfigRevisionService.record` snapshot (`ENTITY_FORM`) + audit — keep that on any new write path. See [[revert-feature-scope]].
- Numbers normalize via `Decimal(str(value))`; NaN/Infinity are rejected (`is_finite`) before min/max compare so they never reach budget code (T-12/T-17).

**Related:** be-applications, be-budget, be-config-revision, be-audit, be-flow
