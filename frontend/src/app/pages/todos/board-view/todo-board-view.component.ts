import { CdkDrag, CdkDropList, CdkDropListGroup, type CdkDragDrop, type CdkDragEnter } from '@angular/cdk/drag-drop';
import { CdkScrollable } from '@angular/cdk/scrolling';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Uuid } from '@core/api/models';
import type { TodoBoard, TodoCardMove, TodoCardTile, TodoColumn, TodoLabel } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { ButtonComponent, IconComponent, TabsComponent, type TabItem } from '@stupa-makers/ui-kit';
import { LongPressDirective } from '@shared/long-press.directive';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { TodoCardTileComponent } from '../../../features/todos/card-tile/todo-card-tile.component';
import type { TileMenuRequest } from '../../../features/todos/tile-menu/todo-tile-menu.component';
import { DROP_ENTER, dropMove, moveRequest, sortedColumns } from '../../../features/todos/todos.util';

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
interface KeyDrag {
  cardId: Uuid;
  col: number;
  index: number;
  fromCol: number;
  fromIndex: number;
}

/**
 * The columns of a board (frames 0, 1, 11, 34).
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
 * Phone: one page per column behind tabs with the counts. The pages sit side by side in
 * a horizontal scroller with CSS scroll snap, so a swipe moves one column, and a tab
 * scrolls to its page. The ink under the tabs moves with the scroll, between two tabs
 * while the pager is between two pages, and the active tab changes at the half way. The
 * pager and the tab bar run to the edges of the screen, so a card or a tab leaves at the
 * edge and not at the gutter. Each page scrolls down by itself; an empty column shows
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
    TabsComponent,
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
  readonly kb = signal<KeyDrag | null>(null);
  /** A touch lifts a card after this long press, so a swipe over the cards scrolls; a mouse lifts it at once. */
  protected readonly dragDelay = { touch: 400, mouse: 0 };
  /** The keydown of Space lifted or put down a card, so its keyup must not click the tile. */
  private spaceTaken = false;
  /** The pointer drag: the column the card left and the column it is over. */
  readonly ptr = signal<{ from: Uuid; over: Uuid } | null>(null);
  /** A card is held, by pointer or keyboard: the page holds a live read until it lands. */
  readonly dragging = computed(() => this.ptr() !== null || this.kb() !== null);
  readonly announce = signal('');
  /** Phone: the column on screen. */
  readonly phoneColumn = signal(0);
  /** Phone: the horizontal scroller with one page per column. */
  private readonly pager = viewChild<ElementRef<HTMLElement>>('pager');
  /** Phone: the tab bar and the ink that moves under it. */
  private readonly tabBar = viewChild<ElementRef<HTMLElement>>('tabBar');
  private readonly ink = viewChild<ElementRef<HTMLElement>>('ink');
  /** A tapped tab: the page the pager scrolls to. The tabs keep it until the scroll arrives. */
  private target: number | null = null;
  private inkFrame = 0;
  private readonly resize =
    typeof ResizeObserver === 'function' ? new ResizeObserver(() => this.placeInk()) : null;
  private readonly stopInk = inject(DestroyRef).onDestroy(() => {
    cancelAnimationFrame(this.inkFrame);
    this.resize?.disconnect();
  });

  /** The ink and the tab strip follow a new active tab, new counts and a new size of the bar. */
  private readonly inkFollows = effect((onCleanup) => {
    this.tabs();
    this.phoneColumn();
    const bar = this.tabBar()?.nativeElement;
    if (!bar) return;
    const place = (): void => this.placeInk();
    let strip: HTMLElement | null = null;
    this.resize?.observe(bar);
    const ref = afterNextRender(
      () => {
        strip = bar.querySelector<HTMLElement>('[role="tablist"]');
        strip?.addEventListener('scroll', place, { passive: true });
        this.revealTab();
        this.placeInk();
      },
      { injector: this.injector },
    );
    onCleanup(() => {
      ref.destroy();
      strip?.removeEventListener('scroll', place);
      this.resize?.unobserve(bar);
    });
  });

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

  onDragStart(col: TodoColumn): void {
    // A pointer drag computes its move from the shown lists, so a held card goes back first.
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

  // ------------------------------------------------------------------ quick add

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

  // ------------------------------------------------------------------ pointer drag

  drop(event: CdkDragDrop<Uuid>): void {
    const cardId = event.item.data as Uuid;
    const toCol = event.container.data;
    if (toCol === event.previousContainer.data && event.previousIndex === event.currentIndex) return;
    const col = this.columns().find((c) => c.id === toCol);
    if (!col) return;
    const target = this.list(col).filter((c) => c.id !== cardId);
    const held = this.board().cards.find((c) => c.id === cardId);
    if (!held) {
      // A card of another board: the page moves it over.
      this.dropIn.emit({ cardId, move: dropMove(target, event.currentIndex, toCol) });
      return;
    }
    target.splice(event.currentIndex, 0, held);
    this.moveCard.emit({ cardId, move: moveRequest(target, event.currentIndex, toCol) });
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

  onTileKey(event: KeyboardEvent, card: TodoCardTile, colIndex: number, index: number): void {
    if (!this.canWrite() || this.phone()) return;
    const kb = this.kb();
    if (!kb) {
      if (event.key !== ' ') return;
      event.preventDefault();
      this.spaceTaken = true;
      this.kb.set({ cardId: card.id, col: colIndex, index, fromCol: colIndex, fromIndex: index });
      this.say('todos.drag.lifted', card);
      return;
    }
    if (kb.cardId !== card.id) return;
    const cols = this.columns();
    switch (event.key) {
      case 'ArrowUp':
      case 'ArrowDown': {
        event.preventDefault();
        const len = this.list(cols[kb.col]).length;
        const step = event.key === 'ArrowUp' ? -1 : 1;
        this.kb.set({ ...kb, index: Math.max(0, Math.min(len - 1, kb.index + step)) });
        break;
      }
      case 'ArrowLeft':
      case 'ArrowRight': {
        event.preventDefault();
        const col = Math.max(0, Math.min(cols.length - 1, kb.col + (event.key === 'ArrowLeft' ? -1 : 1)));
        if (col === kb.col) return;
        const others = (this.cards().get(cols[col].id) ?? []).filter((c) => c.id !== kb.cardId).length;
        this.kb.set({ ...kb, col, index: Math.min(kb.index, others) });
        break;
      }
      case ' ':
      case 'Enter':
        event.preventDefault();
        this.spaceTaken = event.key === ' ';
        this.commit(card);
        return;
      case 'Escape':
      case 'Tab':
        this.kb.set(null);
        this.say('todos.drag.cancelled', card);
        // Tab leaves the card the native way; only Escape keeps the focus on it.
        if (event.key === 'Escape') {
          event.preventDefault();
          this.refocus(card.id);
        }
        return;
      default:
        return;
    }
    this.say('todos.drag.moved', card);
    this.refocus(card.id);
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

  /** A tab: show its column and scroll the pager to its page. */
  selectPhoneColumn(id: string | null): void {
    const i = this.columns().findIndex((c) => c.id === id);
    if (i < 0) return;
    this.phoneColumn.set(i);
    const el = this.pager()?.nativeElement;
    if (!el?.clientWidth) return;
    const reduce = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    // `scrollLeft` is negative in a right-to-left page; the sign follows the direction.
    const sign = getComputedStyle(el).direction === 'rtl' ? -1 : 1;
    this.target = i;
    el.scrollTo({ left: sign * i * el.clientWidth, behavior: reduce ? 'auto' : 'smooth' });
  }

  /** The pager moved: the ink follows in the next frame, the tab at the half way. */
  onPagerScroll(): void {
    this.syncPage();
    cancelAnimationFrame(this.inkFrame);
    this.inkFrame = requestAnimationFrame(() => this.placeInk());
  }

  /** A finger on the pager ends the scroll to a tapped tab: the tabs follow the swipe. */
  onPagerTouch(): void {
    this.target = null;
  }

  /**
   * The active tab is the page that fills most of the pager. During the scroll to a
   * tapped tab, the tapped tab stays active, so the tabs between do not light up.
   */
  syncPage(): void {
    const pos = this.pagerPos();
    if (pos === null) return;
    if (this.target !== null) {
      if (Math.abs(pos - this.target) > 0.01) return;
      this.target = null;
    }
    const last = this.columns().length - 1;
    this.phoneColumn.set(Math.max(0, Math.min(Math.round(pos), last)));
  }

  /**
   * The ink under the tabs: at a page, under its tab; between two pages, between their
   * tabs, with the width blended. The rectangles come from the tabs themselves, so a long
   * label, a scrolled tab bar and a right-to-left page need nothing extra.
   */
  placeInk(): void {
    const bar = this.tabBar()?.nativeElement;
    const ink = this.ink()?.nativeElement;
    if (!bar || !ink) return;
    const tabs = bar.querySelectorAll<HTMLElement>('[role="tab"]');
    if (!tabs.length) return;
    const last = tabs.length - 1;
    const pos = Math.max(0, Math.min(this.pagerPos() ?? this.phoneColumn(), last));
    const i = Math.floor(pos);
    const f = pos - i;
    const from = tabs[i].getBoundingClientRect();
    const to = tabs[Math.min(i + 1, last)].getBoundingClientRect();
    const left = from.left + (to.left - from.left) * f - bar.getBoundingClientRect().left;
    ink.style.width = `${from.width + (to.width - from.width) * f}px`;
    ink.style.transform = `translateX(${left}px)`;
  }

  /** The tab bar scrolls sideways when the tabs are wider than the screen: show the active tab. */
  private revealTab(): void {
    const bar = this.tabBar()?.nativeElement;
    const strip = bar?.querySelector<HTMLElement>('[role="tablist"]');
    const tab = strip?.querySelectorAll<HTMLElement>('[role="tab"]')[this.phoneColumn()];
    if (!strip || !tab) return;
    // The strip runs to the screen edges; a tab counts as shown inside the gutter.
    const pad = parseFloat(getComputedStyle(strip).paddingLeft) || 0;
    const s = strip.getBoundingClientRect();
    const t = tab.getBoundingClientRect();
    const start = s.left + pad;
    const end = s.right - pad;
    const by = t.left < start ? t.left - start : t.right > end ? t.right - end : 0;
    if (by) strip.scrollBy({ left: by });
  }

  /** The pager position in pages: 1.5 is half way from the second page to the third. */
  private pagerPos(): number | null {
    const el = this.pager()?.nativeElement;
    return el?.clientWidth ? Math.abs(el.scrollLeft) / el.clientWidth : null;
  }
}
