import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * The quiet arrow of a row (spec 001962). Without `open` it points right at the end of a row
 * that opens a page or a detail, and it pulls into the end padding of the row by `--space-2`,
 * so the arrow lines up with the edge of the list. With `open` it is the arrow of a row that
 * opens in place (a position, a history entry): it points down and turns up while the row is
 * open. The arrow is decorative: the row names its target or carries `aria-expanded`.
 *
 * ```html
 * <span trail class="x__trail">
 *   …
 *   @if (!split()) {
 *     <app-row-chevron />
 *   }
 * </span>
 *
 * <button type="button" [attr.aria-expanded]="open()" (click)="toggle()">
 *   <app-row-chevron [open]="open()" />
 *   …
 * </button>
 * ```
 */
@Component({
  selector: 'app-row-chevron',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    'aria-hidden': 'true',
    '[class.rch--expand]': 'open() !== null',
    '[class.rch--open]': 'open() === true',
  },
  templateUrl: './row-chevron.component.html',
  styleUrl: './row-chevron.component.scss',
})
export class RowChevronComponent {
  /** The size of the arrow in px. */
  readonly size = input(17);
  /** Whether the row is open, for a row that opens in place; `null` for a row that opens a page. */
  readonly open = input<boolean | null>(null);
}
