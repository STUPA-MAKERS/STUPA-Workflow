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
import type { Attendance, GuestsMode, JoinLink, Meeting } from '@core/api/models';
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
import { MeetingGuestsService } from '../meeting-guests.service';
import { PublicJoinSettingsComponent } from '../public-join/public-join-settings.component';

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
    PublicJoinSettingsComponent,
  ],
  templateUrl: './meeting-settings-dialog.component.html',
  styleUrl: './meeting-settings-dialog.component.scss',
})
export class MeetingSettingsDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly guestsSvc = inject(MeetingGuestsService, { optional: true });

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
  /** Public participation (#17): the switch, the mode and the join link. */
  readonly publicJoin = signal(false);
  readonly guestsMode = signal<GuestsMode>('vote');
  readonly link = signal<JoinLink | null>(null);
  readonly rotating = signal(false);
  /** The confirmation before the public participation goes off in a live meeting. */
  readonly confirmOff = signal(false);

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
        .map((a) => ({
          value: a.principalId,
          label: a.displayName || a.email || this.i18n.translate('common.unnamed'),
        })),
    ];
  });

  /** Only the meeting lead (`canManage`) changes the public participation. */
  readonly publicLocked = computed(() => this.locked() || !this.meeting()?.canManage);
  /** The counts that the confirmation names: open requests and admitted guests. */
  readonly offCounts = computed(() => ({
    pending: this.meeting()?.pendingGuests ?? 0,
    admitted: this.meeting()?.admittedGuests ?? 0,
  }));

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
    this.publicJoin.set(m.publicJoin);
    this.guestsMode.set(m.guestsMode);
    this.link.set(null);
    this.rotating.set(false);
    this.confirmOff.set(false);
    if (m.publicJoin && m.canManage) this.loadLink(m);
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

  private loadLink(m: Meeting): void {
    this.api.getJoinLink(m.id).subscribe({
      next: (link) => {
        if (this.meeting()?.id === m.id) this.link.set(link);
      },
      error: () => {},
    });
  }

  /**
   * The switch. Off in a live meeting with requests or guests asks first: the requests
   * lapse and the guests leave. Cast votes stay counted.
   */
  setPublicJoin(on: boolean): void {
    const m = this.meeting();
    this.publicJoin.set(on);
    const { pending, admitted } = this.offCounts();
    if (!on && m?.status === 'live' && m.publicJoin && pending + admitted > 0) {
      this.confirmOff.set(true);
    }
  }

  /** "Abbrechen" of the confirmation: the participation stays on. */
  keepPublic(): void {
    this.confirmOff.set(false);
    this.publicJoin.set(true);
  }

  /** "Ausschalten": takes effect with "Speichern". */
  confirmPublicOff(): void {
    this.confirmOff.set(false);
  }

  /** "Neuen Link erzeugen": the old code stops working at once, open requests lapse. */
  rotate(): void {
    const m = this.meeting();
    if (!m || this.rotating()) return;
    this.rotating.set(true);
    this.api.rotateJoinCode(m.id).subscribe({
      next: (link) => {
        this.rotating.set(false);
        this.link.set(link);
        if (this.guestsSvc?.meetingId() === m.id) {
          this.guestsSvc.joinLink.set(link);
          this.guestsSvc.reload();
        }
        this.toast.success(this.i18n.translate('guests.toast.rotated'));
      },
      error: (err: unknown) => {
        this.rotating.set(false);
        const detail = errorDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.error(detail ? `${base}: ${detail}` : base);
      },
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
        // Only the meeting lead changes the public participation; send it only on a change.
        ...this.publicChanges(m),
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
          if (errorCode(err) === 'public_join_needs_no_quorum') {
            this.toast.error(this.i18n.translate('guests.toast.needsNoQuorum'));
            return;
          }
          if (errorCode(err) === 'guest_vote_open') {
            this.toast.error(this.i18n.translate('guests.toast.guestVoteOpen'));
            return;
          }
          const detail = errorDetail(err);
          const base = this.i18n.translate('meetings.toast.actionFailed');
          this.toast.error(detail ? `${base}: ${detail}` : base);
        },
      });
  }

  /** The changed public participation fields of the PATCH. */
  private publicChanges(m: Meeting): { publicJoin?: boolean; guestsMode?: GuestsMode } {
    if (this.publicLocked()) return {};
    const out: { publicJoin?: boolean; guestsMode?: GuestsMode } = {};
    if (this.publicJoin() !== m.publicJoin) out.publicJoin = this.publicJoin();
    if (this.publicJoin() && this.guestsMode() !== m.guestsMode) out.guestsMode = this.guestsMode();
    return out;
  }
}
