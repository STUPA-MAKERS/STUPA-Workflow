import { ChangeDetectionStrategy, Component, input, model, output } from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { TodoBoardKind, TodoCardTile, TodoColumn } from '@core/api/todos.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { IconComponent } from '@stupa-makers/ui-kit';

/** A long press on a tile asks for its menu: the card, its board and the columns in order. */
export interface TileMenuRequest {
  card: TodoCardTile;
  boardId: Uuid;
  boardKind: TodoBoardKind;
  columns: readonly TodoColumn[];
}

/**
 * "Verschieben" of the phone: the bottom sheet that a long press on a tile opens. It lists
 * the columns of the board of the card; the column of the card has the check and is not a
 * choice. A tap on another column emits `column` (the page moves the card to the end of
 * it). Below a line, "In anderes Board verschieben" emits `transfer` (the page opens the
 * transfer dialog). Each choice closes the sheet first.
 */
@Component({
  selector: 'app-todo-tile-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent, SideSheetComponent],
  templateUrl: './todo-tile-menu.component.html',
  styleUrl: './todo-tile-menu.component.scss',
})
export class TodoTileMenuComponent {
  readonly open = model(false);
  readonly request = input<TileMenuRequest | null>(null);

  /** A column was picked: the id of the column. */
  readonly column = output<Uuid>();
  /** "In anderes Board verschieben" was picked. */
  readonly transfer = output<void>();

  pick(col: TodoColumn): void {
    if (col.id === this.request()?.card.columnId) return;
    this.open.set(false);
    this.column.emit(col.id);
  }

  moveOn(): void {
    this.open.set(false);
    this.transfer.emit();
  }
}
