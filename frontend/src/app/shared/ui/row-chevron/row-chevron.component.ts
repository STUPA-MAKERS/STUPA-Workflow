import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * The quiet arrow at the end of a row that opens a page or a detail. It pulls into the end
 * padding of the row by `--space-2`, so the arrow lines up with the edge of the list. The
 * arrow is decorative: the row names its target.
 *
 * ```html
 * <span trail class="x__trail">
 *   …
 *   @if (!split()) {
 *     <app-row-chevron />
 *   }
 * </span>
 * ```
 */
@Component({
  selector: 'app-row-chevron',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './row-chevron.component.html',
  styleUrl: './row-chevron.component.scss',
})
export class RowChevronComponent {
  /** The size of the arrow in px. */
  readonly size = input(17);
}
