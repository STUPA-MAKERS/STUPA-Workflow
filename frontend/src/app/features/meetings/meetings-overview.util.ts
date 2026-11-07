import { InjectionToken } from '@angular/core';
import type { Attendance, Meeting, MeetingVote } from '@core/api/models';
import { toFormatLocale } from '@core/i18n/i18n.service';
import type { Translate } from '@core/i18n/translations';
import { isoDay, monthYear, weekdayName } from '@shared/date-format';

/** "8 TOPs", "1 TOP" or "keine TOPs". */
export function topsLabel(n: number, t: Translate): string {
  if (n <= 0) return t('meetings.list.topsNone');
  return n === 1 ? t('meetings.dock.topsOne') : t('meetings.dock.tops', { n });
}

/** The clock of the calendar view ("today"). A spec replaces it with a fixed time. */
export const OVERVIEW_NOW = new InjectionToken<() => Date>('OVERVIEW_NOW', {
  providedIn: 'root',
  factory: () => () => new Date(),
});

/** The two views of the meeting overview (`/meetings`). */
export type MeetingsView = 'list' | 'calendar';

/** The key in `localStorage` that keeps the chosen view per browser. */
export const VIEW_STORAGE_KEY = 'ap.meetings.view';

/**
 * The view that this browser chose last, else the list. Storage can be blocked (a private
 * window, a strict privacy setting): then the read throws, and the list shows.
 */
export function readStoredView(): MeetingsView {
  try {
    return localStorage.getItem(VIEW_STORAGE_KEY) === 'calendar' ? 'calendar' : 'list';
  } catch {
    return 'list';
  }
}

/** Keep the chosen view for the next visit. A blocked storage only forgets it. */
export function storeView(view: MeetingsView): void {
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, view);
  } catch {
    // Nothing to do: the view is a convenience, not data.
  }
}

/** One day cell of the month grid. */
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
  const d = new Date(ref.year, ref.month + delta, 1);
  return monthOf(d);
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
    const inMonth = d.getMonth() === ref.month;
    return { iso, day: d.getDate(), inMonth, isToday: iso === todayIso };
  });
  return Array.from({ length: count / 7 }, (_, w) => days.slice(w * 7, w * 7 + 7));
}

/** The first and the last day of the grid, for the request of the month. */
export function gridRange(weeks: readonly (readonly CalendarDay[])[]): { readonly from: string; readonly to: string } {
  const lastWeek = weeks[weeks.length - 1];
  return { from: weeks[0][0].iso, to: lastWeek[lastWeek.length - 1].iso };
}

/** The meetings of each day, in the order of their start time. */
export function meetingsByDay(meetings: readonly Meeting[]): ReadonlyMap<string, readonly Meeting[]> {
  const dates = [...new Set(meetings.flatMap((m) => (m.date ? [m.date] : [])))];
  const onDay = (date: string): readonly Meeting[] =>
    [...meetings.filter((m) => m.date === date)].sort(byStart);
  return new Map(dates.map((date) => [date, onDay(date)]));
}

/** Order by date, then start time, then title. A meeting without a date comes last. */
export function byStart(a: Meeting, b: Meeting): number {
  const key = (m: Meeting): string => `${m.date ?? '9999-99-99'} ${m.startTime ?? '99:99'}`;
  return key(a).localeCompare(key(b)) || a.title.localeCompare(b.title);
}

/** The meeting matches the search text (title or Gremium, case and accents ignored). */
export function matchesQuery(m: Meeting, query: string): boolean {
  const q = fold(query.trim());
  if (!q) return true;
  return fold(`${m.title} ${m.gremiumName ?? ''}`).includes(q);
}

function fold(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();
}

/**
 * The short weekday names, Monday first: "Mo" … "So". `locale` is the format locale.
 *
 * 2024-01-01 is a Monday.
 */
export function weekdayNames(locale: string): readonly string[] {
  return Array.from({ length: 7 }, (_, i) => weekdayName(new Date(2024, 0, 1 + i), locale));
}

/** A group of rows in the list view. */
export interface MeetingGroup {
  readonly key: string;
  readonly kind: 'now' | 'upcoming' | 'past';
  /** The month of the group ("Oktober 2026"), or '' for "Jetzt" and an undated group. */
  readonly month: string;
  readonly items: readonly Meeting[];
}

/**
 * The groups of the list view: "Jetzt" (the live meetings), "Anstehend · <Monat>" (the
 * planned meetings from now on, month by month) and "Vergangen · <Monat>" (the past
 * meetings, newest first). `past` comes oldest first, as the timeline keeps it.
 */
export function overviewGroups(
  upcoming: readonly Meeting[],
  past: readonly Meeting[],
  i18nLocale: string,
): readonly MeetingGroup[] {
  const locale = toFormatLocale(i18nLocale);
  const live = upcoming.filter((m) => m.status === 'live');
  const now: readonly MeetingGroup[] = live.length
    ? [{ key: 'now', kind: 'now', month: '', items: live }]
    : [];
  const rows = [
    ...upcoming.filter((m) => m.status !== 'live').map((m) => ({ kind: 'upcoming' as const, m })),
    ...[...past].reverse().map((m) => ({ kind: 'past' as const, m })),
  ];
  return rows.reduce((groups, { kind, m }) => withMonthRow(groups, kind, m, locale), now);
}

/** Adds `m` to the last group when it has the same kind and month, else opens a new group. */
function withMonthRow(
  groups: readonly MeetingGroup[],
  kind: 'upcoming' | 'past',
  m: Meeting,
  locale: string,
): readonly MeetingGroup[] {
  const key = `${kind}-${m.date ? m.date.slice(0, 7) : ''}`;
  const last = groups[groups.length - 1];
  return last && last.key === key
    ? [...groups.slice(0, -1), { ...last, items: [...last.items, m] }]
    : [...groups, { key, kind, month: monthYear(m.date, locale), items: [m] }];
}

/** The progress of a live meeting through its agenda, or null without a current item. */
export interface AgendaProgress {
  readonly position: number;
  readonly count: number;
  readonly title: string | null;
}

export function agendaProgress(m: Meeting): AgendaProgress | null {
  const current = m.currentAgendaItem;
  const count = m.agendaItemCount ?? 0;
  if (m.status !== 'live' || !current || count <= 0) return null;
  return {
    position: current.position,
    count,
    title: current.title,
  };
}

/** The open vote of the meeting, if one runs. */
export function openVoteOf(m: Meeting): MeetingVote | null {
  return m.votes.find((v) => v.status === 'open') ?? null;
}

/** The counts of the roster: present, excused, absent, open and all members. */
export interface AttendanceCounts {
  readonly present: number;
  readonly excused: number;
  readonly absent: number;
  readonly open: number;
  readonly total: number;
}

export function attendanceCounts(rows: readonly Attendance[]): AttendanceCounts {
  const count = (status: Attendance['status']): number =>
    rows.filter((row) => row.status === status).length;
  const present = count('present');
  const excused = count('excused');
  const absent = count('absent');
  const total = rows.length;
  return { present, excused, absent, open: total - present - excused - absent, total };
}
