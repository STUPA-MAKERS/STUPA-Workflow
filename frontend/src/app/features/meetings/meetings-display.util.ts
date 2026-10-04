/** Pure, DI-free display helpers for the meetings feature. */

import { toFormatLocale } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  I18nMap,
  Meeting,
  MeetingVote,
  SelfAttendanceStatus,
} from '@core/api/models';
import type { BadgeVariant, IconName } from '@stupa-makers/ui-kit';
import type { ServerMessage } from '@core/ws/ws-messages';

/** Canonical ballot options. The pass/fail evaluation needs yes, no and abstain. */
export const FIXED_VOTE_OPTIONS = ['yes', 'no', 'abstain'] as const;

/**
 * The status mappers return status variants only (coloured text). `neutral` is a tag
 * (a grey plate), so a status that has no colour of its own uses `info` (muted text).
 */
export function meetingStatusVariant(status: Meeting['status']): BadgeVariant {
  return status === 'live' ? 'success' : 'info';
}

export function meetingStatusKey(status: Meeting['status']): TranslationKey {
  return `meetings.status.${status}` as TranslationKey;
}

export function voteStatusVariant(status: MeetingVote['status']): BadgeVariant {
  if (status === 'open') return 'success';
  if (status === 'closed') return 'info';
  return status === 'cancelled' ? 'danger' : 'warning';
}

export function voteStatusKey(status: MeetingVote['status']): TranslationKey {
  return `meetings.voteStatus.${status}` as TranslationKey;
}

export function voteResultKey(result: string | null | undefined): TranslationKey {
  return `vote.result.${result ?? 'tie'}` as TranslationKey;
}

export function voteResultVariant(result: string | null | undefined): BadgeVariant {
  return result === 'passed' ? 'success' : result === 'rejected' ? 'danger' : 'info';
}

export function attendanceKey(status: AttendanceStatus | 'unknown'): TranslationKey {
  return `meetings.attendance.${status}` as TranslationKey;
}

export function attendanceButtonVariant(
  status: AttendanceStatus,
): 'primary' | 'secondary' | 'danger' {
  return status === 'present' ? 'primary' : status === 'excused' ? 'secondary' : 'danger';
}

export function attendanceIcon(status: AttendanceStatus): IconName {
  return status === 'present' ? 'check' : status === 'excused' ? 'half' : 'remove';
}

export function attendanceBadgeVariant(status: AttendanceStatus): BadgeVariant {
  return status === 'present' ? 'success' : status === 'excused' ? 'warning' : 'danger';
}

/** The statuses a member reports for the own record (Z2). Only the lead records `absent`. */
export const SELF_ATTENDANCE_STATUSES: readonly SelfAttendanceStatus[] = ['present', 'excused'];

/** The member labels: "Anwesend / Abwesend", where "Abwesend" is `excused` (Z2). */
export function selfAttendanceKey(status: SelfAttendanceStatus): TranslationKey {
  return status === 'present' ? 'meetings.attendance.selfPresent' : 'meetings.attendance.selfExcused';
}

/**
 * The status label that a member sees on any row (Z2): "Anwesend" or "Abwesend".
 * A member does not see the difference between `excused` and `absent`; only the
 * meeting lead sees "Entschuldigt" and "Unentschuldigt".
 */
export function memberAttendanceKey(status: AttendanceStatus): TranslationKey {
  return selfAttendanceKey(status === 'present' ? 'present' : 'excused');
}

/** The badge colour that a member sees. `excused` and `absent` look the same (Z2). */
export function memberAttendanceBadgeVariant(status: AttendanceStatus): BadgeVariant {
  return status === 'present' ? 'success' : 'warning';
}

/**
 * True when a member may report this status for this record: the own row, a status
 * other than `absent`, and a record that the meeting lead did not set (O15).
 */
export function canReportOwn(member: Attendance, status: AttendanceStatus): boolean {
  return member.isSelf && member.source !== 'lead' && status !== 'absent';
}

export function countEntries(vote: MeetingVote): { key: string; value: number }[] {
  return Object.entries(vote.counts ?? {}).map(([key, value]) => ({ key, value }));
}

/** Selectable options of a vote. The fallback is the set of tally keys. */
export function voteOptionsFor(vote: MeetingVote): string[] {
  return vote.options.length ? vote.options : Object.keys(vote.counts ?? {});
}

/** Resolve an i18n map for the given locale. The fallback is de, then the first value. */
export function resolveI18n(map: I18nMap | null | undefined, locale: string): string {
  if (!map) return '';
  return map[locale] ?? map['de'] ?? Object.values(map)[0] ?? '';
}

/** Display label of a ballot option (yes→Ja …). An unknown option stays raw. */
export function voteOptionLabel(
  opt: string,
  translate: (key: TranslationKey) => string,
): string {
  const key = `vote.option.${opt}` as TranslationKey;
  const label = translate(key);
  return label === key ? opt : label;
}

/** The stable problem+json `code` of an HTTP error (for example `open_vote`), or `''`. */
export function errorCode(err: unknown): string {
  const body = (err as { error?: { code?: string } } | null)?.error;
  return typeof body?.code === 'string' ? body.code : '';
}

/** The problem+json `detail` message of an HTTP error, or an empty string. */
export function errorDetail(err: unknown): string {
  const body = (err as { error?: { detail?: string } } | null)?.error;
  return typeof body?.detail === 'string' ? body.detail : '';
}

/**
 * Assemble the protocol markdown from the ordered TOPs.
 * Top-level `#` headings are required. The protocol renderer numbers them
 * as "TOP n" on its own. Do not add a manual prefix and do not use `##`, because
 * that doubles the numbering.
 */
export function assembleProtocolMarkdown(agenda: AgendaItem[]): string {
  return agenda
    .map((t) => {
      const heading = `# ${t.title?.trim() || 'Tagesordnungspunkt'}`;
      const ref = t.applicationId ? `\n\n:::antrag{#${t.applicationId}}\n:::` : '';
      const body = t.body?.trim() ? `\n\n${t.body.trim()}` : '';
      return `${heading}${ref}${body}`;
    })
    .join('\n\n');
}

/** Beamer pick: the currently open vote, else the last closed one. */
export function pickBeamerVote(votes: MeetingVote[]): MeetingVote | null {
  return (
    votes.find((v) => v.status === 'open') ??
    [...votes].reverse().find((v) => v.status === 'closed') ??
    null
  );
}

/** Long localized date ("14. Juni 2026"). It mirrors the `ldate` pipe. */
export function longDate(isoDate: string, i18nLocale: string): string {
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return isoDate;
  return new Intl.DateTimeFormat(toFormatLocale(i18nLocale), { dateStyle: 'long' }).format(date);
}

/**
 * Clock time of a meeting as `HH:MM`, always 24 h.
 *
 * The API sends a SQL `time`, thus `18:00:00`. The seconds are noise on screen.
 * An empty value gives an empty string. A value that is not a time stays as it
 * is, because unreadable source text tells more than an invented time. The
 * format stays 24 h on purpose: `app-time-input` also forces 24 h, because the
 * native `type="time"` follows the browser locale and can show AM/PM.
 */
export function shortTime(value: string | null | undefined): string {
  const raw = (value ?? '').trim();
  const match = /^([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d(?:\.\d+)?)?$/.exec(raw);
  return match ? `${match[1].padStart(2, '0')}:${match[2]}` : raw;
}

/** `", 18:00"` suffix behind a meeting date, or an empty string. */
export function meetingTimeSuffix(value: string | null | undefined): string {
  const time = shortTime(value);
  return time ? `, ${time}` : '';
}

/** Placeholder vote for a live `vote_opened` that was not loaded yet (follower). */
export function liveOpenedVote(
  msg: Extract<ServerMessage, { type: 'vote_opened' }>,
): MeetingVote {
  return {
    id: msg.voteId,
    applicationId: msg.applicationId ?? null,
    agendaItemId: msg.agendaItemId ?? null,
    title: null,
    question: msg.question ?? null,
    options: msg.options ?? [],
    status: 'open',
    result: null,
    counts: null,
    leading: null,
    closesAt: msg.closesAt,
    voted: 0,
    present: 0,
    revealed: false,
    failedReason: null,
  };
}

/** The clock time (`HH:MM`, 24 h) of an ISO timestamp in local time, or `''`. */
export function clockTime(iso: string | null | undefined, i18nLocale: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(toFormatLocale(i18nLocale), {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(date);
}

/** The time line of a meeting row: a running meeting shows its start (`since`). */
export interface MeetingTimeText {
  /** `HH:MM` or `HH:MM–HH:MM`. Empty when the meeting has no time at all. */
  text: string;
  /** True for a live meeting with a known start: the row reads "seit HH:MM". */
  since: boolean;
}

/**
 * The time of a meeting row in the list.
 *
 * A planned meeting shows the planned start and end. A live meeting shows the real
 * start (`startedAt`, "seit 18:04"). A closed meeting shows the real start and close.
 * A meeting that started before the real times existed falls back to the planned
 * times.
 */
export function meetingTimeText(m: Meeting, i18nLocale: string): MeetingTimeText {
  const range = (a: string, b: string): string => (a && b ? `${a}–${b}` : a);
  const planned = range(shortTime(m.startTime), shortTime(m.endTime));
  const started = clockTime(m.startedAt, i18nLocale);
  if (m.status === 'live' && started) return { text: started, since: true };
  if (m.status === 'closed' && started) {
    return { text: range(started, clockTime(m.closedAt, i18nLocale)), since: false };
  }
  return { text: planned, since: false };
}

/** The date of a meeting as a local midnight, for the date block. `null` without a date. */
export function meetingDay(m: Meeting): string | null {
  return m.date ? `${m.date}T00:00:00` : null;
}
