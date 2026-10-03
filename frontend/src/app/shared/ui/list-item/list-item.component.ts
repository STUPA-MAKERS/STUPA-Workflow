import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';

/**
 * One row of a list: a lead, a title with a sub line, and a trailing slot.
 *
 * The whole row is the target, but only the title is the control: a link when `link` is
 * set, else a button that emits `activate`. The control stretches over the row, so a
 * click anywhere on the row opens it. Enter (and Space for the button) open it from the
 * keyboard. Controls in the trailing slot (a row menu, a delete button) sit above the
 * stretched area and keep their own click.
 *
 * The title is one line with an ellipsis and always carries the full text as `title`.
 *
 * ```html
 * <app-list-item [title]="a.title" [selected]="a.id === selectedId()" (activate)="open(a)">
 *   <span sub><app-status-text kind="warn">In Prüfung</app-status-text> · Förderantrag</span>
 *   <span trail class="mono">1.250,00 €</span>
 * </app-list-item>
 * ```
 *
 * Slots: `[lead]` (an avatar for a person, an icon or a date block; never initials for a
 * thing), `[sub]` and `[trail]`.
 */
@Component({
  selector: 'app-list-item',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  templateUrl: './list-item.component.html',
  styleUrl: './list-item.component.scss',
})
export class ListItemComponent {
  /** The name of the thing. Shown on one line; the full text is in the `title` attribute. */
  readonly title = input.required<string>();
  /** A plain sub line. Use the `[sub]` slot for a sub line with a status or markup. */
  readonly sub = input<string | null>(null);
  /** A router link. Without it the title is a button that emits `activate`. */
  readonly link = input<string | readonly unknown[] | null>(null);
  /** The row is the one open in the detail pane. */
  readonly selected = input(false);

  /** The row was opened by a click, Enter or Space. Also emitted for a link. */
  readonly activate = output<void>();
}
