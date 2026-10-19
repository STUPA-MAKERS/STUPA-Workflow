import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';

/** Where an agenda item is in the meeting. */
export type TopBadgeState = 'todo' | 'now' | 'done';

/**
 * The round mark before an agenda item: its number, a check when it is done, or a lock for
 * a non-public item. The current item has the accent fill, a done item an accent ring.
 *
 * The host is the mark. Set `--tb-size` (2rem) for its diameter and `--tb-font` (0.75rem)
 * for the number, and `--tb-nums` (tabular-nums) for its digits. `decorative` hides the mark from assistive technology, for a row that
 * names its number and state in text of its own.
 *
 * ```html
 * <app-top-badge [number]="i + 1" [state]="done ? 'done' : 'todo'" decorative />
 * ```
 */
@Component({
  selector: 'app-top-badge',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './top-badge.component.html',
  styleUrl: './top-badge.component.scss',
  host: {
    '[class.tb--now]': "state() === 'now'",
    '[class.tb--done]': "state() === 'done'",
    '[attr.aria-hidden]': "decorative() ? 'true' : null",
  },
})
export class TopBadgeComponent {
  /** The number of the item. */
  readonly number = input.required<number | string>();
  /** Where the item is in the meeting. */
  readonly state = input<TopBadgeState>('todo');
  /** Show a lock instead of the number or the check. */
  readonly lock = input(false, { transform: booleanAttribute });
  /** The size of the check and the lock. */
  readonly iconSize = input(16);
  /** Hide the mark from assistive technology. */
  readonly decorative = input(false, { transform: booleanAttribute });
}
