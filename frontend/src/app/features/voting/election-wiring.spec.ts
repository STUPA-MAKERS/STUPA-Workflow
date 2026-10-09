import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Subject, firstValueFrom } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { electionFields, mapMeetingVote } from '@core/api/mappers';
import { mockApiInterceptor } from '@core/api/mock-api.interceptor';
import type { ElectionConfig, ElectionResult, MeetingVote } from '@core/api/models';
import type { TranslationKey } from '@core/i18n/translations';
import { LiveVoteService } from '@core/ws/live-vote.service';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from '@core/ws/live-vote.source';
import type { ClientMessage, ServerMessage } from '@core/ws/ws-messages';
import type { MeetingChannel } from '@core/ws/ws.service';
import { vote } from '../../../testing/meeting-fixtures';
import { liveOpenedVote } from '../meetings/meetings-display.util';
import { electionSnippet, voteSnippet } from '../meetings/meetings.util';
import { voteResultInfo } from '../meetings/vote-result/vote-result';

const ELECTION: ElectionConfig = {
  seats: 2,
  candidates: [
    { id: 'c1', name: 'Anna' },
    { id: 'c2', name: 'Ben' },
    { id: 'c3', name: 'Cem' },
  ],
  secret: true,
};
const RESULT: ElectionResult = {
  counts: { c1: 3, c2: 5, c3: 1 },
  abstentions: 2,
  ballots: 6,
  elected: ['c2', 'c1'],
};

function election(over: Partial<MeetingVote> = {}): MeetingVote {
  return vote({
    question: 'Wahl der Referate',
    status: 'closed',
    result: 'elected',
    kind: 'election',
    election: ELECTION,
    electionResult: RESULT,
    round: 1,
    ...over,
  });
}

const t = (key: TranslationKey, params?: Record<string, string | number>) =>
  params ? `${key}${JSON.stringify(params)}` : key;

describe('election wiring (F2)', () => {
  it('writes the protocol callout like the backend', () => {
    expect(voteSnippet(election())).toBe(
      [
        '> [!abstimmung] **Wahl der Referate**',
        '> Wahl · 2 Posten',
        '> Ben: 5 · Anna: 3 · Cem: 1 · Enthaltungen: 2',
        '> Gewählt: Ben, Anna',
      ].join('\n'),
    );
  });

  it('writes the lot, the runoff and the single candidate', () => {
    const lot = electionSnippet(
      election({
        round: 2,
        electionResult: { ...RESULT, elected: ['c1'], lot: { among: ['c1', 'c3'], seats: 1, drawn: ['c1'] } },
      }),
    );
    expect(lot).toContain('> Wahl · 2 Posten · Stichwahl (2. Wahlgang)');
    expect(lot).toContain('> Durch Los entschieden.');
    const pending = electionSnippet(
      election({ electionResult: { ...RESULT, elected: [], lot: { among: ['c1', 'c2'], seats: 1, drawn: null } } }),
    );
    expect(pending).toContain('> Gewählt: niemand');
    expect(pending).toContain('> Gleichstand: das Los steht aus.');
    const runoff = electionSnippet(
      election({ electionResult: { ...RESULT, elected: ['c2'], runoff: { candidateIds: ['c1', 'c3'], seats: 1 } } }),
    );
    expect(runoff).toContain('> Stichwahl (2. Wahlgang) um 1 Posten: Anna, Cem');
    const single = electionSnippet(
      election({
        election: { seats: 1, candidates: [{ id: 'c1', name: 'Anna' }], secret: true },
        electionResult: { counts: { yes: 7, no: 2 }, abstentions: 1, ballots: 10, yes: 7, no: 2, elected: ['c1'] },
      }),
    );
    expect(single).toContain('> Kandidatur: Anna');
    expect(single).toContain('> ja: 7, nein: 2, enthaltung: 1');
    // An open election has no result lines; a vote without a question is a "Wahlgang".
    expect(electionSnippet(election({ question: null, electionResult: null }))).toBe(
      '> [!abstimmung] **Wahlgang**\n> Wahl · 2 Posten',
    );
    expect(electionSnippet(election({ election: null }))).toBe(
      '> [!abstimmung] **Wahl der Referate**\n> Wahl · 1 Posten',
    );
  });

  it('gives the editor card of an election its caption and status', () => {
    const info = voteResultInfo(election({ closedAt: '2026-06-12T16:52:00Z' }), t, 'de');
    expect(info.caption).toMatch(/^election\.kind · election\.seats\.other\{"n":2\} · \d\d:\d\d$/);
    expect(info.result).toEqual({ label: 'election.status.elected', tone: 'passed' });
    const tie = voteResultInfo(election({ result: 'tie', closedAt: null }), t, 'de');
    expect(tie.result?.tone).toBe('rejected');
    expect(voteResultInfo(election({ status: 'open' }), t, 'de').result).toBeNull();
  });

  it('maps the election fields of a meeting vote and leaves a motion as it was', () => {
    expect(electionFields({})).toEqual({});
    const mapped = mapMeetingVote({ id: 'e1', status: 'open', kind: 'election', election: ELECTION });
    expect(mapped).toMatchObject({
      kind: 'election',
      election: ELECTION,
      electionResult: null,
      parentVoteId: null,
      round: 1,
    });
    expect(mapMeetingVote({ id: 'v1', status: 'open' })).not.toHaveProperty('kind');
    const opened = liveOpenedVote({
      type: 'vote_opened',
      voteId: 'e2',
      options: ['c1', 'abstain'],
      closesAt: null,
      kind: 'election',
      election: ELECTION,
      round: 2,
    });
    expect(opened).toMatchObject({ kind: 'election', election: ELECTION, round: 2 });
    expect(
      liveOpenedVote({ type: 'vote_opened', voteId: 'e3', options: [], closesAt: null, kind: 'election' }),
    ).toMatchObject({ election: null, round: 1 });
  });

  it('takes the lot frame into the live result', () => {
    const subject = new Subject<ServerMessage>();
    const channel: MeetingChannel = {
      messages$: subject.asObservable(),
      send: (_msg: ClientMessage) => {},
      close: () => {},
    };
    const source: LiveVoteSource = { connectMeeting: () => channel };
    TestBed.configureTestingModule({ providers: [{ provide: LIVE_VOTE_SOURCE, useValue: source }] });
    const session = TestBed.inject(LiveVoteService).open('m-1', { beamer: true });
    const er: ElectionResult = { ...RESULT, elected: ['c1'], lot: { among: ['c1', 'c2'], seats: 1, drawn: ['c1'] } };
    // A screen that joined after the close takes the counts of the frame.
    subject.next({ type: 'vote_lot_drawn', voteId: 'e1', result: 'elected', electionResult: er });
    expect(session.result()).toMatchObject({ voteId: 'e1', result: 'elected', counts: er.counts });
    subject.next({ type: 'vote_closed', voteId: 'e2', result: 'tie', counts: { c1: 1 }, failedReason: null });
    subject.next({ type: 'vote_lot_drawn', voteId: 'e2', result: 'elected', electionResult: er });
    expect(session.result()).toMatchObject({ voteId: 'e2', counts: { c1: 1 }, electionResult: er });
  });

  describe('mock API', () => {
    function api(): ApiClient {
      TestBed.configureTestingModule({
        providers: [
          provideHttpClient(withInterceptors([mockApiInterceptor])),
          provideHttpClientTesting(),
          { provide: USE_MOCK_API, useValue: true },
        ],
      });
      return TestBed.inject(ApiClient);
    }

    it('reads the demo election, draws its lot once and refuses a runoff', async () => {
      const client = api();
      const id = 'a0000000-0000-0000-0000-0000000000e1';
      const before = await firstValueFrom(client.getVote(id));
      expect(before).toMatchObject({ kind: 'election', result: 'tie' });
      const after = await firstValueFrom(client.drawElectionLot(id));
      expect(after.result).toBe('elected');
      expect(after.electionResult?.lot?.drawn).toEqual(['c1']);
      await expect(firstValueFrom(client.drawElectionLot(id))).rejects.toMatchObject({
        error: { code: 'no_lot_pending' },
      });
      await expect(firstValueFrom(client.createElectionRunoff(id))).rejects.toMatchObject({
        error: { code: 'no_runoff_pending' },
      });
      await expect(firstValueFrom(client.drawElectionLot('nope'))).rejects.toMatchObject({
        error: { code: 'not_an_election' },
      });
    });

    it('opens an election with the server ids and casts a list', async () => {
      const client = api();
      const meeting = await firstValueFrom(
        client.openMeetingVote('d0000000-0000-0000-0000-000000000001', {
          agendaItemId: 'ag-s6',
          kind: 'election',
          question: 'Wahl der Kassenprüfung',
          seats: 2,
          secret: false,
          candidates: [{ name: 'Anna' }, { name: 'Ben', principalId: 'p-1' }, { name: 'Cem' }],
        }),
      );
      const created = meeting.votes.at(-1)!;
      expect(created.kind).toBe('election');
      expect(created.election?.candidates.map((c) => c.id)).toEqual(['c1', 'c2', 'c3']);
      expect(created.options).toEqual(['c1', 'c2', 'c3', 'abstain']);
      await firstValueFrom(client.castBallot(created.id, ['c1', 'c3']));
      const read = await firstValueFrom(client.getVote(created.id));
      expect(read.myBallot).toMatchObject({ cast: true, choices: ['c1', 'c3'] });
    });
  });
});
