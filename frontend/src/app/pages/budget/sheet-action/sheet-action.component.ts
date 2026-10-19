import { ChangeDetectionStrategy, Component, booleanAttribute, input, output } from '@angular/core';
import { ButtonComponent, IconComponent, type IconName } from '@stupa-makers/ui-kit';

/**
 * The main action in the head of a finance detail, such as "Bearbeiten". On a phone it is a
 * small tonal button with the icon and the text. Otherwise it is an icon button that has
 * `title` as its name and tooltip. The host has no box, so the button sits in the sheet bar.
 *
 * ```html
 * <app-sheet-action icon="edit" [label]="'action.edit' | t" [ariaLabel]="'expenses.edit' | t"
 *                   [phone]="phone()" (pressed)="edit.emit(e)" />
 * ```
 */
@Component({
  selector: 'app-sheet-action',
  standalone: true,
  imports: [ButtonComponent, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sheet-action.component.html',
  styleUrl: './sheet-action.component.scss',
})
export class SheetActionComponent {
  /** The icon of the action. */
  readonly icon = input.required<IconName>();
  /** The short text of the phone button. */
  readonly label = input.required<string>();
  /** The name and tooltip of the icon button. */
  readonly ariaLabel = input.required<string>();
  /** Show the phone button with text. */
  readonly phone = input(false, { transform: booleanAttribute });
  /** The person pressed the button. */
  readonly pressed = output<void>();
}
