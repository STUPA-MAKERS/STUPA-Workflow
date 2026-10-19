import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** How the approved and the requested amount sit: one over the other, or in one line. */
export type AmountLayout = 'stack' | 'inline';

/**
 * The amount of an application. With an approved amount, it shows the approved amount and
 * the requested amount struck through. Without one, it shows the requested amount. Without
 * either, it shows nothing.
 *
 * `stack` puts the struck amount under the approved one, right-aligned, in the small type of
 * a list row. `inline` puts it after the approved one in the type of the line, and marks the
 * approved amount in the accent colour. The host has no box.
 *
 * ```html
 * <app-amount [amount]="row.amount" [approved]="row.approved" layout="stack" />
 * ```
 */
@Component({
  selector: 'app-amount',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './amount.component.html',
  styleUrl: './amount.component.scss',
})
export class AmountComponent {
  /** The formatted requested amount. `null`: no amount. */
  readonly amount = input<string | null | undefined>(null);
  /** The formatted approved amount, set only when it differs from the requested one. */
  readonly approved = input<string | null | undefined>(null);
  /** One over the other (`stack`) or in one line (`inline`). */
  readonly layout = input<AmountLayout>('inline');
}
