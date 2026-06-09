import type { FormlyFieldConfig } from '@ngx-formly/core';
import type { FieldType, FormFieldDef, Lang } from '@core/api/models';
import { evalJsonLogic, isFieldVisible, JsonLogicError } from './jsonlogic';
import { resolveI18n } from './i18n-text';

/** HTML-`type` für die `input`-Variante (text/number/currency/date/file). */
const INPUT_HTML_TYPE: Partial<Record<FieldType, string>> = {
  text: 'text',
  number: 'number',
  currency: 'number',
  date: 'date',
  file: 'text', // Datei-Upload (Attachment-Referenz) — voller Upload folgt mit T-13.
};

/** Form-Feldtyp → registrierter Formly-Typ (`@shared/formly/formly.providers`). */
const FORMLY_TYPE: Record<FieldType, string> = {
  text: 'input',
  number: 'input',
  currency: 'input',
  date: 'input',
  file: 'input',
  textarea: 'textarea',
  select: 'select',
  multiselect: 'multicheckbox',
  checkbox: 'checkbox',
  markdown: 'display',
  computed: 'display',
  table: 'display',
  positions: 'positions',
  // Abschnitts-Marker sind strukturell; sie werden in `toFormlyFields` herausgefiltert
  // und sollten nie gemappt werden (Backend strippt sie aus der effektiven Form).
  section: 'display',
};

/**
 * Eine effektive Form-Definition (`FormFieldDef[]`) in Formly-Feldkonfigurationen
 * übersetzen (T-30). Bildet ab:
 * - Labels/Hilfetexte via `resolveI18n` (aktive UI-Locale).
 * - `required` + `validation` (min/max/minLen/maxLen/pattern) → Formly-Props.
 * - `visibleIf` → `expressions.hide` (negiert; Eval-Fehler ⇒ konservativ sichtbar).
 * - `compute`/`computed` → `expressions['model.<key>']` (abgeleiteter Wert).
 *
 * `extraContext` liefert Nicht-Feld-Variablen (z. B. `has_budget`) an die
 * JsonLogic-Auswertung, analog zum Backend `validate_answers(context=…)`.
 */
export function toFormlyFields(
  fields: FormFieldDef[],
  lang: Lang | string,
  extraContext: Record<string, unknown> = {},
): FormlyFieldConfig[] {
  return fields.filter((f) => f.type !== 'section').map((f) => mapField(f, lang, extraContext));
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

  if (f.options && (f.type === 'select' || f.type === 'multiselect')) {
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
