---
name: be-forms
description: Versioned per-application-type form definitions (form_version/form_field) stored as JSONB FormFieldDef. Covers the effective-form merge (type fields plus budget-pot extra fields) and the pure validation engine (validate_definition, validate_answers, extract_promoted) with visibleIf/compute JsonLogic and ReDoS-hardened patterns. Use when working on form versions, the form builder, answer validation, promoted fields, or positions/Kostenaufstellung in backend/app/modules/forms.
---

# Forms — `backend/app/modules/forms`

**Does:** Stores versioned form definitions as JSONB field rows, one active version per application type. Serves the "effective form": type fields plus optional budget-pot extra fields, split into wizard sections. A pure engine (no DB, no HTTP) validates definitions and applicant answers, computes derived fields, and extracts promoted values.

**Key files:**
- `models.py` — `FormVersion` + `FormField` SQLAlchemy tables (JSONB columns).
- `schemas.py` — request and response wrappers (`FormVersionCreate`, `FormVersionOut`, `FormDraftOut`, `EffectiveFormOut`, `FormSectionOut`, `FormActiveSet`) plus the `SECTION_LABELS` defaults. The field shape itself is `FormFieldDef` from `app.shared.config_schemas`.
- `service.py` — `FormsService`: DB CRUD for versions, `get_effective_form` (pins `form_version_id`, merges pot fields), `set_form_active`, `get_form_draft`, version bumping, config-revision snapshot + audit on create.
- `validation.py` — pure engine: `validate_definition`, `effective_form`/`_split_sections`, `validate_answers`, `extract_promoted`, `positions_total`, `system_title_field`, per-type validators, ReDoS-hardened `_pattern_matches`.
- `router.py` — FastAPI router (tags `forms`), mounted in `app/main.py`.
- `__init__.py` — empty.

**Domain / data model:**
- `form_version` (table `FormVersion`): `application_type_id` (FK → `application_type`, CASCADE), `version` (int, unique per type), `active` (bool — **partial-unique index `uq_form_version_one_active_per_type`: max one active per type**), `created_by`, `description_i18n` (JSONB Markdown, NC-Forms). `application_type.active_form_version_id` is the authoritative pointer.
- `form_field` (table `FormField`): belongs to a version (`form_version_id`, CASCADE), unique `(form_version_id, key)`. Columns mirror `FormFieldDef`: `key`, `type`, `label_i18n`, `help_i18n`, `required`, `validation` (JSONB), `visible_if`, `compute`, `options`, `order`, `is_pii`, `is_promoted`, `promote_target`.
- `FormFieldDef` (`app.shared.config_schemas`, the single source of truth): camelCase JSON aliases (`visibleIf`, `isPII`, `isPromoted`, `promoteTarget`). `FieldType` literal = `text, textarea, number, currency, date, select, multiselect, checkbox, file, table, markdown, computed, positions, section`. `validation` (`FieldValidation`): `minLen/maxLen/min/max/pattern/maxRows/minOffers/minPositions`.
- **Versioning is pin-not-mutate** (data-model §4): creating a version never edits old ones. Running applications keep their `form_version_id` and render the pinned form. `get_effective_form(..., form_version_id=)` overrides the active version for pinned rendering.
- **Sections:** a `section`-type field is a marker only (label, no answer value). `_split_sections` breaks the field list into wizard steps. With no marker the form has one `main` section.
- **System title:** `effective_form` prepends a required `title` text field (`SYSTEM_TITLE_KEY`) to the first section unless the type already defines a `title` key. The builder cannot edit it.
- **Budget pot extras:** when the caller supplies a `budget_pot_id`, that pot's `BudgetField`s become a `budget` section. This works only if the pot belongs to the Gremium of the type and the type sets `has_budget`. Otherwise the API answers 404 and leaks no existence.

**API surface:**
- `GET  /api/application-types/{type_id}/form` — public. Effective form definition, optional `?budgetPotId=`.
- `GET  /api/admin/application-types/{type_id}/form-versions/latest` — perm `form.configure`. Latest version as an editable draft (raw fields, no merge).
- `POST /api/admin/application-types/{type_id}/form-versions` — perm `form.configure`. Creates a version, optional `activate`. The server validates the definition: 400 for malformed JSON, 422 for a schema or definition error.
- `PATCH /api/admin/application-types/{type_id}/form-active` — perm `form.configure`. `{active}` toggles the type on (reactivate the newest version) or off (clear `active_form_version_id`, lock new applications).

**Conventions & gotchas:**
- All error paths return an RFC-9457 `ProblemDetail`. Definition errors raise `FormDefinitionError`, which the module re-wraps as `ValidationProblem` (422). `require_principal("form.configure")` enforces RBAC from the session, never from the body.
- `validate_definition` gates on save. It rejects duplicate keys. `isPromoted` fields must be numeric (`number`/`currency`) because they promote into numeric targets like `amount`. `visibleIf`/`compute` must use only the JsonLogic whitelist (`validate_jsonlogic`). A `pattern` must compile.
- **JsonLogic `and`/`or` do NOT short-circuit** — the engine evaluates every operand. `_is_visible` in `validate_answers` therefore treats any evaluation error as *visible*. That is the conservative choice: it validates the field instead of skipping it silently. Whitelist ops: `== != > >= < <= and or not var + - * / in`.
- `validate_answers` collects **all** field errors (no fail-fast) and raises `AnswerValidationError(errors)`. It evaluates `computed` fields first, in field order, so they feed later expressions. `section` and `computed` fields carry no answer value.
- **ReDoS hardening:** the admin `validation.pattern` runs against applicant input behind two independent limits. The engine caps the input at `_PATTERN_MAX_INPUT_LEN` (4096, over-length counts as no match). A 1.0 s wall-clock thread timeout (`_PATTERN_EXECUTOR`) bounds each match. On failure or timeout the engine marks the field invalid. It never returns a 500 and never hangs. `config_schemas._redos_prone` also rejects nested-quantifier patterns at definition time.
- **Positions / Kostenaufstellung** (`positions` type): a field needs at least `minPositions` positions. Each position needs at least `minOffers` (default 3) comparison offers, exactly one `preferred` offer, and offer `value`s that are all finite and > 0. `positions_total` sums the preferred values. `extract_promoted` promotes that sum into `amount` implicitly, additive across several `positions` fields and without an `isPromoted` flag. Offer shape: `{label, value, preferred}` — see [[positions-field-shape]].
- External callers: `applications/service.py` (`get_effective_form` → `validate_answers` → `extract_promoted` on create/update) and `config_revision/reapply.py` (revert). `create_form_version` writes a `ConfigRevisionService.record` snapshot (`ENTITY_FORM`) + audit — keep that on any new write path. See [[revert-feature-scope]].
- Numbers normalize via `Decimal(str(value))`. The engine rejects NaN and Infinity (`is_finite`) before the min/max compare, so they never reach budget code (T-12/T-17).

**Related:** be-applications, be-budget, be-config-revision, be-audit, be-flow
