import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { errorCode, errorDetail } from '../meetings-display.util';

/**
 * "Sitzung schließen?": the last step of a live meeting.
 *
 * The close is final and freezes the attendance. The checklist says what the close
 * needs and does (O12, O13):
 *
 * - No vote of the meeting may be open. The server refuses the close with 409
 *   `open_vote` otherwise, and the dialog then shows that reason in the list.
 * - The close cancels the planned (draft) votes of the meeting.
 * - The close does NOT finalize the protocol. Finalizing is a step of its own, for a
 *   holder of the Gremium right `protocol.finalize`.
 */
@Component({
  selector: 'app-close-meeting-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DialogComponent, ButtonComponent, IconComponent, NoteComponent],
  templateUrl: './close-meeting-dialog.component.html',
  styleUrl: './close-meeting-dialog.component.scss',
})
export class CloseMeetingDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly open = input(false);
  readonly meeting = input.required<Meeting>();
  readonly closed = output<void>();
  /** The server closed the meeting. Carries the closed meeting. */
  readonly meetingClosed = output<Meeting>();

  readonly closing = signal(false);
  /** The server refused the close because a vote is open (409 `open_vote`). */
  readonly refused = signal(false);

  /** A vote of the meeting is open, as far as this page knows. */
  readonly openVote = computed(
    () => this.refused() || this.meeting().votes.some((v) => v.status === 'open'),
  );
  /** The meeting has planned votes, which the close cancels. */
  readonly hasDrafts = computed(() => this.meeting().votes.some((v) => v.status === 'pending'));

  constructor() {
    effect(() => {
      if (this.open()) {
        untracked(() => {
          this.closing.set(false);
          this.refused.set(false);
        });
      }
    });
  }

  cancel(): void {
    this.closed.emit();
  }

  confirm(): void {
    const m = this.meeting();
    if (m.status !== 'live' || this.closing() || this.openVote()) return;
    this.closing.set(true);
    this.api.patchMeeting(m.id, { status: 'closed' }).subscribe({
      next: (updated) => {
        this.closing.set(false);
        this.toast.success(this.i18n.translate('meetings.toast.closed'));
        this.meetingClosed.emit(updated);
      },
      error: (err: unknown) => {
        this.closing.set(false);
        if (errorCode(err) === 'open_vote') {
          // The vote opened in another tab after this page loaded.
          this.refused.set(true);
          return;
        }
        const detail = errorDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.error(detail ? `${base}: ${detail}` : base);
      },
    });
  }
}
