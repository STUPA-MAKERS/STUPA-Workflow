import type { AgendaItem, IsoDateTime } from '@core/api/models';

/** The time zone of the meetings: the start time of a meeting is a wall time there. */
const PLAN_TZ = 'Europe/Berlin';

/** One row of the time plan (§ 001141, § 001143). */
export interface AgendaPlanRow {
  /** The start as minutes after midnight, or `null` without a start time of the meeting. */
  readonly start: number | null;
  /** `true` when the start is the recorded time of the move (000870), not a plan. */
  readonly actual: boolean;
  /** The estimated duration, or `null` when the item has none. */
  readonly minutes: number | null;
}

/** The time plan of an agenda. */
export interface AgendaPlan {
  readonly rows: readonly AgendaPlanRow[];
  /** The planned end as minutes after midnight, or `null` without a start time. */
  readonly end: number | null;
  /** The sum of all durations, or `null` when no item has one. */
  readonly total: number | null;
  /** The planned end is after the end time of the meeting (§ 001144). */
  readonly overrun: boolean;
}

/** The meeting facts that the plan reads. */
export interface AgendaPlanMeeting {
  readonly date?: string | null;
  readonly startTime?: string | null;
  readonly endTime?: string | null;
  readonly status: string;
  readonly currentAgendaItemId?: string | null;
}

/** `HH:MM[:SS]` as minutes after midnight. */
function wallMinutes(time: string): number {
  const [h, m] = time.split(':');
  return Number(h) * 60 + Number(m);
}

/** The date (`YYYY-MM-DD`) and the minutes after midnight of an instant in Berlin. */
function berlin(at: Date): { readonly date: string; readonly minutes: number } {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone: PLAN_TZ,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(at)
      .map((p) => [p.type, p.value]),
  );
  return { date: `${parts['year']}-${parts['month']}-${parts['day']}`, minutes: Number(parts['hour']) * 60 + Number(parts['minute']) };
}

/** Minutes after midnight as `HH:MM`; a plan past midnight wraps. */
export function planClock(minutes: number): string {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

/**
 * The time plan of an agenda (§ 001141 – § 001144).
 *
 * The first item starts at the start time of the meeting, and each further item at the
 * start of the item before it plus that duration; an item without a duration adds 0. A
 * reached item of a live or closed meeting shows its recorded start. In a live meeting the
 * item after the current one starts at the later of now (on the day of the meeting) and the
 * start of the current item plus its duration, and the rest follows from there.
 */
export function agendaPlan(
  items: readonly (Pick<AgendaItem, 'id' | 'estimatedMinutes'> & { readonly startedAt?: IsoDateTime | null })[],
  meeting: AgendaPlanMeeting,
  now: Date = new Date(),
): AgendaPlan {
  const durations = items.map((i) => i.estimatedMinutes ?? null);
  const total = durations.some((d) => d !== null) ? durations.reduce<number>((s, d) => s + (d ?? 0), 0) : null;
  if (!meeting.startTime) {
    return { rows: durations.map((minutes) => ({ start: null, actual: false, minutes })), end: null, total, overrun: false };
  }
  const live = meeting.status === 'live';
  const current = live ? items.findIndex((i) => i.id === meeting.currentAgendaItemId) : -1;
  const today = berlin(now);
  const nowMinutes = meeting.date && today.date === meeting.date ? today.minutes : null;
  let cursor = wallMinutes(meeting.startTime);
  const rows = items.map((item, index): AgendaPlanRow => {
    const minutes = durations[index];
    const reached = meeting.status !== 'planned' && item.startedAt ? berlin(new Date(item.startedAt)).minutes : null;
    let start = reached ?? cursor;
    if (live && index === current + 1 && current >= 0 && nowMinutes !== null && reached === null) {
      start = Math.max(start, nowMinutes);
    }
    cursor = start + (minutes ?? 0);
    return { start, actual: reached !== null, minutes };
  });
  const end = cursor;
  const overrun = !!meeting.endTime && end > wallMinutes(meeting.endTime);
  return { rows, end, total, overrun };
}
