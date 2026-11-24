import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  type OnInit,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { Subject, finalize, merge } from 'rxjs';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type TodoAssignedBoard,
  type TodoCardDetail,
  type TodoCardMove,
  type TodoCardTile,
  type TodoLabel,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TodoLiveService, batchPings } from '@core/ws/todo-live.service';
import type { TodoPing } from '@core/ws/ws-messages';
import { ToastService } from '@stupa-makers/ui-kit';
import {
  TodoBoardRowsViewComponent,
  boardRows,
  type BoardFilter,
  type RowDrop,
  type RowLead,
  type TileMenuRequest,
} from '@stupa-makers/ui-kit/views/board';
import { TodoCacheService } from '../../../features/todos/todo-cache.service';
import {
  applyMove,
  insertTile,
  moveErrorText,
  placeTile,
  removeTile,
  replaceTile,
  sheetMove,
} from '../../../features/todos/todos.util';

export {
  COLLAPSED_KEY,
  boardRows,
  rowDropId,
  type BoardRow,
  type RowDrop,
  type RowLead,
  type RowOptions,
} from '@stupa-makers/ui-kit/views/board';

/**
 * The board rows, the app part around the kit view `app-todo-board-rows-view`
 * (S/framework/views/002271). `source="mine"`: the rows under "Meine To-Dos", one row per
 * other board that holds cards assigned to me (`GET /todos/mine/boards`), with only my
 * cards. `source="all"`: the meta-board "Alle", one row per readable board with all its
 * cards (`GET /todos/all/boards`).
 *
 * The view shows the rows and the drags. A drop on the same board moves the card
 * (`moveCard`), a drop on another row transfers it (`transferCard`, with the neighbors of
 * the drop place), both at once and back with a toast when the server refuses. A card from
 * `extraDrops` comes out as `dropIn` for the page. On the phone the page moves a card
 * through its sheet (`moveTo`).
 *
 * The page calls `poll()` with its own poll (ETag, 304 keeps the rows), and the
 * `card…` methods after a change in the card drawer.
 *
 * Live: the rows take the pings of their boards and of `liveIds` (`TodoLiveService`). A
 * `card` ping reads that tile and puts it in its row; under "Meine To-Dos" only a tile
 * assigned to `me` stays, so a tile without me leaves and a new one with me joins. A tile
 * of a board without a row, or an unknown `me`, reads the rows again. `card_removed` takes
 * the tile out, a 404 of the tile read too, and `board` is the ETag read of the rows.
 * While a card is held (here or, through `hold`, on the board above) or a move is in
 * flight, the pings wait.
 */
@Component({
  selector: 'app-todo-board-rows',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TodoBoardRowsViewComponent],
  host: { class: 'br-adapter' },
  templateUrl: './todo-board-rows.component.html',
  styleUrl: './todo-board-rows.component.scss',
})
export class TodoBoardRowsComponent implements OnInit {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly live = inject(TodoLiveService);
  /** The reads of the page, the ones made ahead too; absent outside the page. */
  private readonly cache = inject(TodoCacheService, { optional: true });

  readonly filter = input.required<BoardFilter>();
  readonly today = input.required<string>();
  readonly phone = input(false);
  /** `mine`: the rows under "Meine To-Dos"; `all`: the meta-board "Alle". */
  readonly source = input<'mine' | 'all'>('mine');
  /**
   * My principal id: "Alle" needs it for "Zuständig: Ich", "Meine To-Dos" for the live
   * changes (a card without me leaves the rows).
   */
  readonly me = input<Uuid | null>(null);
  /** The labels of the page's label filter by id (see `RowOptions.filterLabels`). */
  readonly filterLabels = input<ReadonlyMap<Uuid, TodoLabel> | undefined>(undefined);
  /** The drop lists of the personal board above the rows, which a pointer drag reaches too. */
  readonly extraDrops = input<string[]>([]);
  /** More boards whose pings the rows take: a card of mine (or of "Alle") can appear there. */
  readonly liveIds = input<readonly Uuid[]>([]);
  /** The page holds a card or waits for a write: the pings wait too. */
  readonly hold = input(false);
  /**
   * Phone, "Meine To-Dos": the personal board as the first section of the list. Its head
   * has no link to the board, because the page shows that board.
   */
  readonly lead = input<RowLead | null>(null);

  readonly openCard = output<Uuid>();
  /** Phone: a long press on a tile of a writable row asks for the "Verschieben" sheet. */
  readonly menu = output<TileMenuRequest>();
  /** A card of `extraDrops` landed in a row: the page transfers it. */
  readonly dropIn = output<RowDrop>();
  /** A drag moved a card to another row: the server answer. */
  readonly transferred = output<TodoCardDetail>();
  /**
   * The drop lists of the writable open rows (`dropIds`), each time they change: the page
   * hands them to the personal board above, so a card of the board reaches the rows.
   */
  readonly drops = output<string[]>();
  /**
   * The number of cards the rows show after the filters. It reports first when the first
   * read answered (or failed), so the page knows whether rows follow under the board.
   */
  readonly matches = output<number>();

  readonly boards = signal<readonly TodoAssignedBoard[]>([]);
  /** The view of the rows: the drag state of the kit view. */
  readonly view = viewChild(TodoBoardRowsViewComponent);
  /** A card of the rows is held, by pointer or keyboard. */
  readonly dragging = computed(() => !!this.view()?.dragging());
  /** The link of a board in a row head. */
  readonly boardLink = (id: Uuid): string => `/todos/${id}`;
  private etag: string | null = null;
  /** Counts every change of the rows, live tiles too: a poll that left before one is dropped. */
  private mutations = 0;
  /**
   * Counts my own writes and the cards taken off: a tile read that left before one is
   * dropped. A live tile does not count, else a burst of k pings reads ~k² tiles.
   */
  private localWrites = 0;
  private seq = 0;
  /** The first read answered or failed. */
  private readonly ready = signal(false);
  /** Moves and transfers of the rows in flight. */
  private pending = 0;
  /** Pings that came while a card was held go round once more. */
  private readonly liveRetry = new Subject<TodoPing>();
  /** The boards of the pings: every row and `liveIds`, sorted, so an equal set is no change. */
  private readonly liveSet = computed(
    () => [...new Set([...this.boards().map((b) => b.id), ...this.liveIds()])].sort(),
    { equal: (a, b) => a.join() === b.join() },
  );

  readonly rows = computed(() =>
    boardRows(this.boards(), this.filter(), this.today(), {
      all: this.source() === 'all',
      me: this.me(),
      filterLabels: this.filterLabels(),
    }),
  );
  /** The open cards of every board (the search placeholder of "Alle"). */
  readonly openCount = computed(() =>
    this.boards().reduce((n, b) => {
      const done = new Set(b.columns.filter((c) => c.isDone).map((c) => c.id));
      return n + b.cards.filter((c) => !done.has(c.columnId)).length;
    }, 0),
  );
  constructor() {
    effect(() => {
      const rows = this.rows();
      if (this.ready()) this.matches.emit(rows.reduce((n, r) => n + r.count, 0));
    });
    effect(() => {
      const boards = this.boards();
      if (untracked(this.ready)) {
        untracked(() => this.cache?.putRows(this.source(), [...boards], this.etag));
      }
    });
    effect((onCleanup) => {
      const ids = this.liveSet();
      if (!ids.length) return;
      const sub = untracked(() =>
        merge(this.live.changes$(ids), this.liveRetry)
          .pipe(batchPings())
          .subscribe((pings) => this.onPings(pings)),
      );
      onCleanup(() => sub.unsubscribe());
    });
  }

  ngOnInit(): void {
    const held = this.cache?.rows(this.source());
    if (held) {
      this.boards.set(held.boards);
      this.etag = held.etag;
      this.ready.set(true);
    }
    this.load(held?.etag ?? null);
  }

  private load(etag: string | null): void {
    const seq = ++this.seq;
    const muts = this.mutations;
    const read = this.source() === 'all' ? this.api.pollAllBoards(etag) : this.api.pollMineBoards(etag);
    read.subscribe({
      next: (res) => {
        if (seq !== this.seq || muts !== this.mutations || !res.boards) return;
        this.boards.set(res.boards);
        this.etag = res.etag;
        this.ready.set(true);
      },
      error: () => this.ready.set(true),
    });
  }

  /** Read the rows again; a 304 keeps them. */
  poll(): void {
    this.load(this.etag);
  }

  /** Read the rows again without an ETag (after a change elsewhere or a refused move). */
  refresh(): void {
    this.mutations++;
    this.localWrites++;
    this.load(null);
  }

  /**
   * The card drawer changed a card: take it out of the rows of other boards (it moved to
   * another board), put it in its row, then read the rows again.
   */
  cardChanged(card: TodoCardDetail): void {
    this.localWrites++;
    const list = this.boards();
    const left = list.some((b) => b.id !== card.boardId && b.cards.some((c) => c.id === card.id));
    if (left) {
      this.mutations++;
      this.boards.set(list.map((b) => (b.id !== card.boardId ? removeTile(b, card.id) : b)));
    }
    const placed = this.update(card.boardId, (b) => (card.archivedAt ? removeTile(b, card.id) : placeTile(b, card)));
    if (!placed && !left) return;
    this.refresh();
  }

  /** The card drawer archived a card. */
  cardRemoved(id: Uuid): void {
    this.localWrites++;
    const board = this.boards().find((b) => b.cards.some((c) => c.id === id));
    if (!board) return;
    this.update(board.id, (b) => removeTile(b, id));
    this.refresh();
  }

  /** Merge only the comment count: the drawer's copy of the rest can be stale. */
  commentsChanged(event: { id: Uuid; commentCount: number }): void {
    this.localWrites++;
    const board = this.boards().find((b) => b.cards.some((c) => c.id === event.id));
    if (!board) return;
    this.update(board.id, (b) => ({
      ...b,
      cards: b.cards.map((c) => (c.id === event.id ? { ...c, commentCount: event.commentCount } : c)),
    }));
  }

  /** A card of another board lands in a row at once, before the server answers (`dropIn`). */
  receive(tile: TodoCardTile, boardId: Uuid, move: TodoCardMove): void {
    this.localWrites++;
    this.update(boardId, (b) => insertTile(b, tile, move));
  }

  /**
   * The server answer of a transfer into a row replaces the tile. Under "Meine To-Dos" a
   * card that is not assigned to me leaves the rows: they show only my cards. Such a card
   * gets a success toast with its new board, so it does not vanish without a word.
   *
   * Returns:
   *   True when the rows still show the card.
   */
  accept(card: TodoCardDetail): boolean {
    this.localWrites++;
    if (!this.keeps(card)) {
      this.removeCard(card.id);
      this.toast.show(
        this.i18n.translate('todos.card.transferred', { board: card.boardName }),
        'success',
      );
      return false;
    }
    this.update(card.boardId, (b) => replaceTile(b, card));
    return true;
  }

  /** Move a card of a row to the end of a column of its board (the sheet of the phone). */
  moveTo(cardId: Uuid, columnId: Uuid, position: 'top' | 'bottom' = 'bottom'): void {
    const board = this.boards().find((b) => b.cards.some((c) => c.id === cardId));
    if (board) this.move(board.id, cardId, sheetMove(board.cards, cardId, columnId, position));
  }

  /** Take a card out of its row (it went onto the personal board); null when no row holds it. */
  take(cardId: Uuid): TodoCardTile | null {
    this.localWrites++;
    const board = this.boards().find((b) => b.cards.some((c) => c.id === cardId));
    const card = board?.cards.find((c) => c.id === cardId) ?? null;
    if (board) this.update(board.id, (x) => removeTile(x, cardId));
    return card;
  }

  /** A card is held or a write is in flight: a live change waits. */
  private busy(): boolean {
    return this.dragging() || this.hold() || this.pending > 0;
  }

  private onPings(pings: readonly TodoPing[]): void {
    if (this.busy()) {
      for (const p of pings) this.liveRetry.next(p);
      return;
    }
    for (const p of pings) {
      if (p.type === 'card_removed') this.dropCard(p.cardId, p.boardId);
      else if (p.type === 'card') this.readTile(p);
    }
    if (pings.some((p) => p.type === 'board')) this.poll();
  }

  /**
   * Read the tile of a `card` ping and put it in place; a 404 takes it out of every row. A
   * write of mine or a card taken off while the read was out makes the answer stale: it is
   * dropped and the card is read again. Another live tile does not, because it changes
   * only its own card.
   */
  private readTile(ping: TodoPing & { type: 'card' }): void {
    const writes = this.localWrites;
    this.api.cardTile(ping.cardId).subscribe({
      next: (tile) => {
        if (this.busy() || writes !== this.localWrites) this.liveRetry.next(ping);
        else this.placeLive(tile);
      },
      error: (err: unknown) => {
        if (err instanceof HttpErrorResponse && err.status === 404) this.dropCard(ping.cardId);
      },
    });
  }

  /**
   * A live removal: a tile read that left before it would put the card back, so it counts
   * as a write.
   */
  private dropCard(cardId: Uuid, only: Uuid | null = null): void {
    this.localWrites++;
    this.removeCard(cardId, null, only);
  }

  private placeLive(tile: TodoCardTile): void {
    if (this.source() === 'mine' && !this.me()) {
      this.refresh();
      return;
    }
    this.removeCard(tile.id, this.keeps(tile) ? tile.boardId : null);
    if (!this.keeps(tile)) return;
    if (!this.update(tile.boardId, (b) => placeTile(b, tile))) this.refresh();
  }

  /** The rows show this card: "Alle" every card, "Meine To-Dos" the cards assigned to me. */
  private keeps(card: TodoCardTile): boolean {
    const me = this.me();
    return this.source() === 'all' || !me || card.assignees.some((a) => a.principalId === me);
  }

  /** Take a card out of every row but `except` (or only out of `only`), when a row holds it. */
  private removeCard(cardId: Uuid, except: Uuid | null = null, only: Uuid | null = null): void {
    const list = this.boards();
    const drop = (b: TodoAssignedBoard) =>
      b.id !== except && (only === null || b.id === only) && b.cards.some((c) => c.id === cardId);
    if (!list.some(drop)) return;
    this.mutations++;
    this.boards.set(list.map((b) => (drop(b) ? removeTile(b, cardId) : b)));
  }

  /** Replace one board through `fn`; false when the rows do not hold it. */
  private update(boardId: Uuid, fn: (board: TodoAssignedBoard) => TodoAssignedBoard): boolean {
    const list = this.boards();
    if (!list.some((b) => b.id === boardId)) return false;
    this.mutations++;
    this.boards.set(list.map((b) => (b.id === boardId ? fn(b) : b)));
    return true;
  }

  /** The rollback applies only when nothing else changed the row meanwhile. */
  move(boardId: Uuid, cardId: Uuid, move: TodoCardMove): void {
    const before = this.boards().find((b) => b.id === boardId);
    if (!before?.canWrite) return;
    const optimistic = applyMove(before, cardId, move);
    this.localWrites++;
    this.update(boardId, () => optimistic);
    this.pending++;
    this.api
      .moveCard(cardId, move)
      .pipe(finalize(() => this.pending--))
      .subscribe({
        next: (tile) => {
          this.localWrites++;
          this.update(boardId, (b) => replaceTile(b, tile));
        },
        error: (err: unknown) => {
          this.toast.show(this.i18n.translate(moveErrorText(err, 'todos.error.move')), 'error');
          if (this.boards().find((b) => b.id === boardId) === optimistic)
            this.update(boardId, () => before);
          this.refresh();
        },
      });
  }

  /**
   * Move a card of one row to another board at once, and send the transfer. The answer
   * replaces the tile (labels without a match there are gone); a refusal puts the rows
   * back and reads them again.
   */
  transfer(fromId: Uuid, toId: Uuid, tile: TodoCardTile, move: TodoCardMove): void {
    const before = this.boards();
    if (!before.find((b) => b.id === toId)?.canWrite) return;
    const optimistic = before.map((b) =>
      b.id === fromId ? removeTile(b, tile.id) : b.id === toId ? insertTile(b, tile, move) : b,
    );
    this.mutations++;
    this.localWrites++;
    this.boards.set(optimistic);
    this.pending++;
    this.api
      .transferCard(tile.id, { boardId: toId, ...move })
      .pipe(finalize(() => this.pending--))
      .subscribe({
        next: (card) => {
          this.accept(card);
          this.transferred.emit(card);
        },
        error: (err: unknown) => {
          this.toast.show(this.i18n.translate(moveErrorText(err, 'todos.error.transfer')), 'error');
          if (this.boards() === optimistic) {
            this.mutations++;
            this.localWrites++;
            this.boards.set(before);
          }
          this.refresh();
        },
      });
  }
}
