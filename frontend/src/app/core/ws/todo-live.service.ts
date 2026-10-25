import { Injectable, inject, signal } from '@angular/core';
import { Observable, Subject, type OperatorFunction } from 'rxjs';
import type { TodoPing, TodoServerMessage } from './ws-messages';
import { WsService, type TodoChannel } from './ws.service';

/** The server takes at most this many boards per socket; the rest go without pings. */
export const TODO_LIVE_MAX_BOARDS = 100;
/** Pings of one card within this time are read once (a burst of writes). */
export const PING_COALESCE_MS = 300;
/** The waits before the next connect after a dropped socket. */
const BACKOFF_MS = [1000, 2000, 4000, 8000, 16000, 30000];
/** After this many failed connects in a row the socket stays down; the poll goes on. */
const MAX_ATTEMPTS = 10;
/** The close codes of a refused socket (no session, the connection cap): no reconnect. */
const REFUSED = new Set([4401, 4403]);

/**
 * Collect the pings of a short time and give them out at once: one entry per board ping and
 * per card of a board (the last kind wins), and no card ping of a board that has a board
 * ping in the same batch, because the board read covers the card.
 */
export function batchPings(ms = PING_COALESCE_MS): OperatorFunction<TodoPing, TodoPing[]> {
  return (source) =>
    new Observable<TodoPing[]>((sub) => {
      let pending = new Map<string, TodoPing>();
      let timer: ReturnType<typeof setTimeout> | null = null;
      const flush = () => {
        timer = null;
        const list = [...pending.values()];
        pending = new Map();
        const boards = new Set(list.filter((p) => p.type === 'board').map((p) => p.boardId));
        sub.next(list.filter((p) => p.type === 'board' || !boards.has(p.boardId)));
      };
      const inner = source.subscribe({
        next: (p) => {
          const key = p.type === 'board' ? `b:${p.boardId}` : `c:${p.boardId}:${p.cardId}`;
          pending.delete(key);
          pending.set(key, p);
          timer ??= setTimeout(flush, ms);
        },
        error: (err: unknown) => sub.error(err),
        complete: () => sub.complete(),
      });
      return () => {
        inner.unsubscribe();
        if (timer) clearTimeout(timer);
      };
    });
}

/**
 * The live channel of the to-do boards (`/api/ws/todos`): one socket for the whole app.
 *
 * `changes$(ids)` counts the boards of every subscriber. The socket opens with the first
 * board and closes with the last one; each change of the set sends `subscribe` with all
 * boards (the server keeps the readable ones), and a change that leaves the set as it was
 * sends nothing. Above `TODO_LIVE_MAX_BOARDS` the boards of the newest subscriber (the page
 * on screen) go first, so the cut drops the boards of older ones. A dropped socket connects
 * again with a growing wait and sends `subscribe` again; the first `subscribed` after that
 * reconnect gives every board a `board` ping, because a ping may have gone missing while the
 * socket was down. Another `subscribed` on the same socket (a page swapped its boards) gives
 * none. A refused socket (no session, too many sockets) does not connect again until every
 * board is gone; the pages keep their poll. `connected` is true while the server holds the
 * boards, so a page can poll less often.
 */
@Injectable({ providedIn: 'root' })
export class TodoLiveService {
  private readonly ws = inject(WsService);
  /** The board ids of every live subscriber, oldest first. */
  private readonly subscribers: (readonly string[])[] = [];
  private readonly pings = new Subject<TodoPing>();
  private channel: TodoChannel | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private queued = false;
  private attempts = 0;
  private refused = false;
  /** The socket dropped: the next `subscribed` pings every board once. */
  private resynced = false;
  /** The sorted ids of the last `subscribe` on this socket (null: nothing sent yet). */
  private lastSent: string | null = null;

  /** The socket is open and the server took the boards. */
  readonly connected = signal(false);

  /** The pings of `boardIds` while subscribed. */
  changes$(boardIds: readonly string[]): Observable<TodoPing> {
    return new Observable<TodoPing>((sub) => {
      const ids = new Set(boardIds);
      const entry: readonly string[] = [...ids];
      this.subscribers.push(entry);
      this.queueSync();
      const inner = this.pings.subscribe((p) => {
        if (ids.has(p.boardId)) sub.next(p);
      });
      return () => {
        inner.unsubscribe();
        this.subscribers.splice(this.subscribers.indexOf(entry), 1);
        this.queueSync();
      };
    });
  }

  /** Every subscribed board once, the boards of the newest subscriber first. */
  private boardIds(): string[] {
    const ids = new Set<string>();
    for (let i = this.subscribers.length - 1; i >= 0; i--) for (const id of this.subscribers[i]) ids.add(id);
    return [...ids];
  }

  /** One `subscribe` for all changes of the same task (a page swaps its boards at once). */
  private queueSync(): void {
    if (this.queued) return;
    this.queued = true;
    queueMicrotask(() => {
      this.queued = false;
      this.sync();
    });
  }

  private sync(): void {
    const ids = this.boardIds();
    if (!ids.length) {
      this.stop();
      return;
    }
    if (!this.channel) {
      if (!this.timer && !this.refused) this.connect();
      return;
    }
    const boardIds = ids.slice(0, TODO_LIVE_MAX_BOARDS);
    const key = [...boardIds].sort().join(',');
    if (key === this.lastSent) return;
    this.lastSent = key;
    this.channel.send({ type: 'subscribe', boardIds });
  }

  private connect(): void {
    const channel = this.ws.connectTodos();
    this.channel = channel;
    this.lastSent = null;
    channel.messages$.subscribe((m) => this.handle(channel, m));
    this.sync();
  }

  private handle(channel: TodoChannel, m: TodoServerMessage): void {
    if (channel !== this.channel) return;
    switch (m.type) {
      case 'subscribed':
        this.attempts = 0;
        this.connected.set(true);
        if (this.resynced) for (const boardId of m.boardIds) this.pings.next({ type: 'board', boardId });
        this.resynced = false;
        break;
      case 'closed':
        this.onClosed(m.code);
        break;
      case 'error':
        break;
      default:
        this.pings.next(m);
    }
  }

  private onClosed(code: number): void {
    this.channel = null;
    this.lastSent = null;
    this.connected.set(false);
    this.resynced = true;
    if (REFUSED.has(code)) {
      this.refused = true;
      return;
    }
    this.attempts += 1;
    if (this.attempts > MAX_ATTEMPTS) return;
    const delay = BACKOFF_MS[Math.min(this.attempts, BACKOFF_MS.length) - 1];
    this.timer = setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }

  /** The last board is gone: close the socket and start over at the next one. */
  private stop(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const channel = this.channel;
    this.channel = null;
    this.lastSent = null;
    this.connected.set(false);
    this.attempts = 0;
    this.refused = false;
    this.resynced = false;
    channel?.close();
  }
}
