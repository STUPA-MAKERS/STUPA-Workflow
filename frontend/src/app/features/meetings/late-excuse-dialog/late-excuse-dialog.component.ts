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
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { Attendance, Uuid } from '@core/api/models';
import { problemCode } from '@core/api/problem';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  DialogComponent,
  TextareaComponent,
  ToastService,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';

/** The longest reason that the server accepts (`ATTENDANCE_NOTE_MAX`). */
export const LATE_EXCUSE_NOTE_MAX = 500;

/** The refusals that a second try cannot change, with their text. */
const FINAL_REFUSALS: Readonly<Record<string, TranslationKey>> = {
  late_excuse_expired: 'meetings.lateExcuse.expired',
  not_absent: 'meetings.lateExcuse.notAbsent',
};

/**
 * "Nachträglich entschuldigen": a member changes the own absence of a closed meeting to
 * an excuse (§ 000922).
 *
 * The dialog is open while `meetingId` is set. The reason is required. The server
 * refuses after the period `lateExcuseDays` (409 `late_excuse_expired`) and when the
 * record is no absence (409 `not_absent`); the toast then names the cause and the
 * dialog closes, because a second try gets the same answer.
 */
@Component({
  selector: 'app-late-excuse-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    TextareaComponent,
  ],
  templateUrl: './late-excuse-dialog.component.html',
})
export class LateExcuseDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The meeting of the absence. The dialog is open while it is set. */
  readonly meetingId = input<Uuid | null>(null);
  readonly closed = output<void>();
  /** The server stored the excuse. Carries the new roster of the meeting. */
  readonly excused = output<Attendance[]>();

  readonly note = signal('');
  readonly saving = signal(false);
  readonly tooLong = computed(() => this.note().trim().length > LATE_EXCUSE_NOTE_MAX);
  readonly valid = computed(() => !!this.note().trim() && !this.tooLong());
  /** The field takes no longer reason, so the limit needs no error text. */
  protected readonly max = LATE_EXCUSE_NOTE_MAX;

  constructor() {
    effect(() => {
      if (this.meetingId()) untracked(() => this.reset());
    });
  }

  private reset(): void {
    this.note.set('');
    this.saving.set(false);
  }

  cancel(): void {
    this.closed.emit();
  }

  save(): void {
    const id = this.meetingId();
    if (!id || !this.valid() || this.saving()) return;
    this.saving.set(true);
    this.api.excuseLate(id, this.note().trim()).subscribe({
      next: (roster) => {
        this.saving.set(false);
        this.toast.show(this.i18n.translate('meetings.lateExcuse.saved'), 'success');
        this.excused.emit(roster);
      },
      error: (err: unknown) => {
        this.saving.set(false);
        const code = problemCode(err);
        const final = FINAL_REFUSALS[code ?? ''];
        this.toast.show(this.i18n.translate(final ?? 'meetings.toast.actionFailed'), 'error');
        if (final) this.closed.emit();
      },
    });
  }
}
