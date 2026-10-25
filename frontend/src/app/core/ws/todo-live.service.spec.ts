import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { TODO_LIVE_MAX_BOARDS, TodoLiveService, batchPings } from './todo-live.service';
import type { TodoPing, TodoServerMessage, TodoSubscribeMsg } from './ws-messages';
import { WsService, type TodoChannel } from './ws.service';

class FakeChannel implements TodoChannel {
  readonly frames = new Subject<TodoServerMessage>();
  readonly messages$ = this.frames.asObservable();
  sent: TodoSubscribeMsg[] = [];
  closed = false;
  send(msg: TodoSubscribeMsg): void {
    this.sent.push(msg);
  }
  close(): void {
    this.closed = true;
    this.frames.next({ type: 'closed', code: 1000 });
    this.frames.complete();
  }
}

const flush = () => Promise.resolve();

describe('TodoLiveService', () => {
  let live: TodoLiveService;
  let channels: FakeChannel[];

  beforeEach(() => {
    channels = [];
    const ws = {
      connectTodos: () => {
        const ch = new FakeChannel();
        channels.push(ch);
        return ch;
      },
    };
    live = TestBed.configureTestingModule({ providers: [{ provide: WsService, useValue: ws }] }).inject(TodoLiveService);
  });

  afterEach(() => jest.useRealTimers());

  /** The newest subscriber goes first. */
  it('opens one socket, counts the boards and closes with the last one', async () => {
    const a: TodoPing[] = [];
    const one = live.changes$(['b1', 'b2']).subscribe((p) => a.push(p));
    const two = live.changes$(['b2']).subscribe();
    await flush();
    expect(channels).toHaveLength(1);
    const ch = channels[0];
    expect(ch.sent).toEqual([{ type: 'subscribe', boardIds: ['b2', 'b1'] }]);
    ch.frames.next({ type: 'subscribed', boardIds: ['b1', 'b2'] });
    expect(live.connected()).toBe(true);
    ch.frames.next({ type: 'card', boardId: 'b1', cardId: 'c' });
    ch.frames.next({ type: 'board', boardId: 'x' });
    ch.frames.next({ type: 'error', code: 'rate_limited' });
    expect(a).toEqual([{ type: 'card', boardId: 'b1', cardId: 'c' }]);
    one.unsubscribe();
    await flush();
    expect(ch.sent.at(-1)).toEqual({ type: 'subscribe', boardIds: ['b2'] });
    two.unsubscribe();
    await flush();
    expect(ch.closed).toBe(true);
    expect(live.connected()).toBe(false);
  });

  it('sends at most the cap of boards, the boards of the current page first', async () => {
    const ids = Array.from({ length: TODO_LIVE_MAX_BOARDS + 5 }, (_, i) => `b${i}`);
    live.changes$(ids).subscribe();
    await flush();
    expect(channels[0].sent[0].boardIds).toHaveLength(TODO_LIVE_MAX_BOARDS);
    const page = live.changes$(['p1', 'b104']).subscribe();
    await flush();
    const sent = channels[0].sent.at(-1)!.boardIds;
    expect(sent).toHaveLength(TODO_LIVE_MAX_BOARDS);
    expect(sent.slice(0, 3)).toEqual(['p1', 'b104', 'b0']);
    expect(sent).not.toContain('b99');
    page.unsubscribe();
    await flush();
    expect(channels[0].sent.at(-1)!.boardIds).toEqual(ids.slice(0, TODO_LIVE_MAX_BOARDS));
  });

  /** A second view of the same boards opens, then the first one goes: the set never changes. */
  it('sends nothing when the set of boards stays the same', async () => {
    const first = live.changes$(['b1', 'b2']).subscribe();
    await flush();
    const ch = channels[0];
    expect(ch.sent).toHaveLength(1);
    const second = live.changes$(['b2', 'b1']).subscribe();
    await flush();
    first.unsubscribe();
    await flush();
    expect(ch.sent).toHaveLength(1);
    second.unsubscribe();
    await flush();
    expect(ch.closed).toBe(true);
  });

  it('a second subscribed on the same socket pings no board', async () => {
    const seen: TodoPing[] = [];
    live.changes$(['b1']).subscribe((p) => seen.push(p));
    await flush();
    const ch = channels[0];
    ch.frames.next({ type: 'subscribed', boardIds: ['b1'] });
    live.changes$(['b2']).subscribe((p) => seen.push(p));
    await flush();
    ch.frames.next({ type: 'subscribed', boardIds: ['b2', 'b1'] });
    expect(seen).toEqual([]);
  });

  /**
   * Only the first subscriber after the reconnect pings; a later one on the same socket does not. A
   * frame of the old socket is ignored.
   */
  it('connects again after a drop and pings every board then', async () => {
    jest.useFakeTimers({ doNotFake: ['queueMicrotask'] });
    const seen: TodoPing[] = [];
    live.changes$(['b1']).subscribe((p) => seen.push(p));
    await flush();
    channels[0].frames.next({ type: 'subscribed', boardIds: ['b1'] });
    channels[0].frames.next({ type: 'closed', code: 1006 });
    expect(live.connected()).toBe(false);
    jest.advanceTimersByTime(1000);
    expect(channels).toHaveLength(2);
    expect(channels[1].sent).toEqual([{ type: 'subscribe', boardIds: ['b1'] }]);
    channels[1].frames.next({ type: 'subscribed', boardIds: ['b1'] });
    expect(seen).toEqual([{ type: 'board', boardId: 'b1' }]);
    channels[1].frames.next({ type: 'subscribed', boardIds: ['b1'] });
    expect(seen).toHaveLength(1);
    channels[0].frames.next({ type: 'card', boardId: 'b1', cardId: 'c' });
    expect(seen).toHaveLength(1);
  });

  it('gives up after many failed connects and on a refused socket', async () => {
    jest.useFakeTimers({ doNotFake: ['queueMicrotask'] });
    live.changes$(['b1']).subscribe();
    await flush();
    for (let i = 0; i < 10; i++) {
      channels.at(-1)!.frames.next({ type: 'closed', code: 1006 });
      jest.advanceTimersByTime(30_000);
    }
    expect(channels).toHaveLength(11);
    channels.at(-1)!.frames.next({ type: 'closed', code: 1006 });
    jest.advanceTimersByTime(60_000);
    expect(channels).toHaveLength(11);
  });

  it('stays down after 4403 until every board is gone', async () => {
    const sub = live.changes$(['b1']).subscribe();
    await flush();
    channels[0].frames.next({ type: 'closed', code: 4403 });
    live.changes$(['b2']).subscribe();
    await flush();
    expect(channels).toHaveLength(1);
    sub.unsubscribe();
    await flush();
    expect(channels).toHaveLength(1);
  });

  it('a drop and then no board: the timer is gone and nothing connects', async () => {
    jest.useFakeTimers({ doNotFake: ['queueMicrotask'] });
    const sub = live.changes$(['b1']).subscribe();
    await flush();
    channels[0].frames.next({ type: 'closed', code: 1006 });
    sub.unsubscribe();
    await flush();
    jest.advanceTimersByTime(5000);
    expect(channels).toHaveLength(1);
    const again = live.changes$(['b1']).subscribe();
    await flush();
    expect(channels).toHaveLength(2);
    again.unsubscribe();
    await flush();
    channels[1].frames.next({ type: 'closed', code: 1006 });
    expect(channels).toHaveLength(2);
  });
});

describe('batchPings', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('reads each card once and lets a board ping cover its cards', () => {
    const src = new Subject<TodoPing>();
    const out: TodoPing[][] = [];
    const sub = src.pipe(batchPings(300)).subscribe((b) => out.push(b));
    src.next({ type: 'card', boardId: 'a', cardId: '1' });
    src.next({ type: 'card', boardId: 'a', cardId: '1' });
    src.next({ type: 'card_removed', boardId: 'b', cardId: '1' });
    src.next({ type: 'card', boardId: 'c', cardId: '2' });
    src.next({ type: 'board', boardId: 'c' });
    jest.advanceTimersByTime(300);
    expect(out).toEqual([
      [
        { type: 'card', boardId: 'a', cardId: '1' },
        { type: 'card_removed', boardId: 'b', cardId: '1' },
        { type: 'board', boardId: 'c' },
      ],
    ]);
    src.next({ type: 'board', boardId: 'a' });
    sub.unsubscribe();
    jest.advanceTimersByTime(300);
    expect(out).toHaveLength(1);
  });

  it('passes an error and the end through', () => {
    const src = new Subject<TodoPing>();
    const seen: string[] = [];
    src.pipe(batchPings()).subscribe({ complete: () => seen.push('done') });
    src.complete();
    const bad = new Subject<TodoPing>();
    bad.pipe(batchPings()).subscribe({ error: () => seen.push('error') });
    bad.error(new Error('x'));
    expect(seen).toEqual(['done', 'error']);
  });
});
