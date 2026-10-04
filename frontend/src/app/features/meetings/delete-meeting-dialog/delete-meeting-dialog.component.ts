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
import type { Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { errorCode, errorDetail } from '../meetings-display.util';

/**
 * "Sitzung löschen": the confirmation before a meeting goes for good.
 *
 * The text names what goes with the meeting: the agenda, the attendance and the
 * delegations, and the protocol once the meeting has one. The server refuses the
 * delete while a vote is open (409 `open_vote`) and, for a final protocol, without
 * `meeting.delete_finalized` (403).
 */
@Component({
  selector: 'app-delete-meeting-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DialogComponent, ButtonComponent, IconComponent],
  templateUrl: './delete-meeting-dialog.component.html',
  styleUrl: './delete-meeting-dialog.component.scss',
})
export class DeleteMeetingDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The meeting to delete. The dialog is open while it is set. */
  readonly meeting = input<Meeting | null>(null);
  readonly closed = output<void>();
  /** The server deleted the meeting. Carries its id. */
  readonly deleted = output<Uuid>();

  readonly deleting = signal(false);

  /** A planned meeting has no protocol yet. A live or closed one has. */
  readonly bodyKey = computed<TranslationKey>(() =>
    this.meeting()?.protocolId ? 'meetings.delete.bodyProtocol' : 'meetings.delete.body',
  );

  constructor() {
    effect(() => {
      if (this.meeting()) untracked(() => this.deleting.set(false));
    });
  }

  cancel(): void {
    this.closed.emit();
  }

  confirm(): void {
    const m = this.meeting();
    if (!m || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteMeeting(m.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.toast.success(this.i18n.translate('meetings.toast.deleted'));
        this.deleted.emit(m.id);
      },
      error: (err: unknown) => {
        this.deleting.set(false);
        if (errorCode(err) === 'open_vote') {
          this.toast.error(this.i18n.translate('meetings.toast.closeOpenVote'));
          return;
        }
        const detail = errorDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.error(detail ? `${base}: ${detail}` : base);
      },
    });
  }
}
