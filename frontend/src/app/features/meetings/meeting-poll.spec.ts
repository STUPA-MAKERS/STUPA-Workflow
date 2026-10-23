import { render, screen } from '@testing-library/angular';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { MeetingVote, PollConfig, PollResult } from '@core/api/models';
import { de } from '@core/i18n/translations';
import type { TranslationKey } from '@core/i18n/translations';
import { vote } from '../../../testing/meeting-fixtures';
import { liveOpenedVote, voteMetaLine } from './meetings-display.util';
import { pollSnippet, voteSnippet, voteSnippetQuestion } from './meetings.util';
import { VoteCardComponent } from './vote-card/vote-card.component';
import { voteResultInfo, voteResultResolver } from './vote-result/vote-result';

/** The German catalog with `{param}` filled in. */
function t(key: TranslationKey, params: Record<string, string | number> = {}): string {
  const text = (de as Record<string, string>)[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k: string) => String(params[k] ?? ''));
}

const SINGLE: PollConfig = {
  mode: 'single',
  options: [
    { id: 'o1', label: 'Ja' },
    { id: 'o2', label: 'Nein' },
    { id: 'o3', label: 'Café\nMitte' },
  ],
  secret: false,
};
const DATE: PollConfig = {
  mode: 'date',
  options: [
    { id: 'o1', start: '2026-11-03T17:00:00Z', end: '2026-11-03T19:00:00Z' },
    { id: 'o2', start: '2026-11-04T17:00:00Z' },
  ],
  secret: false,
};
const RESULT: PollResult = {
  counts: { o1: 4, o2: 1, o3: 4 },
  abstentions: 1,
  ballots: 10,
  order: ['o1', 'o3', 'o2'],
  top: ['o1', 'o3'],
};

function poll(over: Partial<MeetingVote> = {}): MeetingVote {
  return vote({
    kind: 'poll',
    poll: SINGLE,
    question: 'Wohin?',
    status: 'closed',
    result: null,
    counts: { o1: 4, o2: 1, o3: 4, abstain: 1 },
    pollResult: RESULT,
    closedAt: '2026-09-29T16:52:00Z',
    ...over,
  });
}

describe('poll snippet (same text as the backend build_poll_snippet)', () => {
  it('a closed single poll lists counts only, highest first', () => {
    expect(voteSnippet(poll()).split('\n')).toEqual([
      '> [!abstimmung] **Wohin?**',
      '> Umfrage · Einzelwahl',
      '> Ja: 4',
      '> Café Mitte: 4',
      '> Nein: 1',
      '> Enthaltungen: 1',
      '> Meiste Stimmen: Ja, Café Mitte',
      '> 10 Antworten · Meinungsbild, kein Beschluss',
    ]);
  });

  it('a closed date poll writes "3 (+2)" and the best date', () => {
    const result: PollResult = {
      counts: { o1: 3, o2: 3 },
      maybe: { o1: 2 },
      abstentions: 0,
      ballots: 5,
      order: ['o1', 'o2'],
      top: ['o1'],
    };
    const v = poll({ poll: DATE, pollResult: result, question: null });
    expect(voteSnippetQuestion(v)).toBe('Umfrage');
    expect(pollSnippet(v, DATE).split('\n')).toEqual([
      '> [!abstimmung] **Umfrage**',
      '> Terminumfrage',
      '> Di, 3.11. · 18:00–20:00: 3 (+2)',
      '> Mi, 4.11. · 18:00: 3 (+0)',
      '> Zahl = Ja, (+n) = Vielleicht',
      '> Bester Termin: Di, 3.11. · 18:00–20:00',
      '> 5 Antworten · Meinungsbild, kein Beschluss',
    ]);
  });

  it('an open poll has no counts; a result without votes names no top', () => {
    const multi: PollConfig = { ...SINGLE, mode: 'multi', maxChoices: 2 };
    expect(voteSnippet(poll({ poll: multi, pollResult: null, status: 'open' }))).toBe(
      '> [!abstimmung] **Wohin?**\n> Umfrage · Mehrfachwahl, höchstens 2',
    );
    const empty: PollResult = { counts: {}, abstentions: 0, ballots: 0, order: [], top: [] };
    const text = pollSnippet(poll({ poll: { ...multi, maxChoices: null }, pollResult: empty }), {
      ...multi,
      maxChoices: null,
    });
    expect(text).toContain('> Umfrage · Mehrfachwahl\n> Ja: 0\n> Nein: 0');
    expect(text).not.toContain('Meiste Stimmen');
    expect(text.endsWith('> 0 Antworten · Meinungsbild, kein Beschluss')).toBe(true);
  });
});

describe('poll in the meeting', () => {
  it('the protocol card has a caption and no result', () => {
    const info = voteResultInfo(poll(), t, 'de');
    expect(info.caption).toMatch(/^Umfrage · Einzelwahl · \d\d:52$/);
    expect(info.result).toBeNull();
    expect(voteResultInfo(poll({ poll: null, closedAt: null }), t, 'de').caption).toBe('Umfrage');
    // The resolver finds a poll by its question.
    expect(voteResultResolver([poll()], t, 'de')('Wohin?')?.result).toBeNull();
  });

  it('the rules line names only the secrecy', () => {
    const line = voteMetaLine(
      poll({ majorityRule: 'simple', quorum: { type: 'count', value: 3 }, secret: true, closedAt: null }),
      t,
      'de',
    );
    expect(line).toBe('geheime Abstimmung');
  });

  it('a live open event carries the poll', () => {
    const v = liveOpenedVote({
      type: 'vote_opened',
      voteId: 'p1',
      options: [],
      closesAt: null,
      kind: 'poll',
      poll: SINGLE,
    });
    expect(v.kind).toBe('poll');
    expect(v.poll).toBe(SINGLE);
    expect(liveOpenedVote({ type: 'vote_opened', voteId: 'p2', options: [], closesAt: null, kind: 'poll' }).poll).toBeNull();
  });

  describe('the vote card', () => {
    async function card(v: MeetingVote, canVote = false) {
      return render(VoteCardComponent, {
        inputs: { vote: v, meetingStatus: 'live', canManage: true, canRun: true, canVote },
        providers: [{ provide: ApiClient, useValue: { castBallot: () => of({ status: 'cast' }) } }],
      });
    }

    it('a closed poll shows "Umfrage beendet", the counts and no decision', async () => {
      await card(poll());
      expect(screen.getByText('Umfrage beendet')).toBeInTheDocument();
      expect(screen.getByText('Umfrage · Einzelwahl')).toBeInTheDocument();
      expect(screen.getByText('Meiste Stimmen: Ja, Café Mitte')).toBeInTheDocument();
      expect(screen.queryByText('Abgelehnt')).toBeNull();
      expect(screen.queryByText('Angenommen')).toBeNull();
    });

    it('an open poll shows "Umfrage offen" and the poll ballot', async () => {
      await card(
        poll({ status: 'open', pollResult: null, counts: null, poll: DATE, guestsVote: true, presentMembers: 3, presentGuests: 1 }),
        true,
      );
      expect(screen.getByText('Umfrage offen')).toBeInTheDocument();
      expect(screen.getAllByRole('radiogroup')).toHaveLength(2);
      expect(screen.getByRole('button', { name: 'Antworten abgeben' })).toBeDisabled();
    });

    it('a closed poll with guests shows no majority line', async () => {
      await card(poll({ guestsVote: true, presentMembers: 3, presentGuests: 1 }));
      expect(screen.queryByText('Mehrheit der abgegebenen Stimmen')).toBeNull();
    });
  });
});
