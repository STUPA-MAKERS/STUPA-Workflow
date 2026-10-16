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
 * boards (the server keeps the readable ones). A dropped socket connects again with a
 * growing wait and sends `subscribe` again; after that reconnect every board gets a
 * `board` ping, because a ping may have gone missing in between. A refused socket (no
 * session, too many sockets) does not connect again until every board is gone; the
 * pages keep their poll. `connected` is true while the server holds the boards, so a
 * page can poll less often.
 */
@Injectable({ providedIn: 'root' })
export class TodoLiveService {
  private readonly ws = inject(WsService);
  private readonly counts = new Map<string, number>();
  private readonly pings = new Subject<TodoPing>();
  private channel: TodoChannel | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private queued = false;
  private attempts = 0;
  private refused = false;
  /** The socket had the boards once, so the next `subscribed` follows a reconnect. */
  private wasLive = false;

  /** The socket is open and the server took the boards. */
  readonly connected = signal(false);

  /** The pings of `boardIds` while subscribed. */
  changes$(boardIds: readonly string[]): Observable<TodoPing> {
    return new Observable<TodoPing>((sub) => {
      const ids = new Set(boardIds);
      for (const id of ids) this.counts.set(id, (this.counts.get(id) ?? 0) + 1);
      this.queueSync();
      const inner = this.pings.subscribe((p) => {
        if (ids.has(p.boardId)) sub.next(p);
      });
      return () => {
        inner.unsubscribe();
        for (const id of ids) {
          const n = (this.counts.get(id) as number) - 1;
          if (n > 0) this.counts.set(id, n);
          else this.counts.delete(id);
        }
        this.queueSync();
      };
    });
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
    if (!this.counts.size) {
      this.stop();
      return;
    }
    if (!this.channel) {
      if (!this.timer && !this.refused) this.connect();
      return;
    }
    this.channel.send({ type: 'subscribe', boardIds: [...this.counts.keys()].slice(0, TODO_LIVE_MAX_BOARDS) });
  }

  private connect(): void {
    const channel = this.ws.connectTodos();
    this.channel = channel;
    channel.messages$.subscribe((m) => this.handle(channel, m));
    this.sync();
  }

  private handle(channel: TodoChannel, m: TodoServerMessage): void {
    if (channel !== this.channel) return;
    switch (m.type) {
      case 'subscribed':
        this.attempts = 0;
        this.connected.set(true);
        if (this.wasLive) for (const boardId of m.boardIds) this.pings.next({ type: 'board', boardId });
        this.wasLive = true;
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
    // A socket that `stop` closed is no longer `channel`, so boards are always there.
    this.channel = null;
    this.connected.set(false);
    if (REFUSED.has(code)) {
      this.refused = true;
      return;
    }
    this.attempts += 1;
    if (this.attempts > MAX_ATTEMPTS) return;
    const delay = BACKOFF_MS[Math.min(this.attempts, BACKOFF_MS.length) - 1];
    // `stop` clears the timer when the last board goes, so it always finds boards.
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
    this.connected.set(false);
    this.attempts = 0;
    this.refused = false;
    this.wasLive = false;
    channel?.close();
  }
}
