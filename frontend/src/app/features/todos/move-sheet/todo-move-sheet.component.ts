import { ChangeDetectionStrategy, Component, computed, effect, inject, input, model, output, signal, untracked } from '@angular/core';
import type { Uuid } from '@core/api/models';
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

/** The choice of the sheet: the column and the end of it. */
export interface MoveChoice {
  columnId: Uuid;
  position: 'top' | 'bottom';
}

/**
 * "Verschieben" (frame 14): the phone moves a card with this bottom sheet instead of a
 * drag. The columns as a radio list with their counts, the place in the column as a
 * segmented control (Oben | Unten), then "Verschieben".
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
  /** The title of the card, as the line under the heading. */
  readonly cardTitle = input('');
  readonly moved = output<MoveChoice>();

  readonly columnId = signal<Uuid | null>(null);
  readonly position = signal<'top' | 'bottom'>('top');

  readonly positions = computed<SegmentedOption[]>(() => [
    { value: 'top', label: this.i18n.translate('todos.move.top') },
    { value: 'bottom', label: this.i18n.translate('todos.move.bottom') },
  ]);

  constructor() {
    // Each opening starts on the column of the card.
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
}
