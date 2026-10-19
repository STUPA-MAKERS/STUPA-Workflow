import { Injectable, inject } from '@angular/core';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type TodoAssignedBoard,
  type TodoBoard,
  type TodoCardDetail,
  type TodoCardTile,
  type TodoMember,
} from '@core/api/todos.service';
import { finalize } from 'rxjs';

/** The reads of the card details that run at once. */
const CARD_READS = 4;

type RowsSource = 'mine' | 'all';

/**
 * The to-do reads of the page, the ones it made and the ones it made ahead: every board
 * with its ETag and its people, the rows of "Alle" and "Meine To-Dos", and the detail of
 * every card. A board change or an opened card shows what is here at once, without a
 * skeleton, and reads it again behind it (a 304 keeps it).
 *
 * The page provides it, so it ends with the page and a later sign-in never sees the reads
 * of an earlier one. A detail is dropped when the tile of its board no longer matches it,
 * because the card changed since the detail was read.
 */
@Injectable()
export class TodoCacheService {
  private readonly api = inject(TodosApiService);
  private readonly boards = new Map<Uuid, { board: TodoBoard; etag: string | null }>();
  private readonly people = new Map<Uuid, TodoMember[]>();
  private readonly rowReads = new Map<RowsSource, { boards: TodoAssignedBoard[]; etag: string | null }>();
  private readonly cards = new Map<Uuid, TodoCardDetail>();
  /** The cards to read ahead, the next one first. */
  private queue: Uuid[] = [];
  private readonly reading = new Set<Uuid>();
  private started = false;

  board(id: Uuid): { board: TodoBoard; etag: string | null } | null {
    return this.boards.get(id) ?? null;
  }

  putBoard(board: TodoBoard, etag: string | null): void {
    this.boards.set(board.id, { board, etag });
    this.dropChanged(board.cards);
  }

  members(boardId: Uuid): TodoMember[] | null {
    return this.people.get(boardId) ?? null;
  }

  putMembers(boardId: Uuid, list: TodoMember[]): void {
    this.people.set(boardId, list);
  }

  rows(source: RowsSource): { boards: TodoAssignedBoard[]; etag: string | null } | null {
    return this.rowReads.get(source) ?? null;
  }

  putRows(source: RowsSource, boards: TodoAssignedBoard[], etag: string | null): void {
    this.rowReads.set(source, { boards, etag });
    for (const b of boards) this.dropChanged(b.cards);
  }

  card(id: Uuid): TodoCardDetail | null {
    return this.cards.get(id) ?? null;
  }

  putCard(card: TodoCardDetail): void {
    this.cards.set(card.id, card);
  }

  /**
   * Read ahead, once per page: every board of the list with its people, the rows of
   * "Alle" and "Meine To-Dos", then the detail of every card. `shown` is the board the
   * page reads itself, so it is not read twice; the page asks for its cards first.
   * A failed read leaves its entry out: the page reads it when it is shown.
   */
  prefetch(ids: readonly Uuid[], shown: Uuid | null): void {
    if (this.started) return;
    this.started = true;
    for (const id of ids) {
      if (id === shown) continue;
      if (!this.boards.has(id)) {
        this.api.pollBoard(id, null).subscribe({
          next: ({ board, etag }) => {
            if (!board || this.boards.has(id)) return;
            this.putBoard(board, etag);
            this.readCards(board.cards);
          },
          error: () => undefined,
        });
      }
      if (!this.people.has(id)) {
        this.api.members(id).subscribe({
          next: (list) => {
            if (!this.people.has(id)) this.putMembers(id, list);
          },
          error: () => undefined,
        });
      }
    }
    for (const source of ['all', 'mine'] as const) {
      if (this.rowReads.has(source)) continue;
      const read = source === 'all' ? this.api.pollAllBoards(null) : this.api.pollMineBoards(null);
      read.subscribe({
        next: ({ boards, etag }) => {
          if (boards && !this.rowReads.has(source)) this.putRows(source, boards, etag);
        },
        error: () => undefined,
      });
    }
  }

  /** Read the detail of these cards ahead; `soon` puts them before the rest. */
  readCards(tiles: readonly TodoCardTile[], soon = false): void {
    const ids = tiles.map((t) => t.id).filter((id) => !this.cards.has(id) && !this.reading.has(id));
    const rest = this.queue.filter((id) => !ids.includes(id));
    this.queue = soon ? [...ids, ...rest] : [...rest, ...ids];
    this.pump();
  }

  private pump(): void {
    while (this.reading.size < CARD_READS && this.queue.length) {
      const id = this.queue.shift() as Uuid;
      if (this.cards.has(id)) continue;
      this.reading.add(id);
      this.api
        .card(id)
        .pipe(finalize(() => this.done(id)))
        .subscribe({
          next: (card) => {
            if (!this.cards.has(id)) this.cards.set(id, card);
          },
          error: () => undefined,
        });
    }
  }

  private done(id: Uuid): void {
    this.reading.delete(id);
    this.pump();
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
