import { CdkScrollable } from '@angular/cdk/scrolling';
import { CdkDrag, CdkDropList, CdkDropListGroup, type CdkDragDrop, type CdkDragEnter } from '@angular/cdk/drag-drop';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
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
import { IconComponent, ToastService } from '@stupa-makers/ui-kit';
import { TodoCardTileComponent } from '../../../features/todos/card-tile/todo-card-tile.component';
import {
  applyMove,
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

/** The ids of the collapsed rows, per browser. */
export const COLLAPSED_KEY = 'ap.todos.rows.collapsed';

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
 * A row without such a card is left out. Every card of a row is assigned to the viewer,
 * so "Zuständig: Ich" keeps all of them.
 */
export function boardRows(
  boards: readonly TodoAssignedBoard[],
  filter: BoardFilter,
  today: string,
): BoardRow[] {
  const rows: BoardRow[] = [];
  for (const board of boards) {
    const labels = new Map(board.labels.map((l) => [l.id, l]));
    const ctx = { today, mine: new Set(board.cards.map((c) => c.id)), labels };
    const columns = sortedColumns(board.columns);
    const cards = new Map<Uuid, TodoCardTile[]>(columns.map((c) => [c.id, []]));
    let count = 0;
    for (const card of board.cards) {
      const list = cards.get(card.columnId);
      if (!list || !matchesFilter(card, filter, ctx)) continue;
      list.push(card);
      count++;
    }
    if (count) rows.push({ board, columns, cards, labels, count });
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
 * The rows under "Meine To-Dos": one row per other board that holds cards assigned to me
 * (`GET /todos/mine/boards`), headed by the board name and the count, with the columns of
 * that board and only my cards in them.
 *
 * A row is a region with a heading; the heading button collapses it (remembered per
 * browser). A drag moves a card inside its row only, on its own board, through the move
 * route of the board: each row is its own drop group, so a card never reaches another
 * row or the personal board. The keyboard drag works as on the board: Space lifts, the
 * arrows move, Space or Enter put down, Escape puts back. A row without `canWrite` is
 * read only. On a phone the columns of a row scroll sideways and there is no drag.
 *
 * The page calls `poll()` with its own poll (ETag, 304 keeps the rows), and the
 * `card…` methods after a change in the card drawer.
 */
@Component({
  selector: 'app-todo-board-rows',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CdkDrag, CdkDropList, CdkDropListGroup, CdkScrollable, RouterLink, TranslatePipe, IconComponent, TodoCardTileComponent],
  host: {
    class: 'br-host',
    '(document:focusin)': 'leaveDrag($event)',
    '(document:pointerdown)': 'leaveDrag($event)',
  },
  templateUrl: './todo-board-rows.component.html',
  styleUrl: './todo-board-rows.component.scss',
})
export class TodoBoardRowsComponent {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly filter = input.required<BoardFilter>();
  readonly today = input.required<string>();
  readonly phone = input(false);

  readonly openCard = output<Uuid>();
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
  /** The pointer drag: the row, the column the card left and the column it is over. */
  readonly ptr = signal<{ boardId: Uuid; from: Uuid; over: Uuid } | null>(null);
  readonly announce = signal('');
  readonly icon = BOARD_ICON;

  private etag: string | null = null;
  /** Counts the local changes: a poll that left before one is dropped. */
  private mutations = 0;
  private seq = 0;
  /** The first read answered or failed. */
  private readonly ready = signal(false);

  readonly rows = computed(() => boardRows(this.boards(), this.filter(), this.today()));

  constructor() {
    this.load(null);
    effect(() => {
      const rows = this.rows();
      if (this.ready()) this.matches.emit(rows.reduce((n, r) => n + r.count, 0));
    });
  }

  // ------------------------------------------------------------------ data

  private load(etag: string | null): void {
    const seq = ++this.seq;
    const muts = this.mutations;
    this.api.pollMineBoards(etag).subscribe({
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

  /** The card drawer changed a card: put it in its row, then read the rows again. */
  cardChanged(card: TodoCardDetail): void {
    if (!this.update(card.boardId, (b) => (card.archivedAt ? removeTile(b, card.id) : placeTile(b, card)))) return;
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

  /** The column a dragged card of the row left and the one it is over, by pointer or keyboard. */
  private moving(row: BoardRow): { from: Uuid; over: Uuid } | null {
    const ptr = this.ptr();
    if (ptr) return ptr.boardId === row.board.id ? ptr : null;
    const kb = this.kb();
    if (!kb || kb.boardId !== row.board.id) return null;
    return { from: row.columns[kb.fromCol].id, over: row.columns[kb.col].id };
  }

  onDragStart(row: BoardRow, col: TodoColumn): void {
    this.kb.set(null);
    this.ptr.set({ boardId: row.board.id, from: col.id, over: col.id });
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
    this.api.moveCard(cardId, move).subscribe({
      next: (tile) => this.update(boardId, (b) => replaceTile(b, tile)),
      error: () => {
        this.toast.error(this.i18n.translate('todos.error.move'));
        // Roll back when nothing else changed the row meanwhile, then read the rows again.
        if (this.boards().find((b) => b.id === boardId) === optimistic) this.update(boardId, () => before);
        this.refresh();
      },
    });
  }

  drop(row: BoardRow, event: CdkDragDrop<Uuid>): void {
    const cardId = event.item.data as Uuid;
    const toCol = event.container.data;
    if (toCol === event.previousContainer.data && event.previousIndex === event.currentIndex) return;
    const col = row.columns.find((c) => c.id === toCol);
    const held = row.board.cards.find((c) => c.id === cardId);
    if (!col || !held) return;
    const target = this.list(row, col).filter((c) => c.id !== cardId);
    target.splice(event.currentIndex, 0, held);
    this.move(row.board.id, cardId, moveRequest(target, event.currentIndex, toCol));
  }

  // ------------------------------------------------------------------ keyboard drag

  onTileKey(event: KeyboardEvent, row: BoardRow, card: TodoCardTile, colIndex: number, index: number): void {
    if (!this.canDrag(row)) return;
    const kb = this.kb();
    if (!kb) {
      if (event.key !== ' ') return;
      event.preventDefault();
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
