import { booleanAttribute, ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * One booking in a list of a sheet: a sub-booking of a booking, a booking of a bulk
 * action. The title, a quiet meta line, the signed amount, and a slot at the end (a row
 * menu).
 *
 * The host is the row (`role="listitem"`), so it takes the surface of its `.rowgroup`.
 * The page projects the meta line with the `meta` attribute and the end with no
 * attribute:
 *
 * ```html
 * <div class="rowgroup" role="list">
 *   <app-booking-row mark [title]="s.description" [amount]="signed(s)">
 *     <span meta>…</span>
 *     <app-row-menu … />
 *   </app-booking-row>
 * </div>
 * ```
 *
 * `mark` puts "↳" before a sub-booking. `plain` is the row of a form: the title in the
 * normal weight with the mark in it, the amount in the size of the form.
 */
@Component({
  selector: 'app-booking-row',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { role: 'listitem', '[class.bkr--plain]': 'plain()' },
  templateUrl: './booking-row.component.html',
  styleUrl: './booking-row.component.scss',
})
export class BookingRowComponent {
  readonly title = input.required<string>();
  /** The signed amount, formatted. */
  readonly amount = input.required<string>();
  /** A sub-booking: "↳" before the title. */
  readonly mark = input(false, { transform: booleanAttribute });
  /** The row of a form. */
  readonly plain = input(false, { transform: booleanAttribute });
}
