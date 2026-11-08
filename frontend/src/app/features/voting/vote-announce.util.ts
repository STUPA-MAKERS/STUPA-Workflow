import type { Vote, VoteStatus } from '@core/api/models';
import type { Translate } from '@core/i18n/translations';
import { closedStatus } from './election.util';

/** The status of a vote as it was last read: the base of the next announcement. */
export interface SeenVote {
  readonly id: string;
  readonly status: VoteStatus;
}

/**
 * The name of a vote in an announcement (spec 000518): its question and where it is held,
 * "Frage – 34. Sitzung · TOP 3". Without a question it is "Abstimmung"; without a meeting the
 * place is left out, and without a TOP it is the meeting alone.
 */
export function voteSubject(
  t: Translate,
  question: string | null | undefined,
  meetingTitle: string | null | undefined,
  position: number | null | undefined,
): string {
  const name = question?.trim() || t('voting.live.vote');
  if (!meetingTitle) return name;
  const where =
    position === null || position === undefined ? meetingTitle : t('voting.panel.where', { meeting: meetingTitle, n: position });
  return `${name} – ${where}`;
}

/**
 * The text that tells a screen reader how the shown vote changed since `before`: it opened,
 * or it closed with its result. Any other change, a first read or another vote gives ''
 * (which the announcer ignores).
 */
export function voteChangeText(t: Translate, before: SeenVote | null, vote: Vote, subject: string): string {
  if (before?.id !== vote.id) return '';
  if (before.status === 'draft' && vote.status === 'open') return t('voting.live.opened', { subject });
  if (before.status !== 'open' || vote.status !== 'closed') return '';
  const result = vote.result ? t(closedStatus(vote.kind, vote.result).key) : '';
  return t('voting.live.closed', { subject, result });
}
