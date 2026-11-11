import { InjectionToken } from '@angular/core';
import { isoDay, parseDay, weekdayName } from '@shared/date-format';

/** The clock of the Kalender ("today"). A spec replaces it with a fixed time. */
export const CALENDAR_NOW = new InjectionToken<() => Date>('CALENDAR_NOW', {
  providedIn: 'root',
  factory: () => () => new Date(),
});

/** One day cell of a grid. */
export interface CalendarDay {
  readonly iso: string;
  readonly day: number;
  /** The day is in the shown month (else it fills a week before or after it). */
  readonly inMonth: boolean;
  readonly isToday: boolean;
}

/** A month as `{ year, month }`, `month` 0-based like `Date`. */
export interface MonthRef {
  readonly year: number;
  readonly month: number;
}

/** The month that holds this date. */
export function monthOf(d: Date): MonthRef {
  return { year: d.getFullYear(), month: d.getMonth() };
}

/** The month `delta` months away. */
export function shiftMonth(ref: MonthRef, delta: number): MonthRef {
  return monthOf(new Date(ref.year, ref.month + delta, 1));
}

/** The day `delta` days away, as `YYYY-MM-DD`. An invalid day stays as it is. */
export function shiftDay(iso: string, delta: number): string {
  const d = parseDay(iso);
  return d ? isoDay(new Date(d.getFullYear(), d.getMonth(), d.getDate() + delta)) : iso;
}

/**
 * The weeks of the month grid, Monday to Sunday. The first week starts on the Monday on
 * or before the first day of the month, the last week ends on the Sunday on or after the
 * last day: 4 to 6 weeks.
 *
 * `getDay` returns 0 for Sunday, and Monday is the first column.
 */
export function monthGrid(ref: MonthRef, today: Date): readonly (readonly CalendarDay[])[] {
  const first = new Date(ref.year, ref.month, 1);
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(ref.year, ref.month, 1 - lead);
  const last = new Date(ref.year, ref.month + 1, 0);
  const trail = 6 - ((last.getDay() + 6) % 7);
  const count = lead + last.getDate() + trail;
  const todayIso = isoDay(today);
  const days = Array.from({ length: count }, (_, i): CalendarDay => {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    const iso = isoDay(d);
    return { iso, day: d.getDate(), inMonth: d.getMonth() === ref.month, isToday: iso === todayIso };
  });
  return Array.from({ length: count / 7 }, (_, w) => days.slice(w * 7, w * 7 + 7));
}

/** The seven days, Monday to Sunday, of the week that holds `iso`. */
export function weekOf(iso: string, today: Date): readonly CalendarDay[] {
  const d = parseDay(iso) ?? today;
  const monday = shiftDay(isoDay(d), -((d.getDay() + 6) % 7));
  const todayIso = isoDay(today);
  return Array.from({ length: 7 }, (_, i): CalendarDay => {
    const day = shiftDay(monday, i);
    return { iso: day, day: Number(day.slice(8)), inMonth: true, isToday: day === todayIso };
  });
}

/** The first and the last day of a grid, for the request of its entries. */
export function gridRange(weeks: readonly (readonly CalendarDay[])[]): { readonly from: string; readonly to: string } {
  const lastWeek = weeks[weeks.length - 1];
  return { from: weeks[0][0].iso, to: lastWeek[lastWeek.length - 1].iso };
}

/**
 * The short weekday names, Monday first: "Mo" … "So". `locale` is the format locale.
 *
 * 2024-01-01 is a Monday.
 */
export function weekdayNames(locale: string): readonly string[] {
  return Array.from({ length: 7 }, (_, i) => weekdayName(new Date(2024, 0, 1 + i), locale));
}
