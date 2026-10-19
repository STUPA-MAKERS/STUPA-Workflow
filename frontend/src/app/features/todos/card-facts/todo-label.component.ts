import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import type { TodoLabel } from '@core/api/todos.service';

/**
 * A label of a to-do card: a dot in the label colour, then the name. The host has no box,
 * so the page sets the type size and the colour of the name on it.
 *
 * ```html
 * <app-todo-label class="lv__label" [label]="label" />
 * ```
 */
@Component({
  selector: 'app-todo-label',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './todo-label.component.html',
  styleUrl: './todo-label.component.scss',
})
export class TodoLabelComponent {
  /** The label. */
  readonly label = input.required<TodoLabel>();
}
