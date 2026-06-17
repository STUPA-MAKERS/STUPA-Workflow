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

  it('mirrors closing counts with default tally fields when no prior tally exists', () => {
    const s = svc.open('m-1');
    const ch = source.channels[0];
    // vote_closed arrives with NO preceding vote_tally → prev is null, fallbacks apply.
    ch.subject.next({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: { yes: 5 } });
    expect(s.result()?.result).toBe('passed');
    const t = s.tally();
    expect(t?.counts['yes']).toBe(5);
    expect(t?.eligible).toBe(0); // prev?.eligible ?? 0
    expect(t?.quorumMet).toBe(false); // prev?.quorumMet ?? false
    expect(t?.leading).toBeNull(); // prev?.leading ?? null
  });

  it('clears a pending reconnect timer on explicit close', () => {
    jest.useFakeTimers();
    const s = svc.open('m-1', { reconnectMs: 500 });
    // Enter the reconnecting state so a reconnect timer is armed …
    source.channels[0].subject.complete();
    expect(s.connection()).toBe('reconnecting');
    // … then close: the armed timer must be cleared (no reconnect fires).
    s.close();
    jest.advanceTimersByTime(5000);
    expect(source.channels).toHaveLength(1);
    expect(s.connection()).toBe('closed');
    jest.useRealTimers();
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

  it('clears the open vote (and tally/result) when its vote is cancelled', () => {
    const s = svc.open('m-1');
    const ch = source.channels[0];
    ch.subject.next({
      type: 'vote_opened',
      voteId: 'v1',
      applicationId: 'a1',
      options: ['yes', 'no'],
      closesAt: null,
    });
    ch.subject.next({
      type: 'vote_tally',
      voteId: 'v1',
      counts: { yes: 1 },
      eligible: 5,
      quorumMet: false,
      leading: 'yes',
    });
    ch.subject.next({ type: 'vote_cancelled', voteId: 'v1' });
    expect(s.openVote()).toBeNull();
    expect(s.tally()).toBeNull();
    expect(s.result()).toBeNull();
  });

  it('ignores a cancellation for a different vote than the open one', () => {
    const s = svc.open('m-1');
    const ch = source.channels[0];
    ch.subject.next({
      type: 'vote_opened',
      voteId: 'v1',
      applicationId: 'a1',
      options: ['yes', 'no'],
      closesAt: null,
    });
    // Cancellation references an unrelated vote → the open vote survives.
    ch.subject.next({ type: 'vote_cancelled', voteId: 'other' });
    expect(s.openVote()?.voteId).toBe('v1');
  });

  it('ignores a cancellation when no vote is currently open', () => {
    const s = svc.open('m-1');
    source.channels[0].subject.next({ type: 'vote_cancelled', voteId: 'v1' });
    expect(s.openVote()).toBeNull();
  });

  it('reconnects after an errored stream (not just a clean complete)', () => {
    jest.useFakeTimers();
    const s = svc.open('m-1', { reconnectMs: 500 });
    source.channels[0].subject.error(new Error('socket died'));
    expect(s.connection()).toBe('reconnecting');
    jest.advanceTimersByTime(500);
    expect(source.channels).toHaveLength(2);
    jest.useRealTimers();
  });

  it('gives up after the max reconnect attempts and reports connection_failed', () => {
    jest.useFakeTimers();
    const s = svc.open('m-1', { reconnectMs: 500 });
    // Each connect immediately completes → counts as a failed attempt. The first
    // open used channel 0; attempts 1..4 keep reconnecting, the 5th gives up.
    for (let i = 0; i < 5; i++) {
      source.channels[source.channels.length - 1].subject.complete();
      jest.advanceTimersByTime(15000);
    }
    expect(s.connection()).toBe('closed');
    expect(s.errorCode()).toBe('connection_failed');
    jest.useRealTimers();
  });

  it('resets the attempt counter once a frame is received again', () => {
    jest.useFakeTimers();
    const s = svc.open('m-1', { reconnectMs: 100 });
    // Two failed attempts.
    source.channels[0].subject.complete();
    jest.advanceTimersByTime(100);
    source.channels[1].subject.complete();
    jest.advanceTimersByTime(200);
    // A successful frame on the new channel resets attempts back to zero.
    source.channels[2].subject.next({ type: 'meeting_state', activeApplicationId: null, status: 'live' });
    // Now four more failures would be needed before giving up; one is harmless.
    source.channels[2].subject.complete();
    jest.advanceTimersByTime(100);
    expect(s.connection()).toBe('open');
    jest.useRealTimers();
  });

  it('open() honours explicit reconnectMs and beamer defaults', () => {
    const s = svc.open('m-2');
    expect(source.lastBeamer).toBe(false);
    expect(s.connection()).toBe('open');
  });

  it('does not reconnect when the stream ends after the user closed it', () => {
    jest.useFakeTimers();
    const s = svc.open('m-1', { reconnectMs: 500 });
    s.close();
    // A late complete from the already-closed socket must stay 'closed', no reconnect.
    source.channels[0].subject.complete();
    expect(s.connection()).toBe('closed');
    jest.advanceTimersByTime(5000);
    expect(source.channels).toHaveLength(1);
    jest.useRealTimers();
  });
});
