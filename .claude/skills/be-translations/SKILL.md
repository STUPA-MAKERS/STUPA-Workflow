---
name: be-translations
description: Admin overrides of the UI texts and extra UI languages — ui_translation/ui_language tables, the key catalog copy (catalog.json), the public GET /i18n bundle, /admin/translations (admin.translations), and the frontend I18nService chain (uiLocale vs locale). Use when working on backend/app/modules/translations, the admin page "Übersetzungen", or the i18n service of the frontend.
---

# UI text overrides and extra languages — `backend/app/modules/translations`

**Does:** Stores what an admin changes of the built-in UI texts of the frontend, and the languages that an admin adds beside DE and EN. The frontend keeps owning the texts; the table only overrides them.

**Key files:**
- `models.py` — `UiTranslation` (`locale`, `key`, `value`; PK locale+key; `value` NULL and a missing row both mean the built-in text) and `UiLanguage` (`code` BCP 47, `name`, `active`; DE and EN have no row, a CHECK refuses them).
- `catalog.py` + `catalog.json` — the copy of the DE key catalog with the placeholders of each key. `frontend/src/app/core/i18n/translations.catalog.spec.ts` fails when it is stale; regenerate with `UPDATE_I18N_CATALOG=1 npx jest src/app/core/i18n/translations.catalog.spec.ts`. Every change to the DE catalog needs this.
- `service.py` — `TranslationService`: languages CRUD, `save` (one transaction, all keys checked first), `bundle`. `fallback_chain`: DE → [de]; EN → [en, de]; extra → [code, en, de].
- `router.py` — public `GET /i18n?locale=` (no login, `Cache-Control: no-cache`; unknown or inactive locale resolves to `de`), admin `GET|POST /admin/translations/languages`, `PATCH|DELETE .../languages/{code}`, `GET|PUT /admin/translations/texts/{locale}` (body `{changes: {key: text|null}}`).

**Rules:**
- A save refuses a key outside the catalog (422 `unknown_key`) and a text whose placeholders differ from the built-in text (422 `placeholder_mismatch`). A blank text counts as null and deletes the row.
- A new language starts inactive. Only an active one shows in the bundle and in the language switch. A delete removes its overrides.
- Every change writes `config_change` (target `ui_translation` or `ui_language`) without a revision; the entry names keys and counts, never the texts.
- `updated_by` columns are in `principal_merge.SUB_COLUMNS`.

**Frontend:** `I18nService.uiLocale()` is the chosen language (may be an extra one); `locale()` is its built-in base (`de`/`en`) for DB texts, server labels, ui-kit and `Intl`. `ready()` loads `GET /i18n` before the first paint. `translate` walks `fallbackChain(uiLocale)`, an override before the built-in text of the same locale. The admin page (`pages/admin/translations/`) calls `applyOverrides` after a save.

**Scope:** UI catalog only. Mail templates, form labels and branding texts keep their own editors and know DE and EN only; an extra language shows them in EN.

**Related:** be-admin, be-audit, frontend, mcp (tools `*_ui_language`, `get_ui_texts`, `set_ui_texts`)
