import { booleanAttribute, ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * The sum under a list of bookings: "Summe der Unterbuchungen   1.250,00 €".
 *
 * Quiet small text; the amount in the text colour. `strong` sets the whole line in the
 * text colour and the semibold weight (the sum of a bulk action), `quiet` keeps the
 * amount quiet too (the sum in a form).
 */
@Component({
  selector: 'app-sum-row',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.sum--strong]': 'strong()', '[class.sum--quiet]': 'quiet()' },
  templateUrl: './sum-row.component.html',
  styleUrl: './sum-row.component.scss',
})
export class SumRowComponent {
  readonly label = input.required<string>();
  readonly amount = input.required<string>();
  readonly strong = input(false, { transform: booleanAttribute });
  readonly quiet = input(false, { transform: booleanAttribute });
}
