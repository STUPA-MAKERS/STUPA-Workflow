import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AvatarStackComponent } from '@shared/ui/avatar/avatar.component';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * The people of a to-do card: up to three small avatars, or an empty circle with a person
 * icon that is named "Niemand zuständig". The host has no box.
 *
 * ```html
 * <app-todo-assignees [names]="row.names" [ids]="row.ids" />
 * ```
 */
@Component({
  selector: 'app-todo-assignees',
  standalone: true,
  imports: [AvatarStackComponent, IconComponent, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './todo-assignees.component.html',
  styleUrl: './todo-assignees.component.scss',
})
export class TodoAssigneesComponent {
  /** The names of the people, in order. */
  readonly names = input.required<readonly string[]>();
  /** The principal ids of the people, in the order of `names`. */
  readonly ids = input.required<readonly (string | null)[]>();
}
