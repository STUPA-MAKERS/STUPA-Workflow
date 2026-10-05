import type { FormFieldDef } from '@core/api/models';
import { toFormatLocale } from '@core/i18n/i18n.service';
import { resolveI18n } from './i18n-text';

/**
 * Stringify an answer value without a field definition.
 *
 * A scalar keeps its own text. An object or an array becomes compact JSON.
 * `null` and `undefined` become an empty string.
 */
export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

/** A date-only ISO day, the shape a `date` answer holds. */
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * One date answer as a day the reader knows, in the active locale.
 *
 * A date-only answer carries no timezone. The function reads it as UTC and prints it
 * in UTC, so the day stays the day the applicant entered, west of UTC as well.
 *
 * A value that is not a date keeps its own text: an answer an older form version
 * never validated is still what the applicant wrote, and "Invalid Date" tells the
 * reader less than the stored text does.
 */
export function formatIsoDate(value: unknown, locale: string): string {
  if (typeof value !== 'string') return formatFieldValue(value);
  const raw = value.trim();
  if (!raw) return '';
  const date = new Date(ISO_DAY.test(raw) ? `${raw}T00:00:00Z` : raw);
  if (Number.isNaN(date.getTime())) return raw;
  return new Intl.DateTimeFormat(toFormatLocale(locale), {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

/**
 * A date range `{from, to}` as one span, the same span the public share page shows.
 *
 * Each end is checked on its own. A half-filled range shows the half it has, because
 * a missing end printed as text reads like an answer. A value that is no range keeps
 * the plain rule.
 */
export function formatDateRangeValue(value: unknown, locale: string): string {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return formatFieldValue(value);
  }
  const { from, to } = value as { from?: unknown; to?: unknown };
  const ends = [from, to]
    .filter((end): end is string => typeof end === 'string' && end.trim() !== '')
    .map((end) => formatIsoDate(end, locale));
  if (ends.length === 2) return `${ends[0]} – ${ends[1]}`;
  return ends[0] ?? '';
}

/** An amount in euro, in the given locale. A value that is no number gives `null`. */
export function formatEuro(value: unknown, locale: string): string | null {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') {
    return null;
  }
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return new Intl.NumberFormat(toFormatLocale(locale), {
    style: 'currency',
    currency: 'EUR',
  }).format(n);
}

/** What `formatAnswer` needs besides the field and the value. */
export interface AnswerFormatEnv {
  /** The UI language, for the i18n labels of the options. */
  lang: string;
  /** The words for a checkbox answer. */
  yes: string;
  no: string;
}

/**
 * True when an answer counts as not given: nothing, an empty text, an empty list or a
 * range without an end. `false` and `0` are answers.
 */
export function isEmptyAnswer(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') {
    return Object.values(value as Record<string, unknown>).every(isEmptyAnswer);
  }
  return false;
}

/**
 * One answer as the text a reader sees, by the type of its field (O19, the table
 * "Darstellung der Formularfelder").
 *
 * - `checkbox`: Ja or Nein.
 * - `date` and `daterange`: the day, or "from – to".
 * - `select`, `gremium_select`, `budget_select`: the name of the option. The server puts
 *   the Gremien and the cost centres into the options of the effective form.
 * - `multiselect`: the names, joined by commas.
 * - `currency`: the amount in euro.
 * - Everything else: the value as text.
 *
 * An empty answer gives an empty string; the caller decides whether it shows a dash
 * or leaves the field out. A `positions` answer has its own block (positions-view).
 */
export function formatAnswer(field: FormFieldDef, value: unknown, env: AnswerFormatEnv): string {
  if (isEmptyAnswer(value)) return '';
  switch (field.type) {
    case 'checkbox':
      return typeof value === 'boolean' ? (value ? env.yes : env.no) : formatFieldValue(value);
    case 'date':
      return formatIsoDate(value, env.lang);
    case 'daterange':
      return formatDateRangeValue(value, env.lang);
    case 'select':
    case 'gremium_select':
    case 'budget_select':
      return optionLabel(field, value, env.lang);
    case 'multiselect':
      return Array.isArray(value)
        ? value.map((v) => optionLabel(field, v, env.lang)).join(', ')
        : optionLabel(field, value, env.lang);
    case 'currency':
      return formatEuro(value, env.lang) ?? formatFieldValue(value);
    default:
      return formatFieldValue(value);
  }
}

/** The label of an option, or the stored value when the option is gone. */
function optionLabel(field: FormFieldDef, value: unknown, lang: string): string {
  const opt = field.options?.find((o) => o.value === value);
  return opt ? resolveI18n(opt.label, lang) : formatFieldValue(value);
}
