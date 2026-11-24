import type { FormlyFieldConfig } from '@ngx-formly/core';
import { tap } from 'rxjs';
import type { FieldType, FormFieldDef, FormSection, I18nMap, Lang } from '@core/api/models';
import { isFieldVisible } from './jsonlogic';
import { CATALOG, de, type TranslationKey } from '@core/i18n/translations';
import { langAttr, resolvedI18nLang, resolveI18n } from './i18n-text';
import { baseLocale, toFormatLocale } from '@core/i18n/i18n.service';
import { formatMoney } from '@shared/format-money';
import { normalizePositions, positionsTotal } from './positions';
import { computedFormat, computeValues, finiteNumber } from './form-rules';
import { budgetOptionTree } from './budget-options';

/**
 * HTML `type` for the `input` variant (text/number/currency/date/file).
 *
 * `currency` takes its own branch in `FormlyInputType` (`app-currency-input` with the €
 * format). `funding` is an amount in euro like `currency`, checked against the cost total.
 * `file` is an attachment reference in a text field. `iban` is free text, because the
 * backend checks the format (mod-97).
 */
const INPUT_HTML_TYPE: Partial<Record<FieldType, string>> = {
  text: 'text',
  number: 'number',
  currency: 'currency',
  date: 'date',
  file: 'text',
  funding: 'currency',
  email: 'email',
  iban: 'text',
};

/** Form field type → registered Formly type (`@shared/formly/formly.providers`). */
const FORMLY_TYPE: Record<FieldType, string> = {
  text: 'input',
  number: 'input',
  currency: 'input',
  funding: 'input',
  date: 'input',
  file: 'input',
  textarea: 'textarea',
  select: 'select',
  multiselect: 'multicheckbox',
  /**
   * Dynamic pickers. The server supplies the options in the effective form, so nobody
   * maintains them by hand. A Gremium is a normal select; a cost centre is the tree
   * picker of the budget forms (`budget_select`, with `props.nodes`).
   */
  gremium_select: 'select',
  budget_select: 'budget_select',
  email: 'input',
  iban: 'input',
  daterange: 'daterange',
  checkbox: 'checkbox',
  markdown: 'display',
  computed: 'display',
  table: 'display',
  positions: 'positions',
  /**
   * Section markers are structural. `toFormlyFields` handles them apart from this map, so
   * this entry never applies. The backend strips them from the effective form.
   */
  section: 'display',
};

/**
 * Translate an effective form definition (`FormFieldDef[]`) into Formly field configs.
 * The mapping covers:
 * - labels and help texts through `resolveI18n` (active UI locale). A text in a fallback
 *   language puts that language into `props.textLang`, and an option into its `lang`, so
 *   the field marks it with `lang` (app spec 000523).
 * - `required` and `validation` (min/max/minLen/maxLen/pattern) → Formly props.
 * - `visibleIf` → `expressions.hide` (negated). An eval error keeps the field visible.
 * - `compute`/`computed` → `expressions['model.<key>']` (derived value).
 *
 * `extraContext` supplies non-field variables such as `has_budget` to the JsonLogic
 * evaluation. This matches the backend `validate_answers(context=…)`.
 */
export function toFormlyFields(
  fields: readonly FormFieldDef[],
  lang: Lang,
  extraContext: Readonly<Record<string, unknown>> = {},
): FormlyFieldConfig[] {
  return fields.map((f) =>
    f.type === 'section'
      ? sectionHeading(f, lang)
      : mapField(f, lang, extraContext, fields),
  );
}

/** Field types that take the full width of the edit grid; the rest take one half. A
 *  `multiselect` takes one half there: the edit form shows it as a dropdown. */
const FULL_WIDTH_TYPES: ReadonlySet<FieldType> = new Set<FieldType>([
  'textarea',
  'daterange',
  'markdown',
  'table',
  'positions',
]);

/** Options of `toFormlySections`. */
export interface FormlySectionOptions {
  /** Keys the form leaves out, for example the PII fields the server held back. */
  readonly omitKeys?: readonly string[];
}

/**
 * Translate the sections of an effective form into one Formly group for the edit
 * form of the detail.
 *
 * The `title` field comes first over the full width. Each section then starts with its
 * heading; short fields take half a row (class `fe-half`), long ones the full row
 * (`fe-full`). The group carries the class `fe-grid`; the page lays it out as a grid of
 * two columns. Everything else is as in `toFormlyFields`.
 */
export function toFormlySections(
  sections: readonly FormSection[],
  lang: Lang,
  extraContext: Readonly<Record<string, unknown>> = {},
  options: FormlySectionOptions = {},
): FormlyFieldConfig[] {
  const omit: ReadonlySet<string> = new Set(options.omitKeys ?? []);
  const keep = (f: FormFieldDef) => !omit.has(f.key) && f.type !== 'section';
  const all = sections.flatMap((s) => s.fields);
  const title = all.find((f) => f.key === 'title' && keep(f));
  const head = title
    ? [{ ...mapField(title, lang, extraContext, all), className: 'fe-full' }]
    : [];
  const editField = (f: FormFieldDef): FormlyFieldConfig => ({
    ...mapField(f, lang, extraContext, all),
    ...(f.type === 'multiselect' ? { type: 'multiselect' } : {}),
    className: FULL_WIDTH_TYPES.has(f.type) ? 'fe-full' : 'fe-half',
  });
  const sectionGroup = (section: FormSection): FormlyFieldConfig[] => {
    const fields = section.fields.filter((f) => keep(f) && f !== title);
    const heading: FormlyFieldConfig = {
      type: 'display',
      className: 'fe-full fe-heading',
      props: { heading: true, label: resolveI18n(section.label, lang), ...textLangProp(section.label, lang) },
    };
    return fields.length ? [heading, ...fields.map(editField)] : [];
  };
  return [
    { fieldGroupClassName: 'fe-grid', fieldGroup: [...head, ...sections.flatMap(sectionGroup)] },
  ];
}

/** Section marker → non-editable heading (Formly `display`, `heading`). */
function sectionHeading(f: FormFieldDef, lang: Lang): FormlyFieldConfig {
  const label = resolveI18n(f.label, lang);
  const help = ownHelp(f, label, lang);
  return {
    type: 'display',
    props: { heading: true, label, ...(help ? { description: help } : {}), ...textLangProp(f.label, lang) },
  };
}

/**
 * The help text of a field, or undefined when it has none or when it only repeats the
 * label. A form can hold the same words in both, and the field would then show them twice.
 */
function ownHelp(f: FormFieldDef, label: string, lang: Lang): string | undefined {
  const help = f.help ? resolveI18n(f.help, lang) : '';
  return help.trim() && help.trim() !== label.trim() ? help : undefined;
}

/** `textLang` for a form text in a fallback language; nothing when the UI language shows. */
function textLangProp(map: I18nMap | null | undefined, lang: Lang): { readonly textLang?: string } {
  const code = fallbackLang(map, lang);
  return code ? { textLang: code } : {};
}

/** The language of a form text when it is not the UI language, else `null`. */
function fallbackLang(map: I18nMap | null | undefined, lang: Lang): string | null {
  return langAttr(resolvedI18nLang(map, lang), lang);
}

/** The keys of the `positions` fields: their total caps the requested funding. */
function positionsKeys(fields: readonly FormFieldDef[]): readonly string[] {
  return fields.filter((f) => f.type === 'positions').map((f) => f.key);
}

/** The cost total of the positions answers in the model. */
function costTotal(field: FormlyFieldConfig, costKeys: readonly string[]): number {
  const model = (field.model ?? {}) as Record<string, unknown>;
  return costKeys.reduce((sum, key) => sum + positionsTotal(normalizePositions(model[key])), 0);
}

/** A UI text in the locale of the form. */
function uiText(key: TranslationKey, lang: Lang): string {
  return CATALOG[baseLocale(lang)]?.[key] ?? de[key];
}

/** A UI text with `{total}` filled in, in the locale of the form. */
function totalText(key: TranslationKey, lang: Lang, total: number): string {
  return uiText(key, lang).replace('{total}', formatMoney(total, toFormatLocale(String(lang))) || String(total));
}

/**
 * The requested funding: the hint is the help of the field and nothing else (specs 002990,
 * 003006). While the setting `capAtCost` is on, a value above the cost total is an error that
 * names the total (spec 003004). The server checks the same rule (`_check_funding_total`).
 *
 * The cap is checked again when any answer changes, because the cost positions are other controls.
 */
function withFunding(
  config: FormlyFieldConfig,
  lang: Lang,
  costKeys: readonly string[],
): FormlyFieldConfig {
  const over = (field: FormlyFieldConfig): boolean => {
    const raw: unknown = field.formControl?.value;
    if (raw === null || raw === undefined || raw === '') return false;
    const value = Number(raw);
    return Number.isFinite(value) && value > costTotal(field, costKeys) + 1e-9;
  };
  return {
    ...config,
    validators: {
      ...config.validators,
      fundingMax: { expression: (_control: unknown, field: FormlyFieldConfig) => !over(field) },
    },
    hooks: {
      onInit: (field) =>
        field.form?.valueChanges.pipe(
          tap(() => field.formControl?.updateValueAndValidity({ emitEvent: false })),
        ),
    },
    expressions: {
      ...config.expressions,
      'props.errorText': (field: FormlyFieldConfig) =>
        over(field) ? totalText('forms.funding.max', lang, costTotal(field, costKeys)) : undefined,
    },
  };
}

/** The props of one choice field: its options, and the tree of a cost-centre picker. */
function choiceProps(f: FormFieldDef, lang: Lang): Readonly<Record<string, unknown>> {
  const choice =
    f.type === 'select' ||
    f.type === 'multiselect' ||
    f.type === 'gremium_select' ||
    f.type === 'budget_select';
  const options = f.options?.map((o) => {
    const code = fallbackLang(o.label, lang);
    return { value: o.value, label: resolveI18n(o.label, lang), ...(code ? { lang: code } : {}) };
  });
  return {
    ...(options && choice ? { options } : {}),
    ...(f.type === 'budget_select' ? { nodes: budgetOptionTree(f.options ?? [], lang) } : {}),
  };
}

/**
 * The `positions` limits that the form sets, and its hint texts (spec 003010) with the
 * language of the form and the fields of the form, which the placeholders of a text read.
 */
function positionsProps(
  f: FormFieldDef,
  all: readonly FormFieldDef[],
  lang: Lang,
): Readonly<Record<string, unknown>> {
  const v = f.validation;
  return {
    ...(v?.hints ? { hints: v.hints, hintLang: lang, formFields: all } : {}),
    ...(v?.minOffers !== undefined ? { minOffers: v.minOffers } : {}),
    ...(v?.minPositions !== undefined ? { minPositions: v.minPositions } : {}),
    ...(v?.allowNoOffers !== undefined ? { allowNoOffers: v.allowNoOffers } : {}),
  };
}

/** The props of the display types: a Markdown text, a computed value, a table. */
function displayProps(
  f: FormFieldDef,
  lang: Lang,
  help: string | undefined,
  all: readonly FormFieldDef[],
): Readonly<Record<string, unknown>> {
  switch (f.type) {
    case 'markdown':
      return { text: help ?? fieldLabel(f, lang) };
    case 'computed':
      return { computed: true, format: computedFormat(f) };
    case 'table':
      return {
        text: CATALOG[baseLocale(lang)]?.['forms.table.pending'] ?? de['forms.table.pending'],
      };
    case 'positions':
      return positionsProps(f, all, lang);
    default:
      return {};
  }
}

/** The label of a field in the locale of the form. */
function fieldLabel(f: FormFieldDef, lang: Lang): string {
  return resolveI18n(f.label, lang);
}

function mapField(
  f: FormFieldDef,
  lang: Lang,
  extraContext: Readonly<Record<string, unknown>>,
  all: readonly FormFieldDef[],
): FormlyFieldConfig {
  const costKeys = positionsKeys(all);
  const text = fieldLabel(f, lang);
  const help =
    f.type === 'markdown'
      ? ownHelp(f, text, lang)
      : f.help
        ? resolveI18n(f.help, lang)
        : undefined;
  const isDisplay = f.type === 'markdown' || f.type === 'computed' || f.type === 'table';
  const props: Record<string, unknown> = {
    ...(f.type === 'markdown' && !help ? {} : { label: text }),
    ...(help ? { description: help } : {}),
    ...textLangProp(f.label, lang),
    ...(!isDisplay && f.required ? { required: true } : {}),
    ...(FORMLY_TYPE[f.type] === 'input' ? { type: INPUT_HTML_TYPE[f.type] ?? 'text' } : {}),
    ...choiceProps(f, lang),
    ...validationProps(f),
    ...displayProps(f, lang, help, all),
  };
  const expressions = buildExpressions(f, extraContext, numberKeys(all), all);
  const config: FormlyFieldConfig = {
    key: f.key,
    type: FORMLY_TYPE[f.type],
    props,
    ...(expressions ? { expressions } : {}),
  };
  return f.type === 'funding' && f.validation?.capAtCost !== false
    ? withFunding(config, lang, costKeys)
    : config;
}

/** The Formly props of the `validation` limits of a field. */
function validationProps(f: FormFieldDef): Readonly<Record<string, unknown>> {
  const v = f.validation;
  if (!v) return {};
  return {
    ...(v.min !== undefined ? { min: v.min } : {}),
    ...(v.max !== undefined ? { max: v.max } : {}),
    ...(v.minLen !== undefined ? { minLength: v.minLen } : {}),
    ...(v.maxLen !== undefined ? { maxLength: v.maxLen } : {}),
    ...(v.pattern !== undefined ? { pattern: v.pattern } : {}),
  };
}

/** A Formly expression: a value derived from the field and its model. */
type FieldExpression = (field: FormlyFieldConfig) => unknown;

function buildExpressions(
  f: FormFieldDef,
  extraContext: Readonly<Record<string, unknown>>,
  numbers: ReadonlySet<string> = new Set(),
  all: readonly FormFieldDef[],
): FormlyFieldConfig['expressions'] | undefined {
  const visibleIf = f.visibleIf;
  const compute = f.type === 'computed' ? f.compute : undefined;
  const hide: Readonly<Record<string, FieldExpression>> = visibleIf
    ? { hide: (field: FormlyFieldConfig) => !isFieldVisible(visibleIf, ctxOf(field, extraContext, numbers)) }
    : {};
  const derived: Readonly<Record<string, FieldExpression>> = compute
    ? {
        [`model.${f.key}`]: (field: FormlyFieldConfig) =>
          computeValues(all, (field.model ?? {}) as Record<string, unknown>, extraContext)[f.key] ??
          null,
      }
    : {};
  const expressions: Record<string, FieldExpression> = { ...hide, ...derived };
  return Object.keys(expressions).length > 0 ? expressions : undefined;
}

/** The keys of the numeric fields, whose answer the input holds as a text. */
function numberKeys(all: readonly FormFieldDef[]): ReadonlySet<string> {
  return new Set(all.filter((f) => NUMBER_TYPES.has(f.type)).map((f) => f.key));
}

const NUMBER_TYPES: ReadonlySet<FieldType> = new Set<FieldType>(['number', 'currency', 'funding']);

/**
 * The values that an expression reads. A numeric answer that the input holds as a text
 * (`"84"`) is read as its number, as the server reads it (spec 002840); without that a
 * computed value over a typed number stays empty.
 */
function ctxOf(
  field: FormlyFieldConfig,
  extraContext: Readonly<Record<string, unknown>>,
  numbers: ReadonlySet<string> = new Set(),
): Record<string, unknown> {
  const model = (field.model ?? {}) as Record<string, unknown>;
  const read = Object.fromEntries(
    Object.entries(model)
      .filter(([key, value]) => numbers.has(key) && typeof value === 'string')
      .map(([key, value]) => [key, finiteNumber(value)] as const)
      .filter(([, n]) => n !== null),
  );
  return { ...extraContext, ...model, ...read };
}
