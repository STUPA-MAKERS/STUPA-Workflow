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
    ch.close();
  });

  it('increments the chosen option on a cast frame', () => {
    const ch = source.connectMeeting('m-1');
    const { sink, push } = collect();
    ch.messages$.subscribe(push);
    ch.send({ type: 'cast', voteId: 'vote-demo', choice: 'no' });
    const tally = sink.find((m) => m.type === 'vote_tally') as VoteTallyMsg;
    expect(tally.counts['no']).toBe(3); // 2 → 3
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
    jest.advanceTimersByTime(200); // weit über die 12 Berechtigten hinaus
    const last = tallies[tallies.length - 1];
    const cast = Object.values(last.counts).reduce((a, b) => a + b, 0);
    expect(cast).toBe(12); // bei eligible gedeckelt
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
