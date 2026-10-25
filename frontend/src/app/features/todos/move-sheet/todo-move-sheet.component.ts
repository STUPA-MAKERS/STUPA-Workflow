import { ChangeDetectionStrategy, Component, computed, effect, inject, input, model, output, signal, untracked } from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { TodoBoardKind, TodoCardTile, TodoColumn } from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  IconComponent,
  SegmentedComponent,
  type SegmentedOption,
  SideSheetComponent,
} from '@stupa-makers/ui-kit';

/** A column of the sheet; `count` is the number of cards when the board is known. */
export interface MoveColumn {
  id: Uuid;
  name: string;
  count?: number | null;
}

/** A long press on a tile asks for its sheet: the card, its board and the columns in order. */
export interface TileMenuRequest {
  card: TodoCardTile;
  boardId: Uuid;
  boardKind: TodoBoardKind;
  columns: readonly TodoColumn[];
}

/** The choice of the sheet: the column and the end of it. */
export interface MoveChoice {
  columnId: Uuid;
  position: 'top' | 'bottom';
}

/**
 * "Verschieben": the phone moves a card with this bottom sheet instead of a
 * drag. The card detail and a long press on a tile open the same sheet. The columns as a
 * radio list with their counts, the place in the column as a segmented control
 * (Oben | Unten), then "Verschieben". With `canTransfer`, a row below the columns, "In
 * anderes Board verschieben", closes the sheet and emits `transfer` (the host opens the
 * transfer dialog). A close without a choice (Escape, the scrim, the close button) emits
 * `dismissed`.
 */
@Component({
  selector: 'app-todo-move-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent, SegmentedComponent, SideSheetComponent],
  templateUrl: './todo-move-sheet.component.html',
  styleUrl: './todo-move-sheet.component.scss',
})
export class TodoMoveSheetComponent {
  private readonly i18n = inject(I18nService);

  readonly open = model(false);
  readonly columns = input<readonly MoveColumn[]>([]);
  /** The column the card is in now. */
  readonly current = input<Uuid | null>(null);
  /** Show "In anderes Board verschieben". */
  readonly canTransfer = input(false);
  readonly moved = output<MoveChoice>();
  /** "In anderes Board verschieben" was picked. */
  readonly transfer = output<void>();
  /** The sheet closed without a choice. */
  readonly dismissed = output<void>();

  readonly columnId = signal<Uuid | null>(null);
  readonly position = signal<'top' | 'bottom'>('top');

  readonly positions = computed<SegmentedOption[]>(() => [
    { value: 'top', label: this.i18n.translate('todos.move.top') },
    { value: 'bottom', label: this.i18n.translate('todos.move.bottom') },
  ]);

  constructor() {
    effect(() => {
      if (!this.open()) return;
      untracked(() => {
        this.columnId.set(this.current());
        this.position.set('top');
      });
    });
  }

  setPosition(value: string | null): void {
    this.position.set(value === 'bottom' ? 'bottom' : 'top');
  }

  confirm(): void {
    const columnId = this.columnId();
    if (!columnId) return;
    this.open.set(false);
    this.moved.emit({ columnId, position: this.position() });
  }

  moveOn(): void {
    this.open.set(false);
    this.transfer.emit();
  }
}
