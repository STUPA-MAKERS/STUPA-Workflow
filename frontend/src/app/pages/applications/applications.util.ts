import type { ApplicationListItem, Transition } from '@core/api/models';
import { toFormatLocale } from '@core/i18n/i18n.service';
import { flowColorKind } from '@shared/status-kind.util';

/**
 * Derive the display title of an application from the free `data` fields.
 *
 * A form has no guaranteed `title` field. The function takes the first non-empty
 * string from the usual keys. It returns the fallback when no key matches. The
 * caller passes the i18n "untitled" text as that fallback.
 */
export function applicationTitle(
  data: Record<string, unknown> | null | undefined,
  fallback: string,
): string {
  if (!data) return fallback;
  for (const key of ['title', 'name', 'subject', 'titel']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return fallback;
}

/**
 * Stringify a diff or data field value for display.
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

/** Human-readable bytes, binary base, one decimal from KB up. An invalid size gives "—". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

/** One month of the list: a heading and the rows submitted in that month. */
export interface MonthGroup<T> {
  /** `YYYY-MM` of the submission, also the track key. */
  key: string;
  /** The month as the reader says it, for example "September 2026". */
  label: string;
  items: T[];
}

/**
 * Group the rows by the month of their submission (`createdAt`), in the order the rows
 * come in. The list sorts by date, so each month is one run of rows; a month that comes
 * back later (another sort) starts a new group rather than pulling rows out of order.
 *
 * The month is the local month of the reader, the same day the date column shows.
 */
export function groupByMonth<T extends Pick<ApplicationListItem, 'createdAt'>>(
  items: readonly T[],
  locale: string,
): MonthGroup<T>[] {
  const fmt = new Intl.DateTimeFormat(toFormatLocale(locale), { month: 'long', year: 'numeric' });
  const groups: MonthGroup<T>[] = [];
  for (const item of items) {
    const date = new Date(item.createdAt);
    const valid = !Number.isNaN(date.getTime());
    const key = valid
      ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
      : '';
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.items.push(item);
    } else {
      groups.push({ key, label: valid ? fmt.format(date) : '', items: [item] });
    }
  }
  return groups;
}

/** The look of a transition button in the detail header. */
export type TransitionLook = 'fill' | 'tonal' | 'danger';

/**
 * The look of each transition button: a transition in a red colour (a rejection) is a
 * destructive action and gets the outlined red look. The first other transition is the
 * main action (filled), the rest are tonal. The order of the server stays.
 */
export function transitionLooks(transitions: readonly Transition[]): Map<string, TransitionLook> {
  const looks = new Map<string, TransitionLook>();
  let main = false;
  for (const t of transitions) {
    if (isRejection(t)) {
      looks.set(t.id, 'danger');
    } else {
      looks.set(t.id, main ? 'tonal' : 'fill');
      main = true;
    }
  }
  return looks;
}

/** A transition whose colour reads as an error (red): a rejection or a cancel. */
export function isRejection(t: Pick<Transition, 'color'>): boolean {
  return flowColorKind(t.color) === 'error';
}
