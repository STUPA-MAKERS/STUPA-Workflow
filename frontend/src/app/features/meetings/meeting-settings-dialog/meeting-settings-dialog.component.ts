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
import type { Attendance, Meeting } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import {
  ButtonComponent,
  DatepickerComponent,
  DialogComponent,
  SelectComponent,
  TimeInputComponent,
  ToastService,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { errorCode, errorDetail } from '../meetings-display.util';

/**
 * "Sitzung bearbeiten": the minute-taker, the date, the start and the end of a meeting.
 *
 * The dialog opens from a list row and from the meeting page. A closed meeting locks
 * every field, and a final protocol also locks the minute-taker; the server refuses
 * both with 409. Only a member with `protocol.write` can keep the minutes (O20), so the
 * list offers those members plus the current minute-taker. While the meeting is live a
 * new minute-taker is a handover "now" (Z3).
 */
@Component({
  selector: 'app-meeting-settings-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    SelectComponent,
    DatepickerComponent,
    TimeInputComponent,
    NoteComponent,
  ],
  templateUrl: './meeting-settings-dialog.component.html',
  styleUrl: './meeting-settings-dialog.component.scss',
})
export class MeetingSettingsDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The meeting to edit. The dialog is open while it is set. */
  readonly meeting = input<Meeting | null>(null);
  /** The protocol of the meeting is final: the minute-taker stays as it is. */
  readonly protocolFinal = input(false);
  readonly closed = output<void>();
  /** The server saved the change. Carries the updated meeting. */
  readonly saved = output<Meeting>();

  readonly roster = signal<Attendance[]>([]);
  readonly keeper = signal('');
  readonly date = signal('');
  readonly time = signal('');
  readonly endTime = signal('');
  readonly saving = signal(false);

  /** A closed meeting locks every setting. */
  readonly locked = computed(() => this.meeting()?.status === 'closed');
  readonly keeperLocked = computed(() => this.locked() || this.protocolFinal());

  /** O20: members with `protocol.write`, and the current minute-taker. */
  readonly keeperOptions = computed<SelectOption[]>(() => {
    const current = this.meeting()?.protokollantId ?? null;
    return [
      { value: '', label: this.i18n.translate('meetings.protokollant.none') },
      ...this.roster()
        .filter((a) => a.canKeepProtocol || a.principalId === current)
        .map((a) => ({ value: a.principalId, label: a.displayName || a.email || a.principalId })),
    ];
  });

  readonly valid = computed(() => !!this.date().trim() && !!this.time().trim());

  constructor() {
    effect(() => {
      const m = this.meeting();
      if (m) untracked(() => this.load(m));
    });
  }

  private load(m: Meeting): void {
    this.keeper.set(m.protokollantId ?? '');
    this.date.set(m.date ?? '');
    this.time.set(m.startTime ?? '');
    this.endTime.set(m.endTime ?? '');
    this.saving.set(false);
    this.roster.set([]);
    this.api.listAttendance(m.id, { quiet: true }).subscribe({
      next: (rows) => {
        this.roster.set(rows);
        // Set the choice again once its option exists. Without this the native
        // <select> falls back to "nobody".
        this.keeper.set(m.protokollantId ?? '');
      },
      error: () => this.roster.set([]),
    });
  }

  cancel(): void {
    this.closed.emit();
  }

  /** Save the minute-taker, the date and the times in one PATCH. */
  save(): void {
    const m = this.meeting();
    if (!m || this.saving() || this.locked()) return;
    if (!this.valid()) {
      this.toast.error(this.i18n.translate('meetings.toast.dateTimeRequired'));
      return;
    }
    const end = this.endTime().trim();
    if (end && end <= this.time().trim()) {
      this.toast.error(this.i18n.translate('meetings.create.endBeforeStart'));
      return;
    }
    this.saving.set(true);
    this.api
      .patchMeeting(m.id, {
        // A final protocol locks the minute-taker: leave the field out, the server
        // would answer 409.
        ...(this.keeperLocked() ? {} : { protokollantId: this.keeper() || null }),
        date: this.date().trim(),
        startTime: this.time().trim(),
        endTime: end || null,
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.toast.success(this.i18n.translate('meetings.toast.settingsSaved'));
          this.saved.emit(updated);
        },
        error: (err: unknown) => {
          this.saving.set(false);
          if (errorCode(err) === 'protokollant_needs_protocol_write') {
            this.toast.error(this.i18n.translate('meetings.toast.needsProtocolWrite'));
            return;
          }
          const detail = errorDetail(err);
          const base = this.i18n.translate('meetings.toast.actionFailed');
          this.toast.error(detail ? `${base}: ${detail}` : base);
        },
      });
  }
}
