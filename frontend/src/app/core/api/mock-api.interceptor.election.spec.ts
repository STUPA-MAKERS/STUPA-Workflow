import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from './api.config';
import type { Vote } from './models';
import { mockApiInterceptor } from './mock-api.interceptor';

/**
 * F2 personnel elections in mock mode: the demo election with its tie, the lot, the
 * runoff refusals and elections that the demo creates. A file of its own, because the
 * mock meeting is module state and the main spec deletes the demo election.
 */
describe('mockApiInterceptor — elections (F2)', () => {
  const ELECTION = 'a0000000-0000-0000-0000-0000000000e1';
  const MOTION = 'a0000000-0000-0000-0000-0000000000a1';
  let http: HttpClient;
  let ctrl: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([mockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
      ],
    });
    http = TestBed.inject(HttpClient);
    ctrl = TestBed.inject(HttpTestingController);
  });

  afterEach(() => ctrl.verify());

  const getVote = (id: string) => firstValueFrom(http.get<Vote>(`/api/votes/${id}`));
  const post = <T>(url: string, body: unknown = {}) => firstValueFrom(http.post<T>(url, body));

  interface Row {
    id: string;
    kind?: string;
    options: string[];
    secret?: boolean;
    guestsVote?: boolean;
    election?: { seats: number; secret: boolean; guestsVote: boolean; candidates: { id: string; name: string; principalId: string | null }[] };
  }
  const createElection = async (body: Record<string, unknown>): Promise<Row> => {
    const m = await post<{ votes: Row[] }>('/api/meetings/m1/votes', { kind: 'election', ...body });
    return m.votes[m.votes.length - 1];
  };

  it('serves the closed demo election with its pending lot', async () => {
    const v = await getVote(ELECTION);
    expect(v).toMatchObject({
      id: ELECTION,
      kind: 'election',
      applicationId: null,
      status: 'closed',
      result: 'tie',
      secret: true,
      round: 1,
      parentVoteId: null,
      myBallot: { cast: false, choice: null },
    });
    expect(v.config.options).toEqual(['c1', 'c2', 'c3', 'abstain']);
    expect(v.tally).toMatchObject({ revealed: true, eligible: 12, voted: 12 });
    expect(v.electionResult?.lot).toMatchObject({ among: ['c1', 'c2'], seats: 1, drawn: null });
  });

  it('refuses a runoff for a tie and the lot for a motion or an unknown vote', async () => {
    await expect(post(`/api/votes/${ELECTION}/runoff`)).rejects.toMatchObject({
      status: 409,
      error: expect.objectContaining({ code: 'no_runoff_pending' }),
    });
    for (const id of [MOTION, 'nope']) {
      await expect(post(`/api/votes/${id}/draw-lot`)).rejects.toMatchObject({
        status: 409,
        error: expect.objectContaining({ code: 'not_an_election' }),
      });
      await expect(post(`/api/votes/${id}/runoff`)).rejects.toMatchObject({
        status: 409,
        error: expect.objectContaining({ code: 'not_an_election' }),
      });
    }
  });

  it('draws the lot once: the first tied candidate is elected', async () => {
    const v = await post<Vote>(`/api/votes/${ELECTION}/draw-lot`);
    expect(v.result).toBe('elected');
    expect(v.electionResult?.elected).toEqual(['c1']);
    expect(v.electionResult?.lot).toMatchObject({ drawn: ['c1'], byName: 'Demo-Nutzer:in' });
    // The vote is decided now: no second lot.
    await expect(post(`/api/votes/${ELECTION}/draw-lot`)).rejects.toMatchObject({
      status: 409,
      error: expect.objectContaining({ code: 'no_lot_pending' }),
    });
  });

  it('creates an open election with candidate ids, and a yes/no ballot for a single candidate', async () => {
    const two = await createElection({
      agendaItemId: 'ag-s5',
      seats: 1,
      secret: false,
      guestsVote: true,
      candidates: [{ name: 'Ada', principalId: 'p-1' }, { name: 'Ben' }],
    });
    expect(two).toMatchObject({ kind: 'election', secret: false, options: ['c1', 'c2', 'abstain'] });
    expect(two.election).toEqual({
      seats: 1,
      secret: false,
      guestsVote: true,
      candidates: [
        { id: 'c1', name: 'Ada', principalId: 'p-1' },
        { id: 'c2', name: 'Ben', principalId: null },
      ],
    });
    const one = await createElection({ candidates: [{ name: 'Cleo' }] });
    expect(one).toMatchObject({ secret: true, options: ['yes', 'no', 'abstain'] });
    expect(one.election).toMatchObject({ seats: 1, secret: true, guestsVote: false });
    const none = await createElection({});
    expect(none.election?.candidates).toEqual([]);
    const detail = await getVote(none.id);
    expect(detail).toMatchObject({ kind: 'election', status: 'open', round: 1, electionResult: null });
  });

  it('shows the own election ballot: its picks when open, only "cast" when secret', async () => {
    const open = await createElection({ secret: false, candidates: [{ name: 'Ada' }, { name: 'Ben' }] });
    await post(`/api/votes/${open.id}/ballot`, { choice: ['c2'] });
    expect((await getVote(open.id)).myBallot).toEqual({ cast: true, choice: null, choices: ['c2'] });

    const single = await createElection({ secret: false, candidates: [{ name: 'Cleo' }] });
    await post(`/api/votes/${single.id}/ballot`, { choice: 'yes' });
    expect((await getVote(single.id)).myBallot).toEqual({ cast: true, choice: 'yes' });

    const secret = await createElection({ candidates: [{ name: 'Ada' }, { name: 'Ben' }] });
    await post(`/api/votes/${secret.id}/ballot`, { choice: ['c1'] });
    expect((await getVote(secret.id)).myBallot).toEqual({ cast: true, choice: null });
  });

  it('keeps a list ballot of a motion in the detail and the vote list', async () => {
    await post('/api/votes/vote-list/ballot', { choice: ['yes'] });
    expect((await getVote('vote-list')).myBallot).toEqual({ cast: true, choice: null, choices: ['yes'] });
    const demo = 'b0000000-0000-0000-0000-000000000001';
    await post(`/api/votes/${demo}/ballot`, { choice: ['no'] });
    const detail = await getVote(demo);
    expect(detail.myBallot).toMatchObject({ cast: true, choice: null, choices: ['no'] });
  });
});
