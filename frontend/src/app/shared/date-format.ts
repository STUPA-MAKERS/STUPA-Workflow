/**
 * The one set of date helpers of the app: calendar days, parsing and the short date texts
 * that the pages build in TS (a template uses the `ldate` pipe for a full moment).
 *
 * Every formatter takes the `Intl` format locale, `I18nService.formatLocale()` (`de-DE` /
 * `en-GB`), never the bare UI locale. A missing or invalid value gives `''`.
 *
 * One name per meaning:
 * - `dayMonth` "14.10.", `dayMonthYear` "14.10.2026", `shortDay` "14.10." in the current
 *   year and "14.10.2027" in another one;
 * - `weekdayName` "Di", `weekdayDate` "Di, 14.10.2026" (the short weekday without its
 *   abbreviation dot, the house form);
 * - `monthYear` "Oktober 2026", `monthShort` "Okt", `longDate` "14. Oktober 2026";
 * - `clock` "17:05" of a moment, `shortTime` "18:00" of a SQL time.
 */

/** A date value as the API and the pages hand it over. */
export type DateValue = string | number | Date | null | undefined;

const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const MONTH = /^(\d{4})-(\d{2})$/;
const DAY_MS = 86_400_000;

const pad = (n: number): string => String(n).padStart(2, '0');

/** The local calendar day of a moment as `YYYY-MM-DD`. */
export function isoDay(at: Date): string {
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

/** Today as a local `YYYY-MM-DD`. `now` is a parameter for the tests. */
export function localToday(now: Date = new Date()): string {
  return isoDay(now);
}

/**
 * A date value as a `Date`, or null for no or an invalid value.
 *
 * A plain day (`YYYY-MM-DD`) and a month (`YYYY-MM`, its first day) are local noon:
 * `new Date('2026-09-29')` is midnight UTC, which is the day before west of Greenwich,
 * and noon stays on the day across a DST change. Any other string is a moment.
 */
export function parseDay(value: DateValue): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  let date: Date;
  const day = typeof value === 'string' ? DAY.exec(value) : null;
  const month = typeof value === 'string' && !day ? MONTH.exec(value) : null;
  if (day) date = new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]), 12);
  else if (month) date = new Date(Number(month[1]), Number(month[2]) - 1, 1, 12);
  else date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The number of the local calendar day of a date, for differences in whole days. */
function dayNumber(d: Date): number {
  return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY_MS;
}

const formats = new Map<string, Intl.DateTimeFormat>();

/**
 * The `Intl.DateTimeFormat` of a locale and options, made once. A new one costs far more
 * than a `format` call, and a board formats a date on every tile.
 */
function dateFormat(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let f = formats.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat(locale, options);
    formats.set(key, f);
  }
  return f;
}

/**
 * Whole calendar days from `today` to `value` (negative in the past), or null for an
 * invalid value. Calendar days, not blocks of 24 hours: yesterday 23:00 is one day ago.
 */
export function daysUntil(value: DateValue, today: DateValue = new Date()): number | null {
  const a = parseDay(today);
  const b = parseDay(value);
  return a && b ? dayNumber(b) - dayNumber(a) : null;
}

/**
 * Whole calendar days since a moment, never below 0 ("seit 5 Tagen"), or null for no or an
 * invalid value. A change yesterday at 23:00 counts one day at 09:00 today.
 */
export function calendarDaysSince(at: DateValue, now: Date = new Date()): number | null {
  const days = daysUntil(now, at);
  return days === null ? null : Math.max(0, days);
}

/** The short weekday without its abbreviation dot: "Di" (de), "Tue" (en). */
export function weekdayName(value: DateValue, locale: string): string {
  const d = parseDay(value);
  if (!d) return '';
  return dateFormat(locale, { weekday: 'short' }).format(d).replace(/\.$/, '');
}

/** Day and month: "14.10." (de, always with the closing dot) or "14/10" (en). */
export function dayMonth(value: DateValue, locale: string): string {
  const d = parseDay(value);
  if (!d) return '';
  const text = dateFormat(locale, { day: '2-digit', month: '2-digit' }).format(d);
  // Some ICU versions write the German "14.10" without the closing dot.
  return locale.startsWith('de') && !text.endsWith('.') ? `${text}.` : text;
}

/** Day, month and year: "14.10.2026" (de) or "14/10/2026" (en). */
export function dayMonthYear(value: DateValue, locale: string): string {
  const d = parseDay(value);
  if (!d) return '';
  return dateFormat(locale, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(d);
}

/** "14.10." in the year of `today`, else "14.10.2027". */
export function shortDay(value: DateValue, locale: string, today: DateValue = new Date()): string {
  const d = parseDay(value);
  if (!d) return '';
  const ref = parseDay(today);
  return ref && ref.getFullYear() === d.getFullYear()
    ? dayMonth(d, locale)
    : dayMonthYear(d, locale);
}

/** The options of {@link weekdayDate}. */
export interface WeekdayDateOptions {
  /** With the year (default) or without: "Di, 14.10.". */
  year?: boolean;
  /** With the clock time: "Di, 14.10.2026, 17:00". */
  time?: boolean;
}

/** "Di, 14.10.2026": the short weekday without its dot, then the date. */
export function weekdayDate(
  value: DateValue,
  locale: string,
  options: WeekdayDateOptions = {},
): string {
  const d = parseDay(value);
  if (!d) return '';
  const date = options.year === false ? dayMonth(d, locale) : dayMonthYear(d, locale);
  const text = `${weekdayName(d, locale)}, ${date}`;
  return options.time ? `${text}, ${clock(d, locale)}` : text;
}

/** "Oktober 2026". `utc` reads a moment in UTC (a month key or a plain day is local). */
export function monthYear(
  value: DateValue,
  locale: string,
  options: { utc?: boolean } = {},
): string {
  const d = parseDay(value);
  if (!d) return '';
  return dateFormat(locale, {
    month: 'long',
    year: 'numeric',
    ...(options.utc ? { timeZone: 'UTC' } : {}),
  }).format(d);
}

/** The short month name without its dot: "Okt" (de), "Oct" (en). */
export function monthShort(value: DateValue, locale: string): string {
  const d = parseDay(value);
  if (!d) return '';
  return dateFormat(locale, { month: 'short' }).format(d).replace(/\.$/, '');
}

/** The written date: "14. Oktober 2026" (de), "14 October 2026" (en). */
export function longDate(value: DateValue, locale: string): string {
  const d = parseDay(value);
  if (!d) return '';
  return dateFormat(locale, { dateStyle: 'long' }).format(d);
}

/** The local clock time of a moment, `HH:MM`, always 24 h. */
export function clock(value: DateValue, locale: string): string {
  const d = parseDay(value);
  if (!d) return '';
  return dateFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(d);
}

/**
 * A SQL `time` (`18:00:00`) as `HH:MM`, always 24 h.
 *
 * The seconds are noise on screen. An empty value gives `''`. A value that is not a time
 * stays as it is, because unreadable source text tells more than an invented time. The
 * format stays 24 h on purpose: `app-time-input` also forces 24 h, because the native
 * `type="time"` follows the browser locale and can show AM/PM.
 */
export function shortTime(value: string | null | undefined): string {
  const raw = (value ?? '').trim();
  const match = /^([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d(?:\.\d+)?)?$/.exec(raw);
  return match ? `${match[1].padStart(2, '0')}:${match[2]}` : raw;
}
