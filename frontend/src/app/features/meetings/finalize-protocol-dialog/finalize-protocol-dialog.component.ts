import {
  ChangeDetectionStrategy,
  Component,
  effect,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import { ButtonComponent, DialogComponent, SwitchComponent } from '@stupa-makers/ui-kit';

/**
 * "Protokoll finalisieren?" for a gremium that publishes its protocols.
 *
 * The finalize puts the public version on the public protocol page. The dialog says so,
 * reminds the reader that the free text must not name third persons, and offers to hold
 * this one protocol back ("Nicht veröffentlichen"). A protocol manager can publish it
 * later from the protocol bar. The page runs the finalize with the choice.
 */
@Component({
  selector: 'app-finalize-protocol-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, DialogComponent, NoteComponent, SwitchComponent],
  templateUrl: './finalize-protocol-dialog.component.html',
  styleUrl: './finalize-protocol-dialog.component.scss',
})
export class FinalizeProtocolDialogComponent {
  readonly open = input(false);
  /** The title of the meeting, as the subtitle of the dialog. */
  readonly meetingTitle = input('');
  readonly finalizing = input(false);

  readonly closed = output<void>();
  readonly confirmed = output<{ publicWithheld: boolean }>();

  /** "Nicht veröffentlichen". */
  protected readonly withheld = signal(false);

  constructor() {
    // Each opening starts with "publish": that is the rule of a public gremium.
    effect(() => {
      if (this.open()) untracked(() => this.withheld.set(false));
    });
  }

  protected cancel(): void {
    this.closed.emit();
  }

  protected confirm(): void {
    this.confirmed.emit({ publicWithheld: this.withheld() });
  }
}
