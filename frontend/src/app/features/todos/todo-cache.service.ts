import { Injectable, inject } from '@angular/core';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import {
  CARD_BATCH,
  TodosApiService,
  type TodoAssignedBoard,
  type TodoBoard,
  type TodoCardDetail,
  type TodoCardTile,
  type TodoMember,
} from '@core/api/todos.service';
import { EMPTY, finalize, tap, type Observable } from 'rxjs';

/**
 * The read-ahead requests that run at once. The API serves one request after the other,
 * so a read of the page itself never waits behind more than these.
 */
const READS = 2;

type RowsSource = 'mine' | 'all';
type Read = () => Observable<unknown>;

/**
 * The to-do reads of the page, the ones it made and the ones it made ahead: every board
 * with its ETag and its people, the rows of "Alle" and "Meine To-Dos", and the detail of
 * every card. A board change or an opened card shows what is here at once, without a
 * skeleton, and reads it again behind it (a 304 keeps it).
 *
 * The read-ahead starts when the page calls `prefetch`, after its shown board answered,
 * and runs at most `READS` requests at once: the details of the shown board first, then
 * the other boards with their people and the rows, then the details of the other boards.
 * The details come `CARD_BATCH` cards per request (`GET /todos/cards?ids=`).
 *
 * It lives as long as the app, so a return to the page shows the boards at once and reads
 * them again behind them. It forgets everything when another person signs in (or nobody
 * is), so a later sign-in never sees the reads of an earlier one. `leave` drops the reads
 * still waiting when the page closes; the next visit starts them again for what is not
 * held. A detail is dropped when the tile of its board no longer matches it, because the
 * card changed since the detail was read.
 */
@Injectable({ providedIn: 'root' })
export class TodoCacheService {
  private readonly api = inject(TodosApiService);
  private readonly auth = inject(AuthService);
  /** The person whose reads these are. */
  private owner: string | null = null;
  private readonly boards = new Map<Uuid, { board: TodoBoard; etag: string | null }>();
  private readonly people = new Map<Uuid, TodoMember[]>();
  private readonly rowReads = new Map<RowsSource, { boards: TodoAssignedBoard[]; etag: string | null }>();
  private readonly cards = new Map<Uuid, TodoCardDetail>();
  /** The cards to read ahead: the shown board's (`soon`) before the rest (`later`). */
  private soon: Uuid[] = [];
  private later: Uuid[] = [];
  /** The reads of the boards, their people and the rows, in order. */
  private readonly tasks: Read[] = [];
  private readonly reading = new Set<Uuid>();
  private running = 0;
  private started = false;

  /** Stop the read-ahead of the page that closes; what was read stays. */
  leave(): void {
    this.started = false;
    this.tasks.length = 0;
    this.soon = [];
    this.later = [];
  }

  board(id: Uuid): { board: TodoBoard; etag: string | null } | null {
    this.own();
    return this.boards.get(id) ?? null;
  }

  putBoard(board: TodoBoard, etag: string | null): void {
    this.own();
    this.boards.set(board.id, { board, etag });
    this.dropChanged(board.cards);
  }

  members(boardId: Uuid): TodoMember[] | null {
    this.own();
    return this.people.get(boardId) ?? null;
  }

  putMembers(boardId: Uuid, list: TodoMember[]): void {
    this.own();
    this.people.set(boardId, list);
  }

  rows(source: RowsSource): { boards: TodoAssignedBoard[]; etag: string | null } | null {
    this.own();
    return this.rowReads.get(source) ?? null;
  }

  putRows(source: RowsSource, boards: TodoAssignedBoard[], etag: string | null): void {
    this.own();
    this.rowReads.set(source, { boards, etag });
    for (const b of boards) this.dropChanged(b.cards);
  }

  card(id: Uuid): TodoCardDetail | null {
    this.own();
    return this.cards.get(id) ?? null;
  }

  putCard(card: TodoCardDetail): void {
    this.own();
    this.cards.set(card.id, card);
  }

  /**
   * Start the read-ahead, once per page: every board of the list with its people, the
   * rows of "Alle" and "Meine To-Dos", then the detail of every card. `shown` is the board
   * the page reads itself, so it is not read twice. A failed read leaves its entry out:
   * the page reads it when it is shown.
   */
  prefetch(ids: readonly Uuid[], shown: Uuid | null): void {
    this.own();
    if (this.started) return;
    this.started = true;
    for (const id of ids) {
      if (id === shown) continue;
      if (!this.boards.has(id)) {
        this.tasks.push(() =>
          this.api.pollBoard(id, null).pipe(
            tap(({ board, etag }) => {
              if (!board || this.boards.has(id)) return;
              this.putBoard(board, etag);
              this.readCards(board.cards);
            }),
          ),
        );
      }
      if (!this.people.has(id)) {
        this.tasks.push(() =>
          this.api.members(id).pipe(
            tap((list) => {
              if (!this.people.has(id)) this.putMembers(id, list);
            }),
          ),
        );
      }
    }
    for (const source of ['all', 'mine'] as const) {
      this.tasks.push(() => {
        if (this.rowReads.has(source)) return EMPTY;
        const read = source === 'all' ? this.api.pollAllBoards(null) : this.api.pollMineBoards(null);
        return read.pipe(
          tap(({ boards, etag }) => {
            if (boards && !this.rowReads.has(source)) this.putRows(source, boards, etag);
          }),
        );
      });
    }
    this.pump();
  }

  /**
   * Read the detail of these cards ahead; `soon` puts them before the rest. Before
   * `prefetch` they only wait in line.
   */
  readCards(tiles: readonly TodoCardTile[], soon = false): void {
    this.own();
    const ids = tiles.map((t) => t.id).filter((id) => !this.cards.has(id) && !this.reading.has(id));
    const fresh = new Set(ids);
    this.soon = this.soon.filter((id) => !fresh.has(id));
    this.later = this.later.filter((id) => !fresh.has(id));
    if (soon) this.soon = [...ids, ...this.soon];
    else this.later.push(...ids);
    this.pump();
  }

  /** Forget the reads of another person: the one signed in changed. */
  private own(): void {
    const who = this.auth.userId();
    if (who === this.owner) return;
    this.owner = who;
    this.leave();
    this.boards.clear();
    this.people.clear();
    this.rowReads.clear();
    this.cards.clear();
    this.reading.clear();
  }

  private pump(): void {
    if (!this.started) return;
    while (this.running < READS) {
      const read = this.next();
      if (!read) return;
      this.running++;
      read()
        .pipe(finalize(() => this.done()))
        .subscribe({ error: () => undefined });
    }
  }

  private done(): void {
    this.running--;
    this.pump();
  }

  /** The next read: the cards of the shown board, the boards and rows, the other cards. */
  private next(): Read | null {
    const soon = this.batch('soon');
    if (soon) return soon;
    const task = this.tasks.shift();
    if (task) return task;
    return this.batch('later');
  }

  /** One request for the next `CARD_BATCH` cards of a line that are not held or in flight. */
  private batch(line: 'soon' | 'later'): Read | null {
    let ids: Uuid[] = [];
    while (!ids.length && this[line].length) {
      ids = this[line].splice(0, CARD_BATCH).filter((id) => !this.cards.has(id) && !this.reading.has(id));
    }
    if (!ids.length) return null;
    for (const id of ids) this.reading.add(id);
    return () =>
      this.api.cards(ids).pipe(
        tap((list) => {
          for (const card of list) if (!this.cards.has(card.id)) this.cards.set(card.id, card);
        }),
        finalize(() => {
          for (const id of ids) this.reading.delete(id);
        }),
      );
  }

  /** Drop every detail that no longer matches its tile. */
  private dropChanged(tiles: readonly TodoCardTile[]): void {
    for (const tile of tiles) {
      const card = this.cards.get(tile.id);
      if (card && !sameTile(card, tile)) this.cards.delete(tile.id);
    }
  }
}

function sameTile(card: TodoCardDetail, tile: TodoCardTile): boolean {
  return (
    card.version === tile.version &&
    card.updatedAt === tile.updatedAt &&
    card.boardId === tile.boardId &&
    card.columnId === tile.columnId &&
    card.commentCount === tile.commentCount &&
    card.linkCount === tile.linkCount &&
    card.checklist.done === tile.checklist.done &&
    card.checklist.total === tile.checklist.total
  );
}
