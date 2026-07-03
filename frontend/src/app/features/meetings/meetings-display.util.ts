/** Pure, DI-free display helpers for the meetings feature. */

import type { TranslationKey } from '@core/i18n/translations';
import type {
  AgendaItem,
  AttendanceStatus,
  I18nMap,
  Meeting,
  MeetingVote,
} from '@core/api/models';
import type { BadgeVariant, IconName } from '@stupa-makers/ui-kit';
import type { ServerMessage } from '@core/ws/ws-messages';

/** Canonical ballot options — pass/fail evaluation needs yes/no/abstain. */
export const FIXED_VOTE_OPTIONS = ['yes', 'no', 'abstain'] as const;

export function meetingStatusVariant(status: Meeting['status']): BadgeVariant {
  return status === 'live' ? 'success' : status === 'closed' ? 'neutral' : 'info';
}

export function meetingStatusKey(status: Meeting['status']): TranslationKey {
  return `meetings.status.${status}` as TranslationKey;
}

export function voteStatusVariant(status: MeetingVote['status']): BadgeVariant {
  if (status === 'open') return 'success';
  if (status === 'closed') return 'neutral';
  return status === 'cancelled' ? 'danger' : 'warning';
}

export function voteStatusKey(status: MeetingVote['status']): TranslationKey {
  return `meetings.voteStatus.${status}` as TranslationKey;
}

export function voteResultKey(result: string | null | undefined): TranslationKey {
  return `vote.result.${result ?? 'tie'}` as TranslationKey;
}

export function voteResultVariant(result: string | null | undefined): BadgeVariant {
  return result === 'passed' ? 'success' : result === 'rejected' ? 'danger' : 'neutral';
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

export function countEntries(vote: MeetingVote): { key: string; value: number }[] {
  return Object.entries(vote.counts ?? {}).map(([key, value]) => ({ key, value }));
}

/** Selectable options of a vote (fallback: keys of the tally). */
export function voteOptionsFor(vote: MeetingVote): string[] {
  return vote.options.length ? vote.options : Object.keys(vote.counts ?? {});
}

/** Resolve an i18n map for the given locale, falling back to de → first value. */
export function resolveI18n(map: I18nMap | null | undefined, locale: string): string {
  if (!map) return '';
  return map[locale] ?? map['de'] ?? Object.values(map)[0] ?? '';
}

/** Display label of a ballot option (yes→Ja …); unknown options stay raw. */
export function voteOptionLabel(
  opt: string,
  translate: (key: TranslationKey) => string,
): string {
  const key = `vote.option.${opt}` as TranslationKey;
  const label = translate(key);
  return label === key ? opt : label;
}

/** Concrete problem+json `detail` message from an HTTP error (or empty). */
export function errorDetail(err: unknown): string {
  const body = (err as { error?: { detail?: string } } | null)?.error;
  return typeof body?.detail === 'string' ? body.detail : '';
}

/**
 * Assemble the protocol markdown from the ordered TOPs. Top-level `#` headings
 * are required: pytex' protocol variant numbers them itself as "TOP n", so no
 * manual prefix and no `##` (which would double the numbering).
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

/** Long localized date ("14. Juni 2026") mirroring the `ldate` pipe. */
export function longDate(isoDate: string, i18nLocale: string): string {
  const date = new Date(isoDate);
  if (Number.isNaN(date.getTime())) return isoDate;
  const locale = i18nLocale === 'en' ? 'en-US' : 'de-DE';
  return new Intl.DateTimeFormat(locale, { dateStyle: 'long' }).format(date);
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
