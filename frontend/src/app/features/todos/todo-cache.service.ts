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
import { withEntry } from '@shared/util/immutable';

/**
 * The read-ahead requests that run at once. The API serves one request after the other,
 * so a read of the page itself never waits behind more than these.
 */
const READS = 2;

type RowsSource = 'mine' | 'all';
type Read = () => Observable<unknown>;

/** A board read with its ETag. */
interface HeldBoard {
  readonly board: TodoBoard;
  readonly etag: string | null;
}

/** The rows of "Alle" or "Meine To-Dos" with their ETag. */
interface HeldRows {
  readonly boards: readonly TodoAssignedBoard[];
  readonly etag: string | null;
}

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
  private boards: ReadonlyMap<Uuid, HeldBoard> = new Map();
  private people: ReadonlyMap<Uuid, readonly TodoMember[]> = new Map();
  private rowReads: ReadonlyMap<RowsSource, HeldRows> = new Map();
  private cards: ReadonlyMap<Uuid, TodoCardDetail> = new Map();
  /** The cards to read ahead: the shown board's (`soon`) before the rest (`later`). */
  private soon: readonly Uuid[] = [];
  private later: readonly Uuid[] = [];
  /** The reads of the boards, their people and the rows, in order. */
  private tasks: readonly Read[] = [];
  private reading: ReadonlySet<Uuid> = new Set();
  private running = 0;
  private started = false;

  /** Stop the read-ahead of the page that closes; what was read stays. */
  leave(): void {
    this.started = false;
    this.tasks = [];
    this.soon = [];
    this.later = [];
  }

  board(id: Uuid): HeldBoard | null {
    this.own();
    return this.boards.get(id) ?? null;
  }

  putBoard(board: TodoBoard, etag: string | null): void {
    this.own();
    this.boards = withEntry(this.boards, board.id, { board, etag });
    this.dropChanged(board.cards);
  }

  members(boardId: Uuid): readonly TodoMember[] | null {
    this.own();
    return this.people.get(boardId) ?? null;
  }

  putMembers(boardId: Uuid, list: readonly TodoMember[]): void {
    this.own();
    this.people = withEntry(this.people, boardId, list);
  }

  rows(source: RowsSource): HeldRows | null {
    this.own();
    return this.rowReads.get(source) ?? null;
  }

  putRows(source: RowsSource, boards: readonly TodoAssignedBoard[], etag: string | null): void {
    this.own();
    this.rowReads = withEntry(this.rowReads, source, { boards, etag });
    this.dropChanged(boards.flatMap((b) => b.cards));
  }

  card(id: Uuid): TodoCardDetail | null {
    this.own();
    return this.cards.get(id) ?? null;
  }

  putCard(card: TodoCardDetail): void {
    this.own();
    this.cards = withEntry(this.cards, card.id, card);
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
    const boardTasks = ids
      .filter((id) => id !== shown)
      .flatMap((id) => [
        ...(this.boards.has(id) ? [] : [this.boardRead(id)]),
        ...(this.people.has(id) ? [] : [this.membersRead(id)]),
      ]);
    const rowTasks = (['all', 'mine'] as const).map((source) => this.rowsRead(source));
    this.tasks = [...this.tasks, ...boardTasks, ...rowTasks];
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
    const waiting = this.soon.filter((id) => !fresh.has(id));
    const rest = this.later.filter((id) => !fresh.has(id));
    this.soon = soon ? [...ids, ...waiting] : waiting;
    this.later = soon ? rest : [...rest, ...ids];
    this.pump();
  }

  /** The read of a board ahead; a board the page read meanwhile wins. */
  private boardRead(id: Uuid): Read {
    return () =>
      this.api.pollBoard(id, null).pipe(
        tap(({ board, etag }) => {
          if (!board || this.boards.has(id)) return;
          this.putBoard(board, etag);
          this.readCards(board.cards);
        }),
      );
  }

  /** The read of the people of a board ahead; people the page read meanwhile win. */
  private membersRead(id: Uuid): Read {
    return () =>
      this.api.members(id).pipe(
        tap((list) => {
          if (!this.people.has(id)) this.putMembers(id, list);
        }),
      );
  }

  /** The read of the rows ahead; nothing when the rows are held when the read starts. */
  private rowsRead(source: RowsSource): Read {
    return () => {
      if (this.rowReads.has(source)) return EMPTY;
      const read = source === 'all' ? this.api.pollAllBoards(null) : this.api.pollMineBoards(null);
      return read.pipe(
        tap(({ boards, etag }) => {
          if (boards && !this.rowReads.has(source)) this.putRows(source, [...boards], etag);
        }),
      );
    };
  }

  /** Forget the reads of another person: the one signed in changed. */
  private own(): void {
    const who = this.auth.userId();
    if (who === this.owner) return;
    this.owner = who;
    this.leave();
    this.boards = new Map();
    this.people = new Map();
    this.rowReads = new Map();
    this.cards = new Map();
    this.reading = new Set();
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
    const [task, ...rest] = this.tasks;
    this.tasks = rest;
    return task ?? this.batch('later');
  }

  /** One request for the next `CARD_BATCH` cards of a line that are not held or in flight. */
  private batch(line: 'soon' | 'later'): Read | null {
    const ids = this.take(line);
    if (!ids.length) return null;
    const batch = new Set(ids);
    this.reading = new Set([...this.reading, ...ids]);
    return () =>
      this.api.cards(ids).pipe(
        tap((list) => {
          const read = list.map((card) => [card.id, card] as const).reverse();
          this.cards = new Map([...read, ...this.cards]);
        }),
        finalize(() => {
          this.reading = new Set([...this.reading].filter((id) => !batch.has(id)));
        }),
      );
  }

  /**
   * Take the next `CARD_BATCH` cards of a line that are not held or in flight; the chunks
   * that hold none are dropped on the way, and an empty line gives none.
   */
  private take(line: 'soon' | 'later'): readonly Uuid[] {
    const queue = this[line];
    if (!queue.length) return [];
    const fresh = (id: Uuid): boolean => !this.cards.has(id) && !this.reading.has(id);
    const ids = queue.slice(0, CARD_BATCH).filter(fresh);
    this[line] = queue.slice(CARD_BATCH);
    return ids.length ? ids : this.take(line);
  }

  /** Drop every detail that no longer matches its tile. */
  private dropChanged(tiles: readonly TodoCardTile[]): void {
    const stale = new Set(
      tiles
        .filter((tile) => {
          const card = this.cards.get(tile.id);
          return card !== undefined && !sameTile(card, tile);
        })
        .map((tile) => tile.id),
    );
    if (stale.size) this.cards = new Map([...this.cards].filter(([id]) => !stale.has(id)));
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
