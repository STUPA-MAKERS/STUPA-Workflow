import { CdkDrag, CdkDragPlaceholder, CdkDropList, CdkDropListGroup, type CdkDragDrop } from '@angular/cdk/drag-drop';
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
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { ButtonComponent, IconComponent, TabsComponent, type TabItem } from '@stupa-makers/ui-kit';
import { TodoCardTileComponent } from '../../../features/todos/card-tile/todo-card-tile.component';
import { moveRequest, sortedColumns } from '../../../features/todos/todos.util';

/** The done column shows this many cards until "n weitere" opens the rest. */
export const DONE_PREVIEW = 3;

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
 * columns, Space or Enter put it down, Escape puts it back. A live region names each
 * step for a screen reader.
 *
 * The done column shows its newest cards and "n weitere · Archiv". Each column ends
 * with "+ To-Do", which opens a quick field for a title.
 *
 * Phone: one column at a time behind tabs with the counts; no drag (the card moves with
 * "Verschieben" in its detail).
 */
@Component({
  selector: 'app-todo-board-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CdkDrag,
    CdkDragPlaceholder,
    CdkDropList,
    CdkDropListGroup,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    RowMenuComponent,
    TabsComponent,
    TodoCardTileComponent,
  ],
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

  readonly openCard = output<Uuid>();
  readonly moveCard = output<BoardMove>();
  readonly quickAdd = output<{ columnId: Uuid; title: string }>();
  readonly addIn = output<Uuid>();
  readonly settings = output<void>();
  readonly archive = output<void>();

  readonly columns = computed(() => sortedColumns(this.board().columns));
  readonly canWrite = computed(() => this.board().canWrite);

  /** Done columns opened past the preview. */
  readonly expanded = signal<ReadonlySet<Uuid>>(new Set());
  readonly adding = signal<Uuid | null>(null);
  readonly draft = signal('');
  readonly kb = signal<KeyDrag | null>(null);
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

  count(col: TodoColumn): number {
    return this.cards().get(col.id)?.length ?? 0;
  }

  more(col: TodoColumn): number {
    return this.count(col) - (this.shown().get(col.id)?.length ?? 0);
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
    if (!held) return;
    target.splice(event.currentIndex, 0, held);
    this.moveCard.emit({ cardId, move: moveRequest(target, event.currentIndex, toCol) });
  }

  // ------------------------------------------------------------------ keyboard drag

  onTileKey(event: KeyboardEvent, card: TodoCardTile, colIndex: number, index: number): void {
    if (!this.canWrite() || this.phone()) return;
    const kb = this.kb();
    if (!kb) {
      if (event.key !== ' ') return;
      event.preventDefault();
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
        this.commit(card);
        return;
      case 'Escape':
      case 'Tab':
        if (event.key === 'Escape') event.preventDefault();
        this.kb.set(null);
        this.say('todos.drag.cancelled', card);
        this.refocus(card.id);
        return;
      default:
        return;
    }
    this.say('todos.drag.moved', card);
    this.refocus(card.id);
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

  selectPhoneColumn(id: string | null): void {
    const i = this.columns().findIndex((c) => c.id === id);
    if (i >= 0) this.phoneColumn.set(i);
  }
}
