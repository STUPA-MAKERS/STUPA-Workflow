import type { FormlyFieldConfig } from '@ngx-formly/core';
import type { FieldType, FormFieldDef, Lang } from '@core/api/models';
import { evalJsonLogic, isFieldVisible, JsonLogicError } from './jsonlogic';
import { resolveI18n } from './i18n-text';

/** HTML `type` for the `input` variant (text/number/currency/date/file). */
const INPUT_HTML_TYPE: Partial<Record<FieldType, string>> = {
  text: 'text',
  number: 'number',
  // 'currency' → its own branch in FormlyInputType (app-currency-input with €/format).
  currency: 'currency',
  date: 'date',
  file: 'text', // file upload (attachment reference) — full upload lands later.
  email: 'email',
  iban: 'text', // format check (mod-97) is done by the backend; free text field here.
};

/** Form field type → registered Formly type (`@shared/formly/formly.providers`). */
const FORMLY_TYPE: Record<FieldType, string> = {
  text: 'input',
  number: 'input',
  currency: 'input',
  date: 'input',
  file: 'input',
  textarea: 'textarea',
  select: 'select',
  multiselect: 'multicheckbox',
  // Dynamic pickers: rendered as a normal select; the server supplies the options in
  // the effective form (no hand-maintenance).
  gremium_select: 'select',
  budget_select: 'select',
  email: 'input',
  iban: 'input',
  daterange: 'daterange',
  checkbox: 'checkbox',
  markdown: 'display',
  computed: 'display',
  table: 'display',
  positions: 'positions',
  // Section markers are structural; they are filtered out in `toFormlyFields` and
  // should never be mapped (the backend strips them from the effective form).
  section: 'display',
};

/**
 * Translate an effective form definition (`FormFieldDef[]`) into Formly field
 * configs. Maps:
 * - labels/help texts via `resolveI18n` (active UI locale).
 * - `required` + `validation` (min/max/minLen/maxLen/pattern) → Formly props.
 * - `visibleIf` → `expressions.hide` (negated; eval error ⇒ conservatively visible).
 * - `compute`/`computed` → `expressions['model.<key>']` (derived value).
 *
 * `extraContext` supplies non-field variables (e.g. `has_budget`) to the JsonLogic
 * evaluation, analogous to the backend `validate_answers(context=…)`.
 */
export function toFormlyFields(
  fields: FormFieldDef[],
  lang: Lang | string,
  extraContext: Record<string, unknown> = {},
): FormlyFieldConfig[] {
  // Render section/group markers as headings instead of discarding them — so
  // question groups appear grouped in the inline editor too.
  return fields.map((f) =>
    f.type === 'section'
      ? sectionHeading(f, lang)
      : mapField(f, lang, extraContext),
  );
}

/** Section marker → non-editable heading (Formly `display`, `heading`). */
function sectionHeading(f: FormFieldDef, lang: Lang | string): FormlyFieldConfig {
  const props: Record<string, unknown> = { heading: true, label: resolveI18n(f.label, lang) };
  if (f.help) props['description'] = resolveI18n(f.help, lang);
  return { type: 'display', props };
}

function mapField(
  f: FormFieldDef,
  lang: Lang | string,
  extraContext: Record<string, unknown>,
): FormlyFieldConfig {
  const label = resolveI18n(f.label, lang);
  const help = f.help ? resolveI18n(f.help, lang) : undefined;
  const isDisplay = f.type === 'markdown' || f.type === 'computed' || f.type === 'table';

  const props: Record<string, unknown> = { label };
  if (help) props['description'] = help;
  if (!isDisplay && f.required) props['required'] = true;

  if (FORMLY_TYPE[f.type] === 'input') props['type'] = INPUT_HTML_TYPE[f.type] ?? 'text';

  if (
    f.options &&
    (f.type === 'select' ||
      f.type === 'multiselect' ||
      f.type === 'gremium_select' ||
      f.type === 'budget_select')
  ) {
    props['options'] = f.options.map((o) => ({ value: o.value, label: resolveI18n(o.label, lang) }));
  }

  applyValidation(f, props);

  if (f.type === 'markdown') props['text'] = help ?? label;
  if (f.type === 'computed') props['computed'] = true;
  if (f.type === 'table') props['text'] = '(Tabellen-Eingabe wird in einem späteren Schritt ergänzt.)';
  if (f.type === 'positions') {
    if (f.validation?.minOffers !== undefined) props['minOffers'] = f.validation.minOffers;
    if (f.validation?.minPositions !== undefined) props['minPositions'] = f.validation.minPositions;
  }

  const config: FormlyFieldConfig = { key: f.key, type: FORMLY_TYPE[f.type], props };

  const expressions = buildExpressions(f, extraContext);
  if (expressions) config.expressions = expressions;

  return config;
}

function applyValidation(f: FormFieldDef, props: Record<string, unknown>): void {
  const v = f.validation;
  if (!v) return;
  if (v.min !== undefined) props['min'] = v.min;
  if (v.max !== undefined) props['max'] = v.max;
  if (v.minLen !== undefined) props['minLength'] = v.minLen;
  if (v.maxLen !== undefined) props['maxLength'] = v.maxLen;
  if (v.pattern !== undefined) props['pattern'] = v.pattern;
}

function buildExpressions(
  f: FormFieldDef,
  extraContext: Record<string, unknown>,
): FormlyFieldConfig['expressions'] | undefined {
  const expressions: Record<string, (field: FormlyFieldConfig) => unknown> = {};

  if (f.visibleIf) {
    const visibleIf = f.visibleIf;
    expressions['hide'] = (field) => !isFieldVisible(visibleIf, ctxOf(field, extraContext));
  }

  if (f.type === 'computed' && f.compute) {
    const compute = f.compute;
    expressions[`model.${f.key}`] = (field) => {
      try {
        return evalJsonLogic(compute, ctxOf(field, extraContext));
      } catch (err) {
        if (err instanceof JsonLogicError) return null;
        throw err;
      }
    };
  }

  return Object.keys(expressions).length > 0 ? expressions : undefined;
}

function ctxOf(
  field: FormlyFieldConfig,
  extraContext: Record<string, unknown>,
): Record<string, unknown> {
  const model = (field.model ?? {}) as Record<string, unknown>;
  return { ...extraContext, ...model };
}
