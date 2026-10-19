import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import type { DueInfo } from '../todos.util';

/**
 * The due date of a to-do card: a calendar icon, the short date and the note ("überfällig",
 * "heute", "morgen"). An overdue date is red and a close one amber, both semibold. The host
 * is the line. The page sets the type size on it, and the quiet colour as `--tdu-color`
 * (default: the colour of the line).
 *
 * ```html
 * <app-todo-due class="tt__fact" [due]="due" />
 * ```
 */
@Component({
  selector: 'app-todo-due',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './todo-due.component.html',
  styleUrl: './todo-due.component.scss',
  host: {
    '[class.tdu--overdue]': "due().tone === 'overdue'",
    '[class.tdu--soon]': "due().tone === 'soon'",
  },
})
export class TodoDueComponent {
  /** The due date as `dueInfo` gives it. */
  readonly due = input.required<DueInfo>();
}
