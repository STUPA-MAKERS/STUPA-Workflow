import { booleanAttribute, ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';

/**
 * The foot of a form that replaces a detail sheet: "Löschen" at the start (`deletable`),
 * then "Abbrechen" and the main action of the page at the end.
 *
 * The host is the `footer` of the page, so the page keeps its frame rules. The page
 * projects its main button; in a phone sheet (`compact`) "Löschen" is an icon.
 *
 * ```html
 * <footer class="ff__foot" appPaneFormFoot [deletable]="mode() === 'edit'"
 *         [compact]="layout() === 'sheet'" (removed)="remove.emit()" (cancelled)="close()">
 *   <app-button variant="fill" (click)="submit($event)">Speichern</app-button>
 * </footer>
 * ```
 */
@Component({
  // eslint-disable-next-line @angular-eslint/component-selector -- the host is the footer of the page, which keeps its frame rules
  selector: 'footer[appPaneFormFoot]',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent],
  templateUrl: './pane-form-foot.component.html',
  styleUrl: './pane-form-foot.component.scss',
})
export class PaneFormFootComponent {
  /** Show "Löschen" (an edit, not a create). */
  readonly deletable = input(false, { transform: booleanAttribute });
  /** A phone sheet: "Löschen" is an icon. */
  readonly compact = input(false, { transform: booleanAttribute });
  /** "Löschen" was pressed. */
  readonly removed = output<void>();
  /** "Abbrechen" was pressed. */
  readonly cancelled = output<void>();
}
