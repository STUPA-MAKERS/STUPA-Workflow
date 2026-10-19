import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  booleanAttribute,
  input,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CheckboxComponent, IconComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * The bar of a multiple selection: the count, the actions for the selected rows and a
 * button that clears the selection.
 *
 * Floating (the default), it sticks to the bottom of its container and is centred over
 * it, so it floats over the table it belongs to. It shows only while something is
 * selected.
 *
 * `inline` makes it a row in the flow of the page, on the selected surface, in the place
 * of the row it stands for. An inline bar shows while it is rendered, also at zero: the
 * page decides with `@if` when the selection mode starts and ends.
 *
 * `allSelected` (not null) puts a select-all box before the count; `selectAll` emits the
 * new value. The box shows the mixed state while some rows are selected.
 *
 * ```html
 * <app-selection-bar [count]="selected().length" (cleared)="clear()">
 *   <app-button variant="text" (click)="exportSelected()">Exportieren</app-button>
 * </app-selection-bar>
 * ```
 */
@Component({
  selector: 'app-selection-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CheckboxComponent, FormsModule, IconComponent, NgTemplateOutlet, TranslatePipe],
  templateUrl: './selection-bar.component.html',
  styleUrl: './selection-bar.component.scss',
  host: { '[class.selbar--inline]': 'inline()' },
})
export class SelectionBarComponent {
  /** How many rows are selected. A floating bar hides at zero. */
  readonly count = input.required<number>();
  /**
   * The count as the page words it. Without it, the bar shows "3 ausgewählt"
   * (`ui.selection.count`).
   */
  readonly countLabel = input<string | null>(null);
  /** A row in the flow of the page instead of the floating bar. */
  readonly inline = input(false, { transform: booleanAttribute });
  /** Every row is selected. Null (the default) shows no select-all box. */
  readonly allSelected = input<boolean | null>(null);
  /** The name of the select-all box. Default "Alle wählen" (`ui.selection.selectAll`). */
  readonly selectAllLabel = input<string | null>(null);
  /**
   * The name of the clear button, when it does more than clear (it ends a selection
   * mode). Default "Auswahl aufheben" (`ui.selection.clear`).
   */
  readonly clearLabel = input<string | null>(null);

  /** The clear button was pressed. */
  readonly cleared = output<void>();
  /** The select-all box was toggled: true selects every row, false none. */
  readonly selectAll = output<boolean>();
}
