import { type DateValue, monthYear, parseDay } from './date-format';

/** A group of list rows: the rows of one month, or one group without a heading. */
export interface MonthGroup<T> {
  /** `YYYY-MM` of the rows, also the track key. `''` for the rows without a date, `all`
   *  for the single group of a list that is not by date. */
  key: string;
  /** "September 2026", or empty without a month. */
  label: string;
  items: T[];
}

/** The options of {@link groupByMonth}. */
export interface GroupByMonthOptions {
  /**
   * Read the month from the date part of the value as the server wrote it (`2026-09-30T23:30Z`
   * is September everywhere). Without it, the month is the local month of the reader, the
   * same day the date column shows.
   */
  utc?: boolean;
}

/** The `YYYY-MM` month of a value, or `''` for no or an invalid value. */
function monthKey(value: DateValue, utc: boolean): string {
  if (utc && typeof value === 'string') {
    const key = value.slice(0, 7);
    return /^\d{4}-(0[1-9]|1[0-2])$/.test(key) ? key : '';
  }
  const d = parseDay(value);
  if (!d) return '';
  const year = utc ? d.getUTCFullYear() : d.getFullYear();
  const month = (utc ? d.getUTCMonth() : d.getMonth()) + 1;
  return `${year}-${String(month).padStart(2, '0')}`;
}

/**
 * Group rows by the month of a date, in the order the rows come in. The lists sort by
 * date, so each month is one run of rows; a month that comes back later (another sort)
 * starts a new group rather than pulling rows out of order. A run of rows without a date
 * is a group of its own (key `''`, no label) at the place it comes in.
 *
 * `locale` is the format locale (`I18nService.formatLocale()`).
 */
export function groupByMonth<T>(
  rows: readonly T[],
  dateOf: (row: T) => DateValue,
  locale: string,
  options: GroupByMonthOptions = {},
): MonthGroup<T>[] {
  const groups: MonthGroup<T>[] = [];
  for (const row of rows) {
    const key = monthKey(dateOf(row), options.utc ?? false);
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.items.push(row);
      continue;
    }
    groups.push({ key, label: key ? monthYear(key, locale) : '', items: [row] });
  }
  return groups;
}
