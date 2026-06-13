import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Min/Max- bzw. Von/Bis-Bereich im Filter-Popover: zwei projizierte Controls mit
 * einem Trenner dazwischen. Slots: `[start]` und `[end]`.
 *
 * ```html
 * <app-filter-range>
 *   <input start type="date" … />
 *   <input end type="date" … />
 * </app-filter-range>
 * ```
 */
@Component({
  selector: 'app-filter-range',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './filter-range.component.html',
  styleUrl: './filter-range.component.scss',
})
export class FilterRangeComponent {
  /** Trennzeichen zwischen den beiden Controls. */
  readonly separator = input('–');
}
