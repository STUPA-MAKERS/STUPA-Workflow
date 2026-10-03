import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * The floating bar of a multiple selection: the count, the actions for the selected
 * rows and a button that clears the selection.
 *
 * It sticks to the bottom of its container and is centred over it, so it floats over the
 * table it belongs to. It shows only while something is selected.
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
  imports: [IconComponent, TranslatePipe],
  templateUrl: './selection-bar.component.html',
  styleUrl: './selection-bar.component.scss',
})
export class SelectionBarComponent {
  /** How many rows are selected. The bar hides at zero. */
  readonly count = input.required<number>();
  /**
   * The count as the page words it. Without it, the bar shows "3 ausgewählt"
   * (`ui.selection.count`).
   */
  readonly countLabel = input<string | null>(null);

  /** The clear button was pressed. */
  readonly cleared = output<void>();
}
