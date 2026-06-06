import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { LiveVoteService } from './live-vote.service';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from './live-vote.source';
import type { MeetingChannel } from './ws.service';
import type { ClientMessage, ServerMessage } from './ws-messages';

/** Steuerbarer Kanal: Tests pushen Server-Frames und lesen gesendete Frames. */
class FakeChannel implements MeetingChannel {
  readonly subject = new Subject<ServerMessage>();
  readonly messages$ = this.subject.asObservable();
  readonly sent: ClientMessage[] = [];
  closed = false;
  send(msg: ClientMessage): void {
    this.sent.push(msg);
  }
  close(): void {
    this.closed = true;
  }
}

class FakeSource implements LiveVoteSource {
  readonly channels: FakeChannel[] = [];
  lastBeamer = false;
  connectMeeting(_meetingId: string, beamer = false): MeetingChannel {
    this.lastBeamer = beamer;
    const ch = new FakeChannel();
    this.channels.push(ch);
    return ch;
  }
}

describe('LiveVoteService', () => {
  let svc: LiveVoteService;
  let source: FakeSource;

  beforeEach(() => {
    source = new FakeSource();
    TestBed.configureTestingModule({
      providers: [{ provide: LIVE_VOTE_SOURCE, useValue: source }],
    });
    svc = TestBed.inject(LiveVoteService);
  });

  it('sends a subscribe frame on connect to resync state', () => {
    svc.open('m-1');
    expect(source.channels[0].sent[0]).toEqual({ type: 'subscribe' });
  });

  it('opens the beamer stream read-only when requested', () => {
    const s = svc.open('m-1', { beamer: true });
    expect(source.lastBeamer).toBe(true);
    // Beamer-Modus sendet keine cast-Frames.
    source.channels[0].subject.next({
      type: 'vote_opened',
      voteId: 'v1',
      applicationId: 'a1',
      options: ['yes', 'no'],
      closesAt: null,
    });
    s.cast('yes');
    expect(source.channels[0].sent.some((m) => m.type === 'cast')).toBe(false);
  });

  it('tracks meeting/vote/tally/result frames as signals', () => {
    const s = svc.open('m-1');
    const ch = source.channels[0];
    ch.subject.next({ type: 'meeting_state', activeApplicationId: 'a1', status: 'live' });
    ch.subject.next({
      type: 'vote_opened',
      voteId: 'v1',
      applicationId: 'a1',
      options: ['yes', 'no', 'abstain'],
      closesAt: null,
    });
    ch.subject.next({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 3, no: 1, abstain: 0 },
      eligible: 10,
      quorumMet: false,
      leading: 'yes',
    });
    expect(s.meeting()?.status).toBe('live');
    expect(s.openVote()?.options).toEqual(['yes', 'no', 'abstain']);
    expect(s.tally()?.counts['yes']).toBe(3);
  });

  it('resets tally and result when a new vote opens', () => {
    const s = svc.open('m-1');
    const ch = source.channels[0];
    ch.subject.next({
      type: 'vote_tally',
      voteId: 'v0',
      counts: { yes: 9 },
      eligible: 10,
      quorumMet: true,
      leading: 'yes',
    });
    ch.subject.next({
      type: 'vote_opened',
      voteId: 'v1',
      applicationId: 'a1',
      options: ['yes', 'no'],
      closesAt: null,
    });
    expect(s.tally()).toBeNull();
    expect(s.result()).toBeNull();
  });

  it('mirrors the closing counts into the tally so bars stay final', () => {
    const s = svc.open('m-1');
    const ch = source.channels[0];
    ch.subject.next({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 6, no: 1 },
      eligible: 12,
      quorumMet: true,
      leading: 'yes',
    });
    ch.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 7, no: 1 } });
    expect(s.result()?.result).toBe('passed');
    expect(s.tally()?.counts['yes']).toBe(7);
    expect(s.tally()?.eligible).toBe(12); // aus vorheriger Tally übernommen
  });

  it('captures error frames', () => {
    const s = svc.open('m-1');
    source.channels[0].subject.next({ type: 'error', code: 'not_eligible' });
    expect(s.errorCode()).toBe('not_eligible');
  });

  it('sends a cast frame referencing the open vote', () => {
    const s = svc.open('m-1');
    const ch = source.channels[0];
    ch.subject.next({
      type: 'vote_opened',
      voteId: 'v9',
      applicationId: 'a1',
      options: ['yes', 'no'],
      closesAt: null,
    });
    s.cast('no');
    expect(ch.sent).toContainEqual({ type: 'cast', voteId: 'v9', choice: 'no' });
  });

  it('ignores casts when no vote is open', () => {
    const s = svc.open('m-1');
    s.cast('yes');
    expect(source.channels[0].sent.some((m) => m.type === 'cast')).toBe(false);
  });

  it('reconnects on socket close and re-subscribes', () => {
    jest.useFakeTimers();
    const s = svc.open('m-1', { reconnectMs: 500 });
    expect(s.connection()).toBe('open');
    source.channels[0].subject.complete(); // Socket schließt
    expect(s.connection()).toBe('reconnecting');
    jest.advanceTimersByTime(500);
    expect(source.channels).toHaveLength(2);
    expect(source.channels[1].sent[0]).toEqual({ type: 'subscribe' });
    expect(s.connection()).toBe('open');
    jest.useRealTimers();
  });

  it('does not reconnect after an explicit close', () => {
    jest.useFakeTimers();
    const s = svc.open('m-1', { reconnectMs: 500 });
    s.close();
    expect(source.channels[0].closed).toBe(true);
    expect(s.connection()).toBe('closed');
    jest.advanceTimersByTime(2000);
    expect(source.channels).toHaveLength(1); // kein Reconnect
    jest.useRealTimers();
  });
});
