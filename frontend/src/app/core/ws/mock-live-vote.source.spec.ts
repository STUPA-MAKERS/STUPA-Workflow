import { MockLiveVoteSource } from './mock-live-vote.source';
import type { ServerMessage, VoteTallyMsg } from './ws-messages';

function collect(): { sink: ServerMessage[]; push: (m: ServerMessage) => void } {
  const sink: ServerMessage[] = [];
  return { sink, push: (m) => sink.push(m) };
}

describe('MockLiveVoteSource', () => {
  let source: MockLiveVoteSource;

  beforeEach(() => {
    source = new MockLiveVoteSource();
  });

  it('replays meeting/vote/tally on subscribe (resync contract)', () => {
    const ch = source.connectMeeting('m-1');
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    ch.send({ type: 'subscribe' });
    expect(sink.map((m) => m.type)).toEqual(['meeting_state', 'vote_opened', 'vote_tally']);
    // Like the server, the replay marks the vote as one that was already open.
    expect(sink[1]).toEqual(expect.objectContaining({ voteId: 'vote-demo', replay: true }));
    ch.close();
  });

  it('counts a cast frame and hides the counts until every present member voted', () => {
    const ch = source.connectMeeting('m-1');
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'no' });
    const tally = sink.find((m) => m.type === 'vote_tally') as VoteTallyMsg;
    expect(tally.cast).toBe(9); // 8 → 9
    expect(tally.present).toBe(12);
    expect(tally.revealed).toBe(false);
    expect(tally.counts).toEqual({});
    expect(tally.leading).toBeNull();
    ch.close();
  });

  it('lets a screenshot script push a frame through the dev hook', () => {
    const ch = source.connectMeeting('m-1', true);
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    const hook = (globalThis as { __stupaMockLive?: { push(msg: ServerMessage): void } })
      .__stupaMockLive;
    hook?.push({ type: 'vote_cancelled', voteId: 'vote-demo' });
    expect(sink).toEqual([{ type: 'vote_cancelled', voteId: 'vote-demo' }]);
    ch.close();
  });

  it('counts the first pick of an election ballot, an empty one as abstain, and ignores unknown options', () => {
    const ch = source.connectMeeting('m-1');
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: ['no', 'yes'] });
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: [] });
    expect(sink.filter((m) => m.type === 'vote_tally').map((m) => (m as VoteTallyMsg).cast)).toEqual([9, 10]);
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'maybe' });
    expect(sink.filter((m) => m.type === 'vote_tally')).toHaveLength(2);
    ch.close();
  });

  it('never counts a cast above the eligible voters and reveals the counts at the end', () => {
    const ch = source.connectMeeting('m-1');
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    for (let i = 0; i < 6; i++) ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'yes' });
    const tallies = sink.filter((m) => m.type === 'vote_tally') as VoteTallyMsg[];
    expect(tallies).toHaveLength(4); // 8 → 12, then capped
    const last = tallies[tallies.length - 1];
    expect(last.revealed).toBe(true);
    expect(last.counts).toEqual({ yes: 9, no: 2, abstain: 1 });
    expect(last.leading).toBe('yes');
    ch.close();
  });

  it('ignores cast frames on the read-only beamer stream', () => {
    const ch = source.connectMeeting('m-1', true);
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'no' });
    expect(sink).toHaveLength(0);
    ch.close();
  });

  it('emits incoming votes on the timer and stops when eligible is reached', () => {
    jest.useFakeTimers();
    source.tickMs = 10;
    const ch = source.connectMeeting('m-1');
    const tallies: VoteTallyMsg[] = [];
    ch.messages$.subscribe((m) => {
      if (m.type === 'vote_tally') tallies.push(m);
    });
    jest.advanceTimersByTime(200); // well beyond the 12 eligible voters
    const last = tallies[tallies.length - 1];
    const cast = Object.values(last.counts).reduce((a, b) => a + b, 0);
    expect(cast).toBe(12); // capped at eligible
    ch.close();
    jest.useRealTimers();
  });

  it('recomputes leading and quorum as votes arrive', () => {
    const ch = source.connectMeeting('m-1');
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'no' });
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'no' });
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'no' });
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'no' });
    const tally = sink.filter((m) => m.type === 'vote_tally').pop() as VoteTallyMsg;
    // 8 + 4 = 12 ballots: every present member voted, so the counts show.
    expect(tally.revealed).toBe(true);
    expect(tally.counts['no']).toBe(6);
    expect(tally.leading).toBe('no'); // 2+4 = 6 > yes 5
    ch.close();
  });

  it('completes the stream on close', () => {
    const ch = source.connectMeeting('m-1');
    let completed = false;
    ch.messages$.subscribe({ complete: () => (completed = true) });
    ch.close();
    expect(completed).toBe(true);
  });
});
