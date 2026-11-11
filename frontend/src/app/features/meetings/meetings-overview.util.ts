import type { Attendance, Meeting } from '@core/api/models';
import { toFormatLocale } from '@core/i18n/i18n.service';
import type { Translate } from '@core/i18n/translations';
import { monthYear } from '@shared/date-format';

/** "8 TOPs", "1 TOP" or "keine TOPs". */
export function topsLabel(n: number, t: Translate): string {
  if (n <= 0) return t('meetings.list.topsNone');
  return n === 1 ? t('meetings.dock.topsOne') : t('meetings.dock.tops', { n });
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
