import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** The side of a transfer that a leg shows. */
export type TransferLegDirection = 'out' | 'in';

/**
 * One booking of a transfer as a card: the kind ("Ausgabe auf" or "Einnahme auf"), the
 * cost centre, its path and the signed amount. The transfer detail and the preview of the
 * transfer form show two of these.
 *
 * The host is the card. `fit` sizes the amount with the width of the card, so a long
 * amount stays inside a narrow leg. Without it the amount has the fixed size `--fs-xl`.
 * Set `--leg-bg` (surface 2) for the card colour.
 *
 * ```html
 * <app-transfer-leg direction="out" [name]="cc.name" [color]="cc.color" [path]="cc.path"
 *                   [amount]="amount" fit />
 * ```
 */
@Component({
  selector: 'app-transfer-leg',
  standalone: true,
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './transfer-leg.component.html',
  styleUrl: './transfer-leg.component.scss',
  host: { '[class.tl--fit]': 'fit()' },
})
export class TransferLegComponent {
  /** `out`: the expense on the source. `in`: the income on the target. */
  readonly direction = input.required<TransferLegDirection>();
  /** The name of the cost centre. */
  readonly name = input.required<string>();
  /** The colour of the cost centre. `null`: no mark. */
  readonly color = input<string | null | undefined>(null);
  /** The path of the cost centre. */
  readonly path = input.required<string>();
  /** The formatted amount without a sign. */
  readonly amount = input.required<string>();
  /** The formatted amount that stays available after the booking. `null`: not shown. */
  readonly after = input<string | null | undefined>(null);
  /** Size the amount with the width of the card. */
  readonly fit = input(false, { transform: booleanAttribute });
}
