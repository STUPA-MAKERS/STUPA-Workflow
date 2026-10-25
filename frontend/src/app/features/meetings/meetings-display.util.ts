/** Pure, DI-free display helpers for the meetings feature. */

import { toFormatLocale } from '@core/i18n/i18n.service';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  Meeting,
  MeetingVote,
  Quorum,
  SelfAttendanceStatus,
} from '@core/api/models';
import { clock, shortTime, weekdayDate } from '@shared/date-format';
import type { BadgeVariant } from '@stupa-makers/ui-kit';
import type { ServerMessage } from '@core/ws/ws-messages';

/** Canonical ballot options. The pass/fail evaluation needs yes, no and abstain. */
export const FIXED_VOTE_OPTIONS = ['yes', 'no', 'abstain'] as const;

/**
 * The status mappers return status variants only (coloured text). `neutral` is a tag
 * (a grey plate), so a status that has no colour of its own uses `info` (muted text).
 */
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

/** The member labels: "Anwesend / Abwesend", where "Abwesend" is `excused`. */
export function selfAttendanceKey(status: SelfAttendanceStatus): TranslationKey {
  return status === 'present' ? 'meetings.attendance.selfPresent' : 'meetings.attendance.selfExcused';
}

/**
 * The status label that a member sees on any row: "Anwesend" or "Abwesend".
 * A member does not see the difference between `excused` and `absent`; only the
 * meeting lead sees "Entschuldigt" and "Unentschuldigt".
 */
export function memberAttendanceKey(status: AttendanceStatus): TranslationKey {
  return selfAttendanceKey(status === 'present' ? 'present' : 'excused');
}

/**
 * True when a member may report this status for this record: the own row, a status
 * other than `absent`, and a record that the meeting lead did not set.
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

/** Display label of a ballot option (yes→Ja …). An unknown option stays raw. */
export function voteOptionLabel(
  opt: string,
  translate: (key: TranslationKey) => string,
): string {
  const key = `vote.option.${opt}` as TranslationKey;
  const label = translate(key);
  return label === key ? opt : label;
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

/** "35. Sitzung des Studierendenparlaments · Di, 13.10.2026": the meeting below the
 *  title of a dialog. */
export function meetingLine(m: Meeting, formatLocale: string): string {
  const day = weekdayDate(m.date, formatLocale);
  return day ? `${m.title} · ${day}` : m.title;
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
    secret: msg.secret,
    openedAt: new Date().toISOString(),
    voted: 0,
    present: 0,
    revealed: false,
    failedReason: null,
    ...(msg.kind === 'election'
      ? { kind: msg.kind, election: msg.election ?? null, round: msg.round ?? 1 }
      : {}),
    ...(msg.kind === 'poll' ? { kind: msg.kind, poll: msg.poll ?? null } : {}),
  };
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
  const started = clock(m.startedAt, toFormatLocale(i18nLocale));
  if (m.status === 'live' && started) return { text: started, since: true };
  if (m.status === 'closed' && started) {
    return { text: range(started, clock(m.closedAt, toFormatLocale(i18nLocale))), since: false };
  }
  return { text: planned, since: false };
}

/** The date of a meeting as a local midnight, for the date block. `null` without a date. */
export function meetingDay(m: Meeting): string | null {
  return m.date ? `${m.date}T00:00:00` : null;
}

/** The rule fields of a vote that the rules line reads. */
export interface VoteRules {
  majorityRule?: string | null;
  /** Unknown (a live vote before the next read) leaves the part out. */
  secret?: boolean;
  quorum?: Quorum | null;
  /** Admitted guests vote too: no quorum, the majority of the cast votes decides. */
  guestsVote?: boolean;
}

/** "Einfache Mehrheit", or "Einfache Mehrheit der abgegebenen Stimmen" for a vote with guests. */
export function majorityLabel(
  rule: string,
  guestsVote: boolean | undefined,
  t: Translate,
): string {
  const family = guestsVote ? 'vote.majorityCast' : 'vote.majority';
  return t(`${family}.${rule}` as TranslationKey);
}

/** "geheime Abstimmung" or "offene Abstimmung". */
export function secrecyLabel(secret: boolean, t: Translate): string {
  return t(secret ? 'meetings.vote.secretShort' : 'meetings.vote.publicShort');
}

/** "Quorum 12" or "Quorum 50 %". */
export function quorumLabel(quorum: Quorum, t: Translate): string {
  return t(quorum.type === 'percent' ? 'meetings.vote.quorumPercent' : 'meetings.vote.quorumCount', {
    n: quorum.value,
  });
}

/** The options of {@link voteRulesParts}. */
export interface VoteRulesOptions {
  /**
   * The ballot panel: "Absolute Mehrheit · Quorum 12 · geheime Abstimmung". The quorum
   * comes before the secrecy, and only a secret vote names it (an open vote is the rule
   * there, so "offene Abstimmung" says nothing).
   */
  ballot?: boolean;
}

/**
 * The rule parts of a vote: "Einfache Mehrheit · offene Abstimmung · Quorum 12" (the
 * meeting pages, the beamer, the public protocol), or the ballot form of
 * {@link VoteRulesOptions.ballot}. A part without data stays out: a vote that a live event
 * added before the next read has no rules yet, and a vote without a quorum shows none.
 */
export function voteRulesParts(vote: VoteRules, t: Translate, options: VoteRulesOptions = {}): string[] {
  const majority = vote.majorityRule ? [majorityLabel(vote.majorityRule, vote.guestsVote, t)] : [];
  const quorum = vote.quorum ? [quorumLabel(vote.quorum, t)] : [];
  if (options.ballot) {
    return [...majority, ...quorum, ...(vote.secret ? [secrecyLabel(true, t)] : [])];
  }
  const secrecy = vote.secret === undefined ? [] : [secrecyLabel(vote.secret, t)];
  return [...majority, ...secrecy, ...quorum];
}

/**
 * The rules line of a vote card: "Einfache Mehrheit · offene Abstimmung · Quorum 12 ·
 * seit 18:48" ({@link voteRulesParts}, then the time of the open or the end). A poll
 * shows only its secrecy and the time.
 */
export function voteMetaLine(vote: MeetingVote, translate: Translate, i18nLocale: string): string {
  const parts =
    vote.kind === 'poll'
      ? voteRulesParts({ secret: vote.secret }, translate)
      : voteRulesParts(vote, translate);
  if (vote.status === 'open') {
    const since = clock(vote.openedAt, toFormatLocale(i18nLocale));
    if (since) parts.push(translate('meetings.vote.since', { time: since }));
  } else if (vote.status === 'closed' || vote.status === 'cancelled') {
    const ended = clock(vote.closedAt, toFormatLocale(i18nLocale));
    if (ended) parts.push(translate('meetings.vote.endedAt', { time: ended }));
  }
  return parts.join(' · ');
}

/**
 * "19 Mitglieder + 7 Gäste anwesend" for a vote with guests, or `null` while the
 * counts are unknown (a vote that closed before the counts existed).
 */
export function guestComposition(
  members: number | null | undefined,
  guests: number | null | undefined,
  translate: Translate,
): string | null {
  if (members === null || members === undefined || guests === null || guests === undefined) {
    return null;
  }
  return translate('guests.vote.composition', { members, guests });
}
