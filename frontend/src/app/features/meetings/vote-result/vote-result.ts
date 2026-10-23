import type { MeetingVote } from '@core/api/models';
import { toFormatLocale } from '@core/i18n/i18n.service';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type {
  VoteCalloutInfo,
  VoteCalloutResolver,
} from '@stupa-makers/ui-kit/markdown-editor';
import { electionMeta, pollMeta, voteSnippetQuestion } from '../meetings.util';
import { electionCaption, electionStatus } from '../../voting/election.util';
import { pollCaption } from '../../voting/poll.util';
import { clock } from '@shared/date-format';

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
  if (vote.kind === 'poll') return pollResultInfo(vote, t, locale);
  const parts = [t('meetings.voteResult.caption')];
  const time = clock(vote.closedAt, toFormatLocale(locale));
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
  const time = clock(vote.closedAt, toFormatLocale(locale));
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

/** The card of a poll: "Umfrage · Einzelwahl · 18:52". A poll has no result. */
function pollResultInfo(vote: MeetingVote, t: Translate, locale: string): VoteCalloutInfo {
  const parts = vote.poll ? [pollCaption(vote.poll, t)] : [t('meetings.vote.kind.poll')];
  const time = clock(vote.closedAt, toFormatLocale(locale));
  if (time) parts.push(time);
  return {
    caption: parts.join(' · '),
    result: null,
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
  const byQuestion = new Map<string, MeetingVote[]>();
  for (const v of votes) {
    if (v.status !== 'closed') continue;
    if (v.kind !== 'election' && v.kind !== 'poll' && !(v.question?.trim() || v.title?.trim())) continue;
    // A runoff names its round in the head, so the two rounds of an election
    // keep apart (see `voteSnippetQuestion`).
    const key = normalizeQuestion(voteSnippetQuestion(v));
    byQuestion.set(key, [...(byQuestion.get(key) ?? []), v]);
  }
  return (question, lines) => {
    const found = byQuestion.get(normalizeQuestion(question)) ?? [];
    // Two votes can share a question. A poll or election card names its kind in its
    // first line, so the vote of that kind wins; otherwise the last vote wins.
    const kind = lines?.[0]?.trim();
    const last = [...found].reverse();
    const vote = last.find((v) => kind != null && kindLine(v) === kind) ?? last[0];
    return vote ? voteResultInfo(vote, t, locale) : null;
  };
}

/** The kind line that the snippet of a vote writes under its head, if it has one. */
function kindLine(vote: MeetingVote): string | null {
  if (vote.kind === 'poll' && vote.poll) return pollMeta(vote.poll);
  if (vote.kind === 'election' && vote.election) return electionMeta(vote);
  return null;
}
