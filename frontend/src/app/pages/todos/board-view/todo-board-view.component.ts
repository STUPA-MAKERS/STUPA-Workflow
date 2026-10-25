import { CdkDrag, CdkDropList, CdkDropListGroup, type CdkDragDrop, type CdkDragEnter } from '@angular/cdk/drag-drop';
import { CdkScrollable } from '@angular/cdk/scrolling';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Uuid } from '@core/api/models';
import type { TodoBoard, TodoCardMove, TodoCardTile, TodoColumn, TodoLabel } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  haptic,
  IconComponent,
  LongPressDirective,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  type TabItem,
  TabPageDirective,
  TabPagerComponent,
} from '@stupa-makers/ui-kit';
import { TodoCardTileComponent } from '../../../features/todos/card-tile/todo-card-tile.component';
import type { TileMenuRequest } from '../../../features/todos/move-sheet/todo-move-sheet.component';
import { DROP_ENTER, dropMove, moveRequest, sortedColumns } from '../../../features/todos/todos.util';
import { KanbanKeyDrag, type KeyDragPosition } from '../../../features/todos/kanban-key-drag';

/** The done column shows this many cards until "n weitere" opens the rest. */
export const DONE_PREVIEW = 3;

/** The id of the drop list of a board column, for `cdkDropListConnectedTo`. */
export function boardDropId(columnId: Uuid): string {
  return `bv-list-${columnId}`;
}

/** A move of the board: the card and the request for the server. */
export interface BoardMove {
  cardId: Uuid;
  move: TodoCardMove;
}

/** The keyboard drag: the held card and its place now. */
/**
 * The columns of a board.
 *
 * Desktop: the columns side by side, each a drop list of `@angular/cdk/drag-drop`. A
 * tile lifts with a shadow, the place it would land is a dashed box. The keyboard does
 * the same: Space lifts the focused card, the arrows move it inside and between the
 * columns, Space or Enter put it down, Escape puts it back. A pointer drag also reaches
 * the drop lists of `connectTo` (the rows of "Meine To-Dos"); the keyboard stays on the
 * board. A card of a shared board does not enter a column of the personal board
 * (`DROP_ENTER`, the server refuses it). A live region names each
 * step for a screen reader.
 *
 * The done column shows its newest cards and "n weitere · Archiv". Each column ends
 * with "+ To-Do", which opens a quick field for a title.
 *
 * Phone: one page per column behind tabs with the counts, in the tab pager of the kit
 * (`app-tab-pager`): a swipe moves one column, a tab scrolls to its page, and the ink
 * under the tabs moves with the scroll. The pager and the tab bar run to the edges of the
 * screen, so a card or a tab leaves at the edge and not at the gutter. Each page scrolls
 * down by itself; an empty column shows
 * "Keine Karten" in the middle. No drag: a long press on a tile of a writable board
 * emits `menu`, and the page moves the card through its "Verschieben" sheet. The swipe
 * stays a swipe, because a drift of the finger stops the press.
 */
@Component({
  selector: 'app-todo-board-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CdkDrag,
    CdkDropList,
    CdkDropListGroup,
    CdkScrollable,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    LongPressDirective,
    RowMenuComponent,
    ScrollFadeDirective,
    TabPageDirective,
    TabPagerComponent,
    TodoCardTileComponent,
  ],
  host: {
    '[class.bv-host--natural]': '!fill()',
    '(document:focusin)': 'leaveDrag($event)',
    '(document:pointerdown)': 'leaveDrag($event)',
  },
  templateUrl: './todo-board-view.component.html',
  styleUrl: './todo-board-view.component.scss',
})
export class TodoBoardViewComponent {
  private readonly i18n = inject(I18nService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly board = input.required<TodoBoard>();
  /** The cards that pass the filters, by column id, in board order. */
  readonly cards = input.required<ReadonlyMap<Uuid, readonly TodoCardTile[]>>();
  readonly labels = input<ReadonlyMap<Uuid, TodoLabel>>(new Map());
  readonly today = input.required<string>();
  readonly phone = input(false);
  /**
   * The board fills the free height of the page, and each column (or phone page) scrolls
   * inside. Off, the board is as tall as its cards: the page scrolls it together with
   * the rows of "Meine To-Dos" below it.
   */
  readonly fill = input(true);
  /**
   * The ids of the drop lists of other boards (the rows of "Meine To-Dos") that a card of
   * this board may go to, and that may drop a card here. A card from there comes out as
   * `dropIn`; the page moves it to this board.
   */
  readonly connectTo = input<string[]>([]);

  readonly openCard = output<Uuid>();
  /** Phone: a long press on a tile of a writable board asks for the "Verschieben" sheet. */
  readonly menu = output<TileMenuRequest>();
  readonly moveCard = output<BoardMove>();
  /** A card of another board landed in a column of this board (`connectTo`). */
  readonly dropIn = output<BoardMove>();
  readonly quickAdd = output<{ columnId: Uuid; title: string }>();
  readonly addIn = output<Uuid>();
  readonly settings = output<void>();
  readonly archive = output<void>();

  readonly columns = computed(() => sortedColumns(this.board().columns));
  readonly canWrite = computed(() => this.board().canWrite);

  /** Ask the page for the "Verschieben" sheet of a tile (a long press on the phone). */
  askMenu(card: TodoCardTile): void {
    const b = this.board();
    this.menu.emit({ card, boardId: b.id, boardKind: b.kind, columns: this.columns() });
  }
  /** A card of a shared board does not enter the personal board (`canTransfer`). */
  readonly enter = computed(() => DROP_ENTER[this.board().kind]);
  readonly dropId = boardDropId;

  /** Done columns opened past the preview. */
  readonly expanded = signal<ReadonlySet<Uuid>>(new Set());
  readonly adding = signal<Uuid | null>(null);
  readonly draft = signal('');
  /** The keyboard drag; `kb` is the held card. */
  private readonly keyDrag = new KanbanKeyDrag<KeyDragPosition>();
  readonly kb = this.keyDrag.held;
  /** A touch lifts a card after this long press, so a swipe over the cards scrolls; a mouse lifts it at once. */
  protected readonly dragDelay = { touch: 400, mouse: 0 };
  /** The pointer drag: the column the card left and the column it is over. */
  readonly ptr = signal<{ from: Uuid; over: Uuid } | null>(null);
  /** A card is held, by pointer or keyboard: the page holds a live read until it lands. */
  readonly dragging = computed(() => this.ptr() !== null || this.kb() !== null);
  readonly announce = signal('');
  /** Phone: the column on screen. */
  readonly phoneColumn = signal(0);

  /** The cards of each column as shown: the filters, the keyboard drag, the done preview. */
  readonly shown = computed(() => {
    const cols = this.columns();
    const lists = cols.map((c) => [...(this.cards().get(c.id) ?? [])]);
    const kb = this.kb();
    if (kb) {
      let held: TodoCardTile | undefined;
      for (const list of lists) {
        const i = list.findIndex((c) => c.id === kb.cardId);
        if (i >= 0) held = list.splice(i, 1)[0];
      }
      if (held) lists[kb.col]?.splice(kb.index, 0, held);
    }
    const out = new Map<Uuid, TodoCardTile[]>();
    cols.forEach((col, i) => {
      const list = lists[i];
      const limit = col.isDone && !this.expanded().has(col.id) && !kb ? DONE_PREVIEW : list.length;
      out.set(col.id, list.slice(0, limit));
    });
    return out;
  });

  readonly tabs = computed<TabItem[]>(() =>
    this.columns().map((c) => ({ id: c.id, label: c.name, count: this.cards().get(c.id)?.length ?? 0 })),
  );

  readonly phoneCol = computed<TodoColumn | null>(() => {
    const cols = this.columns();
    return cols[Math.min(this.phoneColumn(), cols.length - 1)] ?? null;
  });

  /** The number in the column head; it follows a card that is being dragged. */
  count(col: TodoColumn): number {
    const n = this.total(col);
    const move = this.moving();
    if (!move || move.from === move.over) return n;
    if (col.id === move.from) return n - 1;
    if (col.id === move.over) return n + 1;
    return n;
  }

  more(col: TodoColumn): number {
    return this.total(col) - (this.shown().get(col.id)?.length ?? 0);
  }

  private total(col: TodoColumn): number {
    return this.cards().get(col.id)?.length ?? 0;
  }

  /** The column a dragged card left and the one it is over, by pointer or keyboard. */
  private moving(): { from: Uuid; over: Uuid } | null {
    const ptr = this.ptr();
    if (ptr) return ptr;
    const kb = this.kb();
    if (!kb) return null;
    const cols = this.columns();
    return { from: cols[kb.fromCol].id, over: cols[kb.col].id };
  }

  /** A pointer drag computes its move from the shown lists, so a held card goes back first. */
  onDragStart(col: TodoColumn): void {
    haptic('lift');
    this.cancelKeyDrag();
    this.ptr.set({ from: col.id, over: col.id });
  }

  onEnter(event: CdkDragEnter<Uuid>): void {
    const over = event.container.data;
    this.ptr.update((p) => (p ? { ...p, over } : p));
  }

  list(col: TodoColumn): TodoCardTile[] {
    return this.shown().get(col.id) ?? [];
  }

  expand(col: TodoColumn): void {
    this.expanded.update((set) => new Set([...set, col.id]));
  }

  columnMenu(col: TodoColumn): RowMenuSection[] {
    const items: RowMenuItem[] = [];
    if (this.canWrite()) items.push({ id: 'add', label: this.i18n.translate('todos.column.add'), icon: 'plus' });
    if (this.board().canConfigure) {
      items.push({ id: 'settings', label: this.i18n.translate('todos.column.settings'), icon: 'tune' });
    }
    if (col.isDone && this.board().archivedCount) {
      items.push({ id: 'archive', label: this.i18n.translate('todos.column.archive'), icon: 'archive' });
    }
    return items.length ? [{ items }] : [];
  }

  onColumnMenu(col: TodoColumn, item: RowMenuItem): void {
    if (item.id === 'add') this.addIn.emit(col.id);
    else if (item.id === 'settings') this.settings.emit();
    else if (item.id === 'archive') this.archive.emit();
  }

  startAdd(col: TodoColumn): void {
    this.draft.set('');
    this.adding.set(col.id);
    this.focus(`[data-quick="${col.id}"]`);
  }

  submitAdd(col: TodoColumn): void {
    const title = this.draft().trim();
    if (!title) return;
    this.quickAdd.emit({ columnId: col.id, title });
    this.draft.set('');
  }

  onAddKey(event: KeyboardEvent, col: TodoColumn): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      this.adding.set(null);
    } else if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.submitAdd(col);
    }
  }

  drop(event: CdkDragDrop<Uuid>): void {
    const cardId = event.item.data as Uuid;
    const toCol = event.container.data;
    if (toCol === event.previousContainer.data && event.previousIndex === event.currentIndex) return;
    const col = this.columns().find((c) => c.id === toCol);
    if (!col) return;
    const target = this.list(col).filter((c) => c.id !== cardId);
    const held = this.board().cards.find((c) => c.id === cardId);
    if (!held) {
      this.dropIn.emit({ cardId, move: dropMove(target, event.currentIndex, toCol) });
      return;
    }
    target.splice(event.currentIndex, 0, held);
    this.moveCard.emit({ cardId, move: moveRequest(target, event.currentIndex, toCol) });
  }

  onTileKeyUp(event: KeyboardEvent): void {
    this.keyDrag.keyUp(event);
  }

  onTileKey(event: KeyboardEvent, card: TodoCardTile, colIndex: number, index: number): void {
    if (!this.canWrite() || this.phone()) return;
    const cols = this.columns();
    const step = this.keyDrag.key(
      event,
      card.id,
      () => ({ cardId: card.id, col: colIndex, index, fromCol: colIndex, fromIndex: index }),
      {
        count: cols.length,
        length: (col) => this.list(cols[col]).length,
        others: (col, id) => (this.cards().get(cols[col].id) ?? []).filter((c) => c.id !== id).length,
      },
    );
    switch (step.kind) {
      case 'lift':
        this.say('todos.drag.lifted', card);
        return;
      case 'move':
        this.say('todos.drag.moved', card);
        this.refocus(card.id);
        return;
      case 'drop':
        this.commit(card);
        return;
      case 'cancel':
        this.say('todos.drag.cancelled', card);
        if (step.refocus) this.refocus(card.id);
        return;
      default:
        return;
    }
  }

  /**
   * A keyboard drag ends when the focus or a pointer goes anywhere but the held card,
   * because only a key on that card ends it. Without that end the board keeps the card at
   * its provisional place, with shifted counts. The refocus after a step lands inside the
   * held card and keeps the drag.
   */
  leaveDrag(event: Event): void {
    const kb = this.kb();
    if (!kb) return;
    const target = event.target instanceof Element ? event.target : null;
    const item = target?.closest('.bv__item');
    if (item?.querySelector(`[data-card-id="${kb.cardId}"]`)) return;
    this.cancelKeyDrag();
  }

  private cancelKeyDrag(): void {
    const kb = this.kb();
    if (!kb) return;
    this.kb.set(null);
    const card = this.board().cards.find((c) => c.id === kb.cardId);
    if (card) this.say('todos.drag.cancelled', card);
  }

  private commit(card: TodoCardTile): void {
    const kb = this.kb();
    if (!kb) return;
    const col = this.columns()[kb.col];
    const list = this.list(col);
    this.kb.set(null);
    if (kb.col === kb.fromCol && kb.index === kb.fromIndex) {
      this.say('todos.drag.cancelled', card);
      this.refocus(card.id);
      return;
    }
    this.moveCard.emit({ cardId: card.id, move: moveRequest(list, kb.index, col.id) });
    this.say('todos.drag.dropped', card, col.name);
    this.refocus(card.id);
  }

  private say(key: 'todos.drag.lifted' | 'todos.drag.moved' | 'todos.drag.dropped' | 'todos.drag.cancelled', card: TodoCardTile, column?: string): void {
    const kb = this.kb();
    const col = kb ? this.columns()[kb.col] : null;
    this.announce.set(
      this.i18n.translate(key, {
        title: card.title,
        column: column ?? col?.name ?? '',
        n: (kb?.index ?? 0) + 1,
        total: col ? this.list(col).length : 0,
      }),
    );
  }

  private refocus(cardId: Uuid): void {
    this.focus(`[data-card-id="${cardId}"]`);
  }

  private focus(selector: string): void {
    afterNextRender(
      () => this.host.nativeElement.querySelector<HTMLElement>(selector)?.focus(),
      { injector: this.injector },
    );
  }

  /** A tab, or a swipe to its page: show its column. */
  selectPhoneColumn(id: string | null): void {
    const i = this.columns().findIndex((c) => c.id === id);
    if (i >= 0) this.phoneColumn.set(i);
  }

  /** The column of a tab of the phone pager. */
  column(id: string): TodoColumn | null {
    return this.columns().find((c) => c.id === id) ?? null;
  }
}
