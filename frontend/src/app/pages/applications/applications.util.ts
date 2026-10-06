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

// The answer formatters live in `@shared/forms/answer-format`, because the answer view
// and the apply wizard use them too. The re-export keeps the imports of this page.
export { formatDateRangeValue, formatFieldValue, formatIsoDate } from '@shared/forms/answer-format';

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
