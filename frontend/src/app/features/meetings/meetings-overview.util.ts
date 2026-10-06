import { InjectionToken } from '@angular/core';
import type { Attendance, Meeting, MeetingVote } from '@core/api/models';
import { toFormatLocale } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

/** The translate function of `I18nService`. */
export type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

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

/** A local day as `YYYY-MM-DD`. */
export function isoDay(d: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The local date of a `YYYY-MM-DD` string (midnight). */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/** One day cell of the month grid. */
export interface CalendarDay {
  iso: string;
  day: number;
  /** The day is in the shown month (else it fills a week before or after it). */
  inMonth: boolean;
  isToday: boolean;
}

/** A month as `{ year, month }`, `month` 0-based like `Date`. */
export interface MonthRef {
  year: number;
  month: number;
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
 */
export function monthGrid(ref: MonthRef, today: Date): CalendarDay[][] {
  const first = new Date(ref.year, ref.month, 1);
  // getDay: 0 = Sunday. Monday is the first column.
  const lead = (first.getDay() + 6) % 7;
  const start = new Date(ref.year, ref.month, 1 - lead);
  const last = new Date(ref.year, ref.month + 1, 0);
  const trail = 6 - ((last.getDay() + 6) % 7);
  const end = new Date(ref.year, ref.month + 1, trail);
  const todayIso = isoDay(today);
  const weeks: CalendarDay[][] = [];
  for (let d = start; d <= end; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
    if ((d.getDay() + 6) % 7 === 0) weeks.push([]);
    const iso = isoDay(d);
    weeks[weeks.length - 1].push({
      iso,
      day: d.getDate(),
      inMonth: d.getMonth() === ref.month,
      isToday: iso === todayIso,
    });
  }
  return weeks;
}

/** The first and the last day of the grid, for the request of the month. */
export function gridRange(weeks: readonly CalendarDay[][]): { from: string; to: string } {
  const lastWeek = weeks[weeks.length - 1];
  return { from: weeks[0][0].iso, to: lastWeek[lastWeek.length - 1].iso };
}

/** The meetings of each day, in the order of their start time. */
export function meetingsByDay(meetings: readonly Meeting[]): Map<string, Meeting[]> {
  const map = new Map<string, Meeting[]>();
  for (const m of meetings) {
    if (!m.date) continue;
    const list = map.get(m.date) ?? [];
    list.push(m);
    map.set(m.date, list);
  }
  for (const list of map.values()) list.sort(byStart);
  return map;
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

/** The month name with the year: "Oktober 2026". */
export function monthLabel(ref: MonthRef, i18nLocale: string): string {
  return new Intl.DateTimeFormat(toFormatLocale(i18nLocale), {
    month: 'long',
    year: 'numeric',
  }).format(new Date(ref.year, ref.month, 1));
}

/** The short weekday names, Monday first: "Mo" … "So". */
export function weekdayNames(i18nLocale: string): string[] {
  const fmt = new Intl.DateTimeFormat(toFormatLocale(i18nLocale), { weekday: 'short' });
  // 2024-01-01 is a Monday.
  return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(2024, 0, 1 + i)).replace('.', ''));
}

/** The short weekday of a date: "Di". */
export function weekdayShort(iso: string, i18nLocale: string): string {
  return new Intl.DateTimeFormat(toFormatLocale(i18nLocale), { weekday: 'short' })
    .format(parseDay(iso))
    .replace('.', '');
}

/** A group of rows in the list view. */
export interface MeetingGroup {
  key: string;
  kind: 'now' | 'upcoming' | 'past';
  /** The month of the group ("Oktober 2026"), or '' for "Jetzt" and an undated group. */
  month: string;
  items: Meeting[];
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
): MeetingGroup[] {
  const fmt = new Intl.DateTimeFormat(toFormatLocale(i18nLocale), {
    month: 'long',
    year: 'numeric',
  });
  const groups: MeetingGroup[] = [];
  const live = upcoming.filter((m) => m.status === 'live');
  if (live.length) groups.push({ key: 'now', kind: 'now', month: '', items: live });
  const add = (kind: 'upcoming' | 'past', m: Meeting): void => {
    const month = m.date ? m.date.slice(0, 7) : '';
    const key = `${kind}-${month}`;
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.items.push(m);
      return;
    }
    groups.push({ key, kind, month: m.date ? fmt.format(parseDay(m.date)) : '', items: [m] });
  };
  for (const m of upcoming) if (m.status !== 'live') add('upcoming', m);
  for (const m of [...past].reverse()) add('past', m);
  return groups;
}

/** The progress of a live meeting through its agenda, or null without a current item. */
export interface AgendaProgress {
  position: number;
  count: number;
  percent: number;
  title: string | null;
}

export function agendaProgress(m: Meeting): AgendaProgress | null {
  const current = m.currentAgendaItem;
  const count = m.agendaItemCount ?? 0;
  if (m.status !== 'live' || !current || count <= 0) return null;
  return {
    position: current.position,
    count,
    percent: Math.round((current.position / count) * 100),
    title: current.title,
  };
}

/** The open vote of the meeting, if one runs. */
export function openVoteOf(m: Meeting): MeetingVote | null {
  return m.votes.find((v) => v.status === 'open') ?? null;
}

/** The counts of the roster: present, excused, absent, open and all members. */
export interface AttendanceCounts {
  present: number;
  excused: number;
  absent: number;
  open: number;
  total: number;
}

export function attendanceCounts(rows: readonly Attendance[]): AttendanceCounts {
  const counts: AttendanceCounts = { present: 0, excused: 0, absent: 0, open: 0, total: 0 };
  for (const row of rows) {
    counts.total++;
    if (row.status === 'present') counts.present++;
    else if (row.status === 'excused') counts.excused++;
    else if (row.status === 'absent') counts.absent++;
    else counts.open++;
  }
  return counts;
}
