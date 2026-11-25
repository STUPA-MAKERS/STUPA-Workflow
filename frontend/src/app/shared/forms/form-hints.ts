/**
 * The hint texts of a form (spec 003010).
 *
 * The code holds no hint text. A hint shows only when the form config holds its text in
 * `validation.hints` of a `positions` field; an empty text shows nothing. A text may hold
 * placeholders in braces: `{key}` inserts the answer of the field `key`, `{costTotal}` and
 * `{amount}` the values of the rules (spec 001670), and a caller can add its own (for
 * example `{noOffersSwitch}`). A money value shows as money, a number as a number. An
 * unknown key or an empty value inserts nothing.
 */
import type { FieldHints, FormFieldDef, Lang } from '@core/api/models';
import { formatMoney } from '@shared/format-money';
import { formatComputed } from './answer-format';
import { computedFormat, computeValues, costTotal, ruleContext } from './form-rules';
import { resolveI18n } from './i18n-text';

/** The key of one hint text of a `positions` field. */
export type HintKey = keyof FieldHints;

/** Every hint of a `positions` field, in the order of the form editor. */
export const HINT_KEYS: readonly HintKey[] = [
  'below',
  'placeholderValue',
  'placeholderLabel',
  'placeholderDuplicate',
  'useNoOffers',
  'noOffers',
  'noFileTitle',
  'noFileBody',
];

/** The field types whose answer is an amount of money. */
const MONEY_TYPES: ReadonlySet<string> = new Set(['currency', 'funding']);

/** The raw text of one hint in the language of the form, or '' without a text. */
export function hintText(hints: FieldHints | undefined, key: HintKey, lang: Lang): string {
  return resolveI18n(hints?.[key], lang).trim();
}

/** One value of a placeholder as text. */
function shown(
  key: string,
  value: unknown,
  field: FormFieldDef | undefined,
  locale: string,
): string {
  if (value === null || value === undefined || value === '') return '';
  if (field?.type === 'computed') return formatComputed(computedFormat(field), value, locale);
  const money = key === 'costTotal' || key === 'amount' || MONEY_TYPES.has(field?.type ?? '');
  if (money || typeof value === 'number') {
    const n = Number(value);
    if (!Number.isFinite(n)) return '';
    return money ? formatMoney(n, locale) : new Intl.NumberFormat(locale).format(n);
  }
  return typeof value === 'string' ? value : '';
}

/**
 * Fill the placeholders of a hint text with the answers of the form. A `positions` field
 * inserts the sum of its preferred offers.
 */
export function fillHint(
  text: string,
  fields: readonly FormFieldDef[],
  data: Readonly<Record<string, unknown>>,
  locale: string,
  extra: Readonly<Record<string, string>> = {},
): string {
  if (!text) return '';
  const ctx = { ...ruleContext(fields, data), ...computeValues(fields, data) };
  return text.replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, key: string) => {
    if (key in extra) return extra[key] ?? '';
    const field = fields.find((f) => f.key === key);
    if (field?.type === 'positions') {
      const sum = costTotal([field], data);
      return sum === null ? '' : formatMoney(sum, locale);
    }
    return shown(key, ctx[key], field, locale);
  });
}
