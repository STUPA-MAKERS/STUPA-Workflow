import { CdkDrag, CdkDropList, CdkDropListGroup, type CdkDragDrop } from '@angular/cdk/drag-drop';
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
import type { TranslationKey } from '@core/i18n/translations';
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
import {
  DROP_ENTER,
  dropMove,
  insertAt,
  moveRequest,
  sortedColumns,
  withHeld,
} from '../../../features/todos/todos.util';
import { KanbanKeyDrag, type KeyDragPosition } from '../../../features/todos/kanban-key-drag';

/** The done column shows this many cards until "n weitere" opens the rest. */
export const DONE_PREVIEW = 3;

/** The id of the drop list of a board column, for `cdkDropListConnectedTo`. */
export function boardDropId(columnId: Uuid): string {
  return `bv-list-${columnId}`;
}

/** A move of the board: the card and the request for the server. */
export interface BoardMove {
  readonly cardId: Uuid;
  readonly move: TodoCardMove;
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
 * Phone: one page per column behind tabs, in the tab pager of the kit
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
  /** The column a pointer drag started in; null without a pointer drag. */
  readonly ptr = signal<Uuid | null>(null);
  /** A card is held, by pointer or keyboard: the page holds a live read until it lands. */
  readonly dragging = computed(() => this.ptr() !== null || this.kb() !== null);
  readonly announce = signal('');
  /** Phone: the column on screen. */
  readonly phoneColumn = signal(0);

  /** The cards of each column as shown: the filters, the keyboard drag, the done preview. */
  readonly shown = computed(() => {
    const cols = this.columns();
    const cards = cols.map((c) => this.cards().get(c.id) ?? []);
    const kb = this.kb();
    const lists = kb ? withHeld(cards, kb) : cards;
    const limit = (col: TodoColumn, list: readonly TodoCardTile[]): number =>
      col.isDone && !this.expanded().has(col.id) && !kb ? DONE_PREVIEW : list.length;
    return new Map(cols.map((col, i) => [col.id, lists[i].slice(0, limit(col, lists[i]))]));
  });

  readonly tabs = computed<TabItem[]>(() =>
    this.columns().map((c) => ({ id: c.id, label: c.name })),
  );

  readonly phoneCol = computed<TodoColumn | null>(() => {
    const cols = this.columns();
    return cols[Math.min(this.phoneColumn(), cols.length - 1)] ?? null;
  });

  more(col: TodoColumn): number {
    return this.total(col) - (this.shown().get(col.id)?.length ?? 0);
  }

  private total(col: TodoColumn): number {
    return this.cards().get(col.id)?.length ?? 0;
  }

  /** A pointer drag computes its move from the shown lists, so a held card goes back first. */
  onDragStart(col: TodoColumn): void {
    haptic('lift');
    this.cancelKeyDrag();
    this.ptr.set(col.id);
  }

  list(col: TodoColumn): readonly TodoCardTile[] {
    return this.shown().get(col.id) ?? [];
  }

  expand(col: TodoColumn): void {
    this.expanded.update((set) => new Set([...set, col.id]));
  }

  columnMenu(col: TodoColumn): RowMenuSection[] {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const archive = col.isDone && !!this.board().archivedCount;
    const items: RowMenuItem[] = [
      ...(this.canWrite()
        ? [{ id: 'add', label: t('todos.column.add'), icon: 'plus' } as const]
        : []),
      ...(this.board().canConfigure
        ? [{ id: 'settings', label: t('todos.column.settings'), icon: 'tune' } as const]
        : []),
      ...(archive
        ? [{ id: 'archive', label: t('todos.column.archive'), icon: 'archive' } as const]
        : []),
    ];
    return items.length ? [{ items }] : [];
  }

  onColumnMenu(col: TodoColumn, item: RowMenuItem): void {
    switch (item.id) {
      case 'add':
        return this.addIn.emit(col.id);
      case 'settings':
        return this.settings.emit();
      case 'archive':
        return this.archive.emit();
      default:
        return;
    }
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
    const placed = insertAt(target, event.currentIndex, held);
    this.moveCard.emit({ cardId, move: moveRequest(placed, event.currentIndex, toCol) });
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
