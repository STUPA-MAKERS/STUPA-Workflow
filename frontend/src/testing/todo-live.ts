import { signal } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { TodoLiveService } from '@core/ws/todo-live.service';
import type { TodoPing } from '@core/ws/ws-messages';

/**
 * A `TodoLiveService` without a socket: jsdom opens no WebSocket, and a spec sends pings
 * with `emit` and reads the subscribed boards in `boards()`.
 */
export class FakeTodoLive {
  readonly connected = signal(false);
  private readonly pings = new Subject<TodoPing>();
  /** The board sets of the open subscriptions. */
  readonly open: string[][] = [];

  changes$(boardIds: readonly string[]): Observable<TodoPing> {
    return new Observable<TodoPing>((sub) => {
      const ids = [...boardIds];
      this.open.push(ids);
      const inner = this.pings.subscribe((p) => {
        if (ids.includes(p.boardId)) sub.next(p);
      });
      return () => {
        inner.unsubscribe();
        this.open.splice(this.open.indexOf(ids), 1);
      };
    });
  }

  /** Every board of an open subscription. */
  boards(): string[] {
    return [...new Set(this.open.flat())].sort();
  }

  emit(ping: TodoPing): void {
    this.pings.next(ping);
  }
}

/** The provider of a fresh fake; the spec reads it back with `TestBed.inject(TodoLiveService)`. */
export function provideFakeTodoLive() {
  return { provide: TodoLiveService, useFactory: () => new FakeTodoLive() };
}
