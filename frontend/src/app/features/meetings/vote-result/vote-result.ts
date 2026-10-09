import type { MeetingVote } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  VoteCalloutInfo,
  VoteCalloutResolver,
} from '@stupa-makers/ui-kit/markdown-editor';
import { clockTime } from '../meetings-display.util';
import { voteSnippetQuestion } from '../meetings.util';
import { electionCaption, electionStatus } from '../../voting/election.util';

/** The translate function of the I18nService. */
type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

/**
 * The result block of a closed vote in the text of an agenda item.
 *
 * The text holds the vote as the protocol callout (`> [!abstimmung] **Frage**` and a
 * tally line). The editor shows it as a card; this module gives the card what the text
 * does not hold: the caption "Beschluss · 18:52 · Einfache Mehrheit" (`closedAt`, the
 * majority rule), the result under the rule of the vote and the labels in the language of
 * the page. A tie is a rejection (O18), so the result is "Angenommen" or "Abgelehnt".
 */
export function voteResultInfo(vote: MeetingVote, t: Translate, locale: string): VoteCalloutInfo {
  if (vote.kind === 'election') return electionResultInfo(vote, t, locale);
  const parts = [t('meetings.voteResult.caption')];
  const time = clockTime(vote.closedAt, locale);
  if (time) parts.push(time);
  if (vote.majorityRule) parts.push(t(`vote.majority.${vote.majorityRule}` as TranslationKey));
  const passed = vote.result === 'passed';
  return {
    caption: parts.join(' · '),
    result:
      vote.status === 'closed'
        ? {
            label: t(passed ? 'vote.result.passed' : 'vote.result.rejected'),
            tone: passed ? 'passed' : 'rejected',
          }
        : null,
    labels: {
      yes: t('vote.option.yes'),
      no: t('vote.option.no'),
      abstain: t('vote.option.abstain'),
      result: t('meetings.voteResult.result'),
    },
  };
}

/** The card of a personnel election (F2): "Wahl · 2 Posten · 18:52" and "Gewählt". */
function electionResultInfo(vote: MeetingVote, t: Translate, locale: string): VoteCalloutInfo {
  const parts = [electionCaption(vote.election ?? null, vote.round, t)];
  const time = clockTime(vote.closedAt, locale);
  if (time) parts.push(time);
  const elected = vote.result === 'elected';
  return {
    caption: parts.join(' · '),
    result:
      vote.status === 'closed'
        ? { label: t(electionStatus(vote.result).key), tone: elected ? 'passed' : 'rejected' }
        : null,
    labels: {
      yes: t('vote.option.yes'),
      no: t('vote.option.no'),
      abstain: t('vote.option.abstain'),
      result: t('meetings.voteResult.result'),
    },
  };
}

/**
 * The text of a question as the card reads it: without Markdown emphasis, code marks and
 * backslash escapes, with single spaces. The server escapes Markdown characters in the
 * snippet, the editor drops the bold marks.
 */
export function normalizeQuestion(text: string): string {
  return text
    .replace(/\\([\\`*_{}[\]()#+\-.!|>~])/g, '$1')
    .replace(/\*\*|__|`/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/**
 * The resolver of the editor: find the closed vote of a card by its question. The
 * question of the snippet is the question of the vote, else its title, with the round
 * of a runoff (see `voteSnippetQuestion`). A card of another meeting or a deleted vote stays plain.
 */
export function voteResultResolver(
  votes: readonly MeetingVote[],
  t: Translate,
  locale: string,
): VoteCalloutResolver {
  const byQuestion = new Map<string, MeetingVote>();
  for (const v of votes) {
    if (v.status !== 'closed') continue;
    if (v.kind !== 'election' && !(v.question?.trim() || v.title?.trim())) continue;
    // A runoff names its round in the head, so the two rounds of an election
    // keep apart (see `voteSnippetQuestion`).
    byQuestion.set(normalizeQuestion(voteSnippetQuestion(v)), v);
  }
  return (question) => {
    const vote = byQuestion.get(normalizeQuestion(question));
    return vote ? voteResultInfo(vote, t, locale) : null;
  };
}
