import type { FormlyFieldConfig } from '@ngx-formly/core';
import { tap } from 'rxjs';
import type { FieldType, FormFieldDef, FormSection, Lang } from '@core/api/models';
import { evalJsonLogic, isFieldVisible, JsonLogicError } from './jsonlogic';
import { CATALOG, de, type TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from './i18n-text';
import { baseLocale, toFormatLocale } from '@core/i18n/i18n.service';
import { formatMoney } from '@shared/format-money';
import { normalizePositions, positionsTotal } from './positions';
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
 * - labels and help texts through `resolveI18n` (active UI locale).
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
  const costKeys = positionsKeys(fields);
  return fields.map((f) =>
    f.type === 'section'
      ? sectionHeading(f, lang)
      : mapField(f, lang, extraContext, costKeys),
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
  const costKeys = positionsKeys(all);
  const title = all.find((f) => f.key === 'title' && keep(f));
  const head = title
    ? [{ ...mapField(title, lang, extraContext, costKeys), className: 'fe-full' }]
    : [];
  const editField = (f: FormFieldDef): FormlyFieldConfig => ({
    ...mapField(f, lang, extraContext, costKeys),
    ...(f.type === 'multiselect' ? { type: 'multiselect' } : {}),
    className: FULL_WIDTH_TYPES.has(f.type) ? 'fe-full' : 'fe-half',
  });
  const sectionGroup = (section: FormSection): FormlyFieldConfig[] => {
    const fields = section.fields.filter((f) => keep(f) && f !== title);
    const heading: FormlyFieldConfig = {
      type: 'display',
      className: 'fe-full fe-heading',
      props: { heading: true, label: resolveI18n(section.label, lang) },
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
    props: { heading: true, label, ...(help ? { description: help } : {}) },
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

/** The keys of the `positions` fields: their total caps the requested funding. */
function positionsKeys(fields: readonly FormFieldDef[]): readonly string[] {
  return fields.filter((f) => f.type === 'positions').map((f) => f.key);
}

/** The cost total of the positions answers in the model. */
function costTotal(field: FormlyFieldConfig, costKeys: readonly string[]): number {
  const model = (field.model ?? {}) as Record<string, unknown>;
  return costKeys.reduce((sum, key) => sum + positionsTotal(normalizePositions(model[key])), 0);
}

/** A UI text with `{total}` filled in, in the locale of the form. */
function totalText(key: TranslationKey, lang: Lang, total: number): string {
  const text = CATALOG[baseLocale(lang)]?.[key] ?? de[key];
  return text.replace('{total}', formatMoney(total, toFormatLocale(String(lang))) || String(total));
}

/**
 * The requested funding: the hint shows the cost total, and a value above the total is
 * an error with its own text. The server checks the same rule (`_check_funding_total`).
 *
 * The cap is checked again when any answer changes, because the cost positions are other controls.
 */
function withFunding(
  config: FormlyFieldConfig,
  help: string | undefined,
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
      'props.description': (field: FormlyFieldConfig) => {
        const hint = totalText('forms.funding.hint', lang, costTotal(field, costKeys));
        return help ? `${help} ${hint}` : hint;
      },
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
  const options = f.options?.map((o) => ({ value: o.value, label: resolveI18n(o.label, lang) }));
  return {
    ...(options && choice ? { options } : {}),
    ...(f.type === 'budget_select' ? { nodes: budgetOptionTree(f.options ?? [], lang) } : {}),
  };
}

/** The `positions` limits that the form sets. */
function positionsProps(f: FormFieldDef): Readonly<Record<string, unknown>> {
  const v = f.validation;
  return {
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
): Readonly<Record<string, unknown>> {
  switch (f.type) {
    case 'markdown':
      return { text: help ?? fieldLabel(f, lang) };
    case 'computed':
      return { computed: true };
    case 'table':
      return {
        text: CATALOG[baseLocale(lang)]?.['forms.table.pending'] ?? de['forms.table.pending'],
      };
    case 'positions':
      return positionsProps(f);
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
  costKeys: readonly string[] = [],
): FormlyFieldConfig {
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
    ...(!isDisplay && f.required ? { required: true } : {}),
    ...(FORMLY_TYPE[f.type] === 'input' ? { type: INPUT_HTML_TYPE[f.type] ?? 'text' } : {}),
    ...choiceProps(f, lang),
    ...validationProps(f),
    ...displayProps(f, lang, help),
  };
  const expressions = buildExpressions(f, extraContext);
  const config: FormlyFieldConfig = {
    key: f.key,
    type: FORMLY_TYPE[f.type],
    props,
    ...(expressions ? { expressions } : {}),
  };
  return f.type === 'funding' ? withFunding(config, help, lang, costKeys) : config;
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
): FormlyFieldConfig['expressions'] | undefined {
  const visibleIf = f.visibleIf;
  const compute = f.type === 'computed' ? f.compute : undefined;
  const hide: Readonly<Record<string, FieldExpression>> = visibleIf
    ? { hide: (field: FormlyFieldConfig) => !isFieldVisible(visibleIf, ctxOf(field, extraContext)) }
    : {};
  const derived: Readonly<Record<string, FieldExpression>> = compute
    ? {
        [`model.${f.key}`]: (field: FormlyFieldConfig) => {
          try {
            return evalJsonLogic(compute, ctxOf(field, extraContext));
          } catch (err) {
            if (err instanceof JsonLogicError) return null;
            throw err;
          }
        },
      }
    : {};
  const expressions: Record<string, FieldExpression> = { ...hide, ...derived };
  return Object.keys(expressions).length > 0 ? expressions : undefined;
}

function ctxOf(
  field: FormlyFieldConfig,
  extraContext: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  const model = (field.model ?? {}) as Record<string, unknown>;
  return { ...extraContext, ...model };
}
