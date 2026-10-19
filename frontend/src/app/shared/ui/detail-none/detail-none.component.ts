import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import type { IconName } from '@stupa-makers/ui-kit';
import { EmptyStateComponent } from '../empty-state/empty-state.component';

/**
 * What the list shows: `busy` while it loads or failed (the pane stays empty),
 * `empty` when it has no rows, `pick` when a row can be picked.
 */
export type DetailNoneState = 'busy' | 'empty' | 'pick';

/**
 * The detail pane of a list/detail page while no row is open: "Wähle einen Antrag aus."
 *
 * It fills the pane and centres the empty state. `empty` shows the text of an empty list
 * (`emptyHeading`, `emptyBody`, `emptyIcon`) in its place; `busy` shows nothing, so the
 * pane does not flash a text while the list loads. `ghost` shows bars in the shape of an
 * open sheet instead (a list that has no rows leaves a neutral sheet).
 *
 * The pane sits on the same sheet as an open row (`surface="sheet"`, with `inset`
 * padding), so it does not jump when a row opens. `surface="flat"` has no sheet.
 *
 * ```html
 * <app-detail-none [state]="state()" icon="vote" [heading]="'voting.list.none' | t"
 *   [emptyHeading]="'voting.list.empty' | t" />
 * ```
 */
@Component({
  selector: 'app-detail-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [EmptyStateComponent],
  host: {
    '[class.dn--sheet]': "surface() === 'sheet'",
    '[class.dn--inset]': 'inset()',
  },
  templateUrl: './detail-none.component.html',
  styleUrl: './detail-none.component.scss',
})
export class DetailNoneComponent {
  readonly state = input<DetailNoneState>('pick');
  /** The icon of the `pick` text. */
  readonly icon = input<IconName>('file');
  readonly heading = input<string>('');
  readonly body = input<string | null>(null);
  /** The icon of the `empty` text. Default: `icon`. */
  readonly emptyIcon = input<IconName | null>(null);
  readonly emptyHeading = input<string>('');
  readonly emptyBody = input<string | null>(null);
  /** Bars in the shape of an open sheet in place of the text. */
  readonly ghost = input(false);
  /** `sheet`: the surface of an open row. `flat`: no surface of its own. */
  readonly surface = input<'sheet' | 'flat'>('sheet');
  /** The padding of the sheet around the empty state. */
  readonly inset = input(true);
}
