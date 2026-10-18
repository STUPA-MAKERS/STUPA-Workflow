import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, DialogComponent } from '@stupa-makers/ui-kit';

/**
 * The one confirmation before a destructive action: a title ("Antrag löschen?"), one
 * text that names the object and says that the step is final, and the footer
 * "Abbrechen" and the confirm button ("Löschen" unless `confirmLabel` says otherwise).
 *
 * The page keeps the state: it opens the dialog, runs the action on `confirm` and
 * closes the dialog when the action is done. `cancel` comes from "Abbrechen", the X,
 * Escape and the backdrop. While `busy`, the confirm button shows the spinner and a
 * second click does nothing. `disabled` blocks the confirm, for example while a note
 * in the content says why the object cannot go.
 *
 * Content between the tags (a note, an error) shows below the text.
 */
@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, DialogComponent, TranslatePipe],
  templateUrl: './confirm-dialog.component.html',
  styleUrl: './confirm-dialog.component.scss',
})
export class ConfirmDialogComponent {
  readonly open = input(false);
  readonly title = input.required<string>();
  /** A line below the title that names the object, for example an e-mail address. */
  readonly subtitle = input('');
  /** The text: what goes and that it is final. Empty: no text. */
  readonly body = input('');
  /** The label of the confirm button. Empty: "Löschen". */
  readonly confirmLabel = input('');
  /** The confirm button in the danger look; `false` gives the fill look. */
  readonly danger = input(true);
  readonly busy = input(false);
  readonly disabled = input(false);

  readonly confirm = output<void>();
  readonly cancel = output<void>();

  protected onConfirm(): void {
    if (this.busy() || this.disabled()) return;
    this.confirm.emit();
  }
}
