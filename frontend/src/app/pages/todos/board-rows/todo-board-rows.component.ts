import { CdkScrollable } from '@angular/cdk/scrolling';
import { HttpErrorResponse } from '@angular/common/http';
import { CdkDrag, CdkDropList, type CdkDragDrop, type CdkDragEnter } from '@angular/cdk/drag-drop';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  type OnInit,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { Subject, finalize, merge } from 'rxjs';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type TodoAssignedBoard,
  type TodoCardDetail,
  type TodoCardMove,
  type TodoCardTile,
  type TodoColumn,
  type TodoLabel,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { TodoLiveService, batchPings } from '@core/ws/todo-live.service';
import type { TodoPing } from '@core/ws/ws-messages';
import { IconComponent, ToastService } from '@stupa-makers/ui-kit';
import { TodoCardTileComponent } from '../../../features/todos/card-tile/todo-card-tile.component';
import {
  applyMove,
  dropMove,
  filterActive,
  insertTile,
  matchesFilter,
  moveRequest,
  placeTile,
  removeTile,
  replaceTile,
  sortedColumns,
  type BoardFilter,
} from '../../../features/todos/todos.util';
import { BOARD_ICON } from '../board-picker/todo-board-picker.component';
import { DONE_PREVIEW } from '../board-view/todo-board-view.component';

/** The ids of the collapsed rows, per browser ("Meine To-Dos" and "Alle" share them). */
export const COLLAPSED_KEY = 'ap.todos.rows.collapsed';

/** The id of the drop list of a column in the rows, for `cdkDropListConnectedTo`. */
export function rowDropId(columnId: Uuid): string {
  return `br-list-${columnId}`;
}

/** A card of another board (the personal board above the rows) landed in a row. */
export interface RowDrop {
  boardId: Uuid;
  cardId: Uuid;
  move: TodoCardMove;
}

/** How `boardRows` reads the cards. */
export interface RowOptions {
  /**
   * "Alle": a row holds every card of its board, so "Zuständig: Ich" keeps the cards
   * assigned to `me`, and a board without a card stays a row while no filter is on
   * (unless no board has a card at all).
   */
  all?: boolean;
  me?: Uuid | null;
  /**
   * The labels of the label filter by id. Labels are per board, so a row keeps the cards
   * with a label of the same name (case-insensitive). Without it the filter compares ids.
   */
  filterLabels?: ReadonlyMap<Uuid, TodoLabel>;
}

/** A row as shown: the board, its columns in order and the cards that pass the filters. */
export interface BoardRow {
  board: TodoAssignedBoard;
  columns: TodoColumn[];
  cards: ReadonlyMap<Uuid, readonly TodoCardTile[]>;
  labels: ReadonlyMap<Uuid, TodoLabel>;
  count: number;
}

/** The keyboard drag: the held card, its row and its place now. */
interface KeyDrag {
  boardId: Uuid;
  cardId: Uuid;
  col: number;
  index: number;
  fromCol: number;
  fromIndex: number;
}

/**
 * Build the rows: every board with its columns and the cards that pass the filters.
 * A row without such a card is left out (see `RowOptions.all` for "Alle"). Under
 * "Meine To-Dos" every card of a row is assigned to the viewer, so "Zuständig: Ich"
 * keeps all of them.
 */
export function boardRows(
  boards: readonly TodoAssignedBoard[],
  filter: BoardFilter,
  today: string,
  opts: RowOptions = {},
): BoardRow[] {
  const rows: BoardRow[] = [];
  const keepEmpty = !!opts.all && !filterActive(filter) && boards.some((b) => b.cards.length > 0);
  const byName = opts.filterLabels;
  const wanted = new Set(filter.labels.map((id) => byName?.get(id)?.name.toLowerCase() ?? ''));
  for (const board of boards) {
    const labels = new Map(board.labels.map((l) => [l.id, l]));
    const mine = opts.all
      ? board.cards.filter((c) => opts.me && c.assignees.some((a) => a.principalId === opts.me))
      : board.cards;
    const ctx = { today, mine: new Set(mine.map((c) => c.id)), labels };
    let rowFilter = filter;
    if (byName && filter.labels.length) {
      const ids = board.labels.filter((l) => wanted.has(l.name.toLowerCase())).map((l) => l.id);
      // No label of that name on this board: '' matches no card.
      rowFilter = { ...filter, labels: ids.length ? ids : [''] };
    }
    const columns = sortedColumns(board.columns);
    const cards = new Map<Uuid, TodoCardTile[]>(columns.map((c) => [c.id, []]));
    let count = 0;
    for (const card of board.cards) {
      const list = cards.get(card.columnId);
      if (!list || !matchesFilter(card, rowFilter, ctx)) continue;
      list.push(card);
      count++;
    }
    if (count || keepEmpty) rows.push({ board, columns, cards, labels, count });
  }
  return rows;
}

function readCollapsed(): Set<Uuid> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    const ids: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(ids) ? ids.filter((x): x is string => typeof x === 'string') : []);
  } catch {
    return new Set();
  }
}

function writeCollapsed(ids: ReadonlySet<Uuid>): void {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...ids]));
  } catch {
    // Storage is off or full: the rows stay open in the next visit.
  }
}

/**
 * The board rows. `source="mine"`: the rows under "Meine To-Dos", one row per other board
 * that holds cards assigned to me (`GET /todos/mine/boards`), with only my cards.
 * `source="all"`: the meta-board "Alle", one row per readable board with all its cards
 * (`GET /todos/all/boards`). Each row is headed by the board name and the count, with the
 * columns of that board.
 *
 * A row is a region with a heading; the heading button collapses it (remembered per
 * browser). A pointer drag reaches every column of every writable row and the drop lists
 * of `extraDrops` (the personal board above the rows): a drop on the same board moves the
 * card (`moveCard`), a drop on another row transfers it (`transferCard`, with the
 * neighbors of the drop place), both at once and back with a toast when the server
 * refuses. A card from `extraDrops` comes out as `dropIn` for the page. The keyboard drag
 * stays in its row: Space lifts, the arrows move, Space or Enter put down, Escape puts
 * back. A row without `canWrite` is read only: no drag source and no drop target. On a
 * phone the columns of a row scroll sideways and there is no drag.
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
  imports: [CdkDrag, CdkDropList, CdkScrollable, RouterLink, TranslatePipe, IconComponent, TodoCardTileComponent],
  host: {
    class: 'br-host',
    '(document:focusin)': 'leaveDrag($event)',
    '(document:pointerdown)': 'leaveDrag($event)',
  },
  templateUrl: './todo-board-rows.component.html',
  styleUrl: './todo-board-rows.component.scss',
})
export class TodoBoardRowsComponent implements OnInit {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  private readonly live = inject(TodoLiveService);

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

  readonly openCard = output<Uuid>();
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

  readonly boards = signal<TodoAssignedBoard[]>([]);
  readonly collapsed = signal<ReadonlySet<Uuid>>(readCollapsed());
  /** Done columns opened past the preview, by column id. */
  readonly expanded = signal<ReadonlySet<Uuid>>(new Set());
  readonly kb = signal<KeyDrag | null>(null);
  /** A touch lifts a card after this long press, so a swipe over the cards scrolls; a mouse lifts it at once. */
  protected readonly dragDelay = { touch: 400, mouse: 0 };
  /** The keydown of Space lifted or put down a card, so its keyup must not click the tile. */
  private spaceTaken = false;
  /** The pointer drag: the column the card left and the column it is over (any row). */
  readonly ptr = signal<{ from: Uuid; over: Uuid } | null>(null);
  /** A card of the rows is held, by pointer or keyboard. */
  readonly dragging = computed(() => this.ptr() !== null || this.kb() !== null);
  readonly announce = signal('');
  readonly icon = BOARD_ICON;

  private etag: string | null = null;
  /** Counts the local changes: a poll that left before one is dropped. */
  private mutations = 0;
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
  /** The drop lists of the writable open rows. */
  readonly dropIds = computed(() =>
    this.phone()
      ? []
      : this.rows()
          .filter((r) => r.board.canWrite && this.isOpen(r))
          .flatMap((r) => r.columns.map((c) => rowDropId(c.id))),
  );
  /** Where a drag of a writable row may go: every writable row and `extraDrops`. */
  readonly connected = computed(() => [...this.dropIds(), ...this.extraDrops()]);
  readonly dropId = rowDropId;

  constructor() {
    effect(() => {
      const rows = this.rows();
      if (this.ready()) this.matches.emit(rows.reduce((n, r) => n + r.count, 0));
    });
    effect(() => {
      const ids = this.dropIds();
      untracked(() => this.drops.emit(ids));
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
    // The first read waits for the inputs: `source` picks the route.
    this.load(null);
  }

  // ------------------------------------------------------------------ data

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
      // The rows are an extra: a failed read keeps what is on screen.
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
    this.load(null);
  }

  /**
   * The card drawer changed a card: take it out of the rows of other boards (it moved to
   * another board), put it in its row, then read the rows again.
   */
  cardChanged(card: TodoCardDetail): void {
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
    const board = this.boards().find((b) => b.cards.some((c) => c.id === id));
    if (!board) return;
    this.update(board.id, (b) => removeTile(b, id));
    this.refresh();
  }

  /** Merge only the comment count: the drawer's copy of the rest can be stale. */
  commentsChanged(event: { id: Uuid; commentCount: number }): void {
    const board = this.boards().find((b) => b.cards.some((c) => c.id === event.id));
    if (!board) return;
    this.update(board.id, (b) => ({
      ...b,
      cards: b.cards.map((c) => (c.id === event.id ? { ...c, commentCount: event.commentCount } : c)),
    }));
  }

  /** A card of another board lands in a row at once, before the server answers (`dropIn`). */
  receive(tile: TodoCardTile, boardId: Uuid, move: TodoCardMove): void {
    this.update(boardId, (b) => insertTile(b, tile, move));
  }

  /**
   * The server answer of a transfer into a row replaces the tile. Under "Meine To-Dos" a
   * card that is not assigned to me leaves the rows: they show only my cards.
   */
  accept(card: TodoCardTile): void {
    if (!this.keeps(card)) {
      this.removeCard(card.id);
      return;
    }
    this.update(card.boardId, (b) => replaceTile(b, card));
  }

  /** Take a card out of its row (it went onto the personal board); null when no row holds it. */
  take(cardId: Uuid): TodoCardTile | null {
    for (const b of this.boards()) {
      const card = b.cards.find((c) => c.id === cardId);
      if (card) {
        this.update(b.id, (x) => removeTile(x, cardId));
        return card;
      }
    }
    return null;
  }

  // ------------------------------------------------------------------ live

  /** A card is held or a write is in flight: a live change waits. */
  private busy(): boolean {
    return this.dragging() || this.hold() || this.pending > 0;
  }

  private onPings(pings: readonly TodoPing[]): void {
    if (this.busy()) {
      for (const p of pings) this.liveRetry.next(p);
      return;
    }
    let poll = false;
    for (const p of pings) {
      if (p.type === 'board') poll = true;
      else if (p.type === 'card_removed') this.removeCard(p.cardId, null, p.boardId);
      else this.readTile(p);
    }
    if (poll) this.poll();
  }

  /** Read the tile of a `card` ping and put it in place; a 404 takes it out of every row. */
  private readTile(ping: TodoPing & { type: 'card' }): void {
    this.api.cardTile(ping.cardId).subscribe({
      next: (tile) => {
        if (this.busy()) this.liveRetry.next(ping);
        else this.placeLive(tile);
      },
      error: (err: unknown) => {
        if (err instanceof HttpErrorResponse && err.status === 404) this.removeCard(ping.cardId);
      },
    });
  }

  private placeLive(tile: TodoCardTile): void {
    if (this.source() === 'mine' && !this.me()) {
      this.refresh();
      return;
    }
    // A card the rows do not show leaves every row; any other leaves the rows of other boards.
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

  // ------------------------------------------------------------------ rows

  isOpen(row: BoardRow): boolean {
    return !this.collapsed().has(row.board.id);
  }

  toggle(row: BoardRow): void {
    const next = new Set(this.collapsed());
    if (next.has(row.board.id)) next.delete(row.board.id);
    else next.add(row.board.id);
    this.collapsed.set(next);
    writeCollapsed(next);
    if (this.kb()?.boardId === row.board.id) this.kb.set(null);
  }

  canDrag(row: BoardRow): boolean {
    return row.board.canWrite && !this.phone();
  }

  /** The cards of a column as shown: the keyboard drag and the done preview. */
  list(row: BoardRow, col: TodoColumn): TodoCardTile[] {
    return this.shown(row).get(col.id) ?? [];
  }

  /** The done cards past the preview; none while a keyboard drag holds a card of the row. */
  more(row: BoardRow, col: TodoColumn): number {
    if (!col.isDone || this.kb()?.boardId === row.board.id) return 0;
    return this.cardsIn(row, col.id).length - this.list(row, col).length;
  }

  /** The number in the column head; it follows a card that is being dragged. */
  count(row: BoardRow, col: TodoColumn): number {
    const n = this.cardsIn(row, col.id).length;
    const move = this.moving(row);
    if (!move || move.from === move.over) return n;
    if (col.id === move.from) return n - 1;
    if (col.id === move.over) return n + 1;
    return n;
  }

  /**
   * The column a dragged card left and the one it is over, by pointer or keyboard. The
   * column ids are unique over all boards, so a pointer drag counts in every row.
   */
  private moving(row: BoardRow): { from: Uuid; over: Uuid } | null {
    const ptr = this.ptr();
    if (ptr) return ptr;
    const kb = this.kb();
    if (!kb || kb.boardId !== row.board.id) return null;
    return { from: row.columns[kb.fromCol].id, over: row.columns[kb.col].id };
  }

  onDragStart(col: TodoColumn): void {
    this.kb.set(null);
    this.ptr.set({ from: col.id, over: col.id });
  }

  onEnter(event: CdkDragEnter<Uuid>): void {
    const over = event.container.data;
    this.ptr.update((p) => (p ? { ...p, over } : p));
  }

  /** The cards of a column that pass the filters. */
  private cardsIn(row: BoardRow, columnId: Uuid): readonly TodoCardTile[] {
    return row.cards.get(columnId) ?? [];
  }

  expand(col: TodoColumn): void {
    this.expanded.update((set) => new Set([...set, col.id]));
  }

  private shown(row: BoardRow): Map<Uuid, TodoCardTile[]> {
    const lists = row.columns.map((c) => [...this.cardsIn(row, c.id)]);
    const kb = this.kb();
    const held = kb?.boardId === row.board.id ? kb : null;
    if (held) {
      let card: TodoCardTile | undefined;
      for (const list of lists) {
        const i = list.findIndex((c) => c.id === held.cardId);
        if (i >= 0) card = list.splice(i, 1)[0];
      }
      if (card) lists[held.col].splice(held.index, 0, card);
    }
    const out = new Map<Uuid, TodoCardTile[]>();
    row.columns.forEach((col, i) => {
      const list = lists[i];
      const limit = col.isDone && !this.expanded().has(col.id) && !held ? DONE_PREVIEW : list.length;
      out.set(col.id, list.slice(0, limit));
    });
    return out;
  }

  // ------------------------------------------------------------------ moves

  private move(boardId: Uuid, cardId: Uuid, move: TodoCardMove): void {
    const before = this.boards().find((b) => b.id === boardId);
    if (!before?.canWrite) return;
    const optimistic = applyMove(before, cardId, move);
    this.update(boardId, () => optimistic);
    this.pending++;
    this.api.moveCard(cardId, move).pipe(finalize(() => this.pending--)).subscribe({
      next: (tile) => this.update(boardId, (b) => replaceTile(b, tile)),
      error: () => {
        this.toast.error(this.i18n.translate('todos.error.move'));
        // Roll back when nothing else changed the row meanwhile, then read the rows again.
        if (this.boards().find((b) => b.id === boardId) === optimistic) this.update(boardId, () => before);
        this.refresh();
      },
    });
  }

  /**
   * Move a card of one row to another board at once, and send the transfer. The answer
   * replaces the tile (labels without a match there are gone); a refusal puts the rows
   * back and reads them again.
   */
  private transfer(fromId: Uuid, toId: Uuid, tile: TodoCardTile, move: TodoCardMove): void {
    const before = this.boards();
    if (!before.find((b) => b.id === toId)?.canWrite) return;
    const optimistic = before.map((b) =>
      b.id === fromId ? removeTile(b, tile.id) : b.id === toId ? insertTile(b, tile, move) : b,
    );
    this.mutations++;
    this.boards.set(optimistic);
    this.pending++;
    this.api.transferCard(tile.id, { boardId: toId, ...move }).pipe(finalize(() => this.pending--)).subscribe({
      next: (card) => {
        this.accept(card);
        this.transferred.emit(card);
      },
      error: () => {
        this.toast.error(this.i18n.translate('todos.error.transfer'));
        if (this.boards() === optimistic) {
          this.mutations++;
          this.boards.set(before);
        }
        this.refresh();
      },
    });
  }

  drop(row: BoardRow, event: CdkDragDrop<Uuid>): void {
    const cardId = event.item.data as Uuid;
    const toCol = event.container.data;
    if (toCol === event.previousContainer.data && event.previousIndex === event.currentIndex) return;
    const col = row.columns.find((c) => c.id === toCol);
    if (!col) return;
    const target = this.list(row, col).filter((c) => c.id !== cardId);
    const from = this.boards().find((b) => b.cards.some((c) => c.id === cardId));
    const held = from?.cards.find((c) => c.id === cardId);
    if (!from || !held) {
      // A card of the personal board above the rows: the page moves it over.
      this.dropIn.emit({ boardId: row.board.id, cardId, move: dropMove(target, event.currentIndex, toCol) });
      return;
    }
    if (from.id !== row.board.id) {
      this.transfer(from.id, row.board.id, held, dropMove(target, event.currentIndex, toCol));
      return;
    }
    target.splice(event.currentIndex, 0, held);
    this.move(row.board.id, cardId, moveRequest(target, event.currentIndex, toCol));
  }

  // ------------------------------------------------------------------ keyboard drag

  /**
   * A button activates on the keyup of Space (Firefox does so even after a prevented
   * keydown), so the keyup after a lift or a put-down would open the card and the drawer
   * would end the drag. The keydown handles Space.
   */
  onTileKeyUp(event: KeyboardEvent): void {
    if (event.key !== ' ' || (!this.spaceTaken && !this.kb())) return;
    this.spaceTaken = false;
    event.preventDefault();
  }

  onTileKey(event: KeyboardEvent, row: BoardRow, card: TodoCardTile, colIndex: number, index: number): void {
    if (!this.canDrag(row)) return;
    const kb = this.kb();
    if (!kb) {
      if (event.key !== ' ') return;
      event.preventDefault();
      this.spaceTaken = true;
      this.kb.set({ boardId: row.board.id, cardId: card.id, col: colIndex, index, fromCol: colIndex, fromIndex: index });
      this.say('todos.drag.lifted', row, card);
      return;
    }
    if (kb.cardId !== card.id) return;
    const cols = row.columns;
    switch (event.key) {
      case 'ArrowUp':
      case 'ArrowDown': {
        event.preventDefault();
        const len = this.list(row, cols[kb.col]).length;
        const step = event.key === 'ArrowUp' ? -1 : 1;
        this.kb.set({ ...kb, index: Math.max(0, Math.min(len - 1, kb.index + step)) });
        break;
      }
      case 'ArrowLeft':
      case 'ArrowRight': {
        event.preventDefault();
        const col = Math.max(0, Math.min(cols.length - 1, kb.col + (event.key === 'ArrowLeft' ? -1 : 1)));
        if (col === kb.col) return;
        const others = this.cardsIn(row, cols[col].id).filter((c) => c.id !== kb.cardId).length;
        this.kb.set({ ...kb, col, index: Math.min(kb.index, others) });
        break;
      }
      case ' ':
      case 'Enter':
        event.preventDefault();
        this.spaceTaken = event.key === ' ';
        this.commit(kb, row, card);
        return;
      case 'Escape':
      case 'Tab':
        this.kb.set(null);
        this.say('todos.drag.cancelled', row, card);
        if (event.key === 'Escape') {
          event.preventDefault();
          this.refocus(card.id);
        }
        return;
      default:
        return;
    }
    this.say('todos.drag.moved', row, card);
    this.refocus(card.id);
  }

  /** A keyboard drag ends when the focus or a pointer goes anywhere but the held card. */
  leaveDrag(event: Event): void {
    const kb = this.kb();
    if (!kb) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('.br__item')?.querySelector(`[data-card-id="${kb.cardId}"]`)) return;
    this.kb.set(null);
    const row = this.rows().find((r) => r.board.id === kb.boardId);
    const card = row?.board.cards.find((c) => c.id === kb.cardId);
    if (row && card) this.say('todos.drag.cancelled', row, card);
  }

  private commit(kb: KeyDrag, row: BoardRow, card: TodoCardTile): void {
    const col = row.columns[kb.col];
    const list = this.list(row, col);
    this.kb.set(null);
    if (kb.col === kb.fromCol && kb.index === kb.fromIndex) {
      this.say('todos.drag.cancelled', row, card);
      this.refocus(card.id);
      return;
    }
    this.move(row.board.id, card.id, moveRequest(list, kb.index, col.id));
    this.say('todos.drag.dropped', row, card, col.name);
    this.refocus(card.id);
  }

  private say(
    key: 'todos.drag.lifted' | 'todos.drag.moved' | 'todos.drag.dropped' | 'todos.drag.cancelled',
    row: BoardRow,
    card: TodoCardTile,
    column?: string,
  ): void {
    const kb = this.kb();
    const col = kb ? row.columns[kb.col] : null;
    this.announce.set(
      this.i18n.translate(key, {
        title: card.title,
        column: column ?? col?.name ?? '',
        n: (kb?.index ?? 0) + 1,
        total: col ? this.list(row, col).length : 0,
      }),
    );
  }

  private refocus(cardId: Uuid): void {
    afterNextRender(
      () => this.host.nativeElement.querySelector<HTMLElement>(`[data-card-id="${cardId}"]`)?.focus(),
      { injector: this.injector },
    );
  }
}
