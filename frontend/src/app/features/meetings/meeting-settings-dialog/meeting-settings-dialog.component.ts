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
import type {
  Attendance,
  GuestsMode,
  JoinLink,
  Meeting,
  MeetingDefaults,
  MeetingForm,
  MeetingKind,
  MeetingPatchBody,
} from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  ConfirmDialogComponent,
  DatepickerComponent,
  DialogComponent,
  InputComponent,
  NoteComponent,
  SelectFieldComponent,
  type SelectFieldOption,
  TimeInputComponent,
  ToastService,
  DialogBodyDirective,
} from '@stupa-makers/ui-kit';
import { problemCode, problemDetail } from '@core/api/problem';
import { MeetingGuestsService } from '../meeting-guests.service';
import {
  firstMeetingOptions,
  lateInviteDays,
  locationError,
  locationTooLong,
  meetingFormOptions,
  meetingKindOptions,
} from '../meeting-kind.util';
import { PublicJoinSettingsComponent } from '../public-join/public-join-settings.component';
import { personLabel } from '@shared/person-label.util';

/** The longest meeting title that the server accepts (`MEETING_TITLE_MAX`). */
export const MEETING_TITLE_MAX = 200;

/**
 * "Sitzung bearbeiten": the title, the kind, the minute-taker, the date, the start, the
 * end, the place and the form of a meeting. The kind changes only while the meeting is
 * planned (§ 000903). A Wiederholungssitzung names its first meeting (§ 000940).
 *
 * The dialog opens from a list row, from the detail sheet, from the calendar and from
 * the meeting page. The title can change while the meeting is planned or live. A
 * closed meeting locks every field, the title too, because the protocol that goes out
 * names the meeting; a final protocol also locks the minute-taker. The server refuses
 * both with 409. Only a member with `protocol.write` can keep the minutes, so the
 * list offers those members plus the current minute-taker. While the meeting is live a
 * new minute-taker is a handover "now".
 */
@Component({
  selector: 'app-meeting-settings-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    ConfirmDialogComponent,
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    InputComponent,
    SelectFieldComponent,
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
  readonly title = signal('');
  readonly keeper = signal('');
  readonly date = signal('');
  readonly time = signal('');
  readonly endTime = signal('');
  readonly saving = signal(false);
  /** Public participation: the switch, the mode and the join link. */
  readonly publicJoin = signal(false);
  readonly guestsMode = signal<GuestsMode>('watch');
  readonly kind = signal<MeetingKind>('ordinary');
  /** The first meeting of a Wiederholungssitzung (§ 000940). */
  readonly repeatOf = signal('');
  /** The meetings of the Gremium, read for a planned meeting. */
  readonly meetings = signal<Meeting[]>([]);
  readonly repeatOfOptions = computed(() =>
    firstMeetingOptions(
      this.meetings(),
      this.i18n.formatLocale(),
      this.date(),
      this.meeting()?.id ?? null,
    ),
  );
  /** A planned Wiederholungssitzung names a first meeting that the list still holds. */
  readonly repeatOfMissing = computed(
    () =>
      !this.kindLocked() &&
      this.kind() === 'repeat' &&
      !this.repeatOfOptions().some((o) => o.value === this.repeatOf()),
  );
  readonly location = signal('');
  readonly form = signal<MeetingForm>('presence');
  readonly kindOptions = computed(() => meetingKindOptions(this.i18n));
  readonly formOptions = computed(() => meetingFormOptions(this.i18n));
  /** The place is too long for the server. */
  readonly locationTooLong = computed(() => locationTooLong(this.location()));
  readonly locationError = computed(() => locationError(this.i18n, this.location()));
  /** The invitation periods of the Gremium, read for a planned meeting. */
  readonly defaults = signal<MeetingDefaults | null>(null);
  /**
   * The invitation period that a new date misses, else `null`. Only a planned meeting
   * with a changed date or a changed kind warns, because the kind sets the period, and
   * the warning never blocks the save (§ 000918).
   */
  readonly lateInvite = computed(() => {
    const m = this.meeting();
    if (m?.status !== 'planned') return null;
    if (this.date().trim() === m.date && this.kind() === m.kind) return null;
    return lateInviteDays(this.date(), this.kind(), this.defaults());
  });
  /** The kind is fixed from the start of the meeting on. */
  readonly kindLocked = computed(() => this.meeting()?.status !== 'planned');
  readonly link = signal<JoinLink | null>(null);
  readonly rotating = signal(false);
  /** The confirmation before the public participation goes off in a live meeting. */
  readonly confirmOff = signal(false);

  /** The meeting is closed: its minute-taker, its kind and its guest settings stay. */
  readonly closedMeeting = computed(() => this.meeting()?.status === 'closed');
  /**
   * A closed meeting with a final protocol locks every setting. Until then the title, the
   * date, the times, the place and the form stay open (§ 000982).
   */
  readonly locked = computed(() => this.closedMeeting() && this.protocolFinal());
  readonly keeperLocked = computed(() => this.closedMeeting() || this.protocolFinal());

  /** Members with `protocol.write`, and the current minute-taker. */
  readonly keeperOptions = computed<SelectFieldOption[]>(() => {
    const current = this.meeting()?.protokollantId ?? null;
    const none = this.i18n.translate('meetings.protokollant.none');
    return [
      { value: '', label: none, person: { name: none, icon: 'user' } },
      ...this.roster()
        .filter((a) => a.canKeepProtocol || a.principalId === current)
        .map((a) => {
          const label = personLabel(a, this.i18n);
          return { value: a.principalId, label, person: { name: label, principalId: a.principalId } };
        }),
    ];
  });

  /** Only the meeting lead (`canManage`) changes the public participation. */
  readonly publicLocked = computed(() => this.closedMeeting() || !this.meeting()?.canManage);
  /** The counts that the confirmation names: open requests and admitted guests. */
  readonly offCounts = computed(() => ({
    pending: this.meeting()?.pendingGuests ?? 0,
    admitted: this.meeting()?.admittedGuests ?? 0,
  }));

  /** The title is too long for the server. An empty title only disables "Speichern". */
  readonly titleTooLong = computed(() => this.title().trim().length > MEETING_TITLE_MAX);
  readonly titleError = computed(() =>
    this.titleTooLong()
      ? this.i18n.translate('meetings.settings.titleTooLong', { max: MEETING_TITLE_MAX })
      : '',
  );

  readonly valid = computed(
    () =>
      !!this.title().trim() &&
      !this.titleTooLong() &&
      !this.locationTooLong() &&
      !this.repeatOfMissing() &&
      !!this.date().trim() &&
      !!this.time().trim(),
  );

  constructor() {
    effect(() => {
      const m = this.meeting();
      if (m) untracked(() => this.load(m));
    });
  }

  private load(m: Meeting): void {
    this.title.set(m.title ?? '');
    this.keeper.set(m.protokollantId ?? '');
    this.date.set(m.date ?? '');
    this.time.set(m.startTime ?? '');
    this.endTime.set(m.endTime ?? '');
    this.saving.set(false);
    this.publicJoin.set(m.publicJoin);
    this.guestsMode.set(m.guestsVoteAllowed ? m.guestsMode : 'watch');
    this.kind.set(m.kind);
    this.repeatOf.set(m.repeatOfId ?? '');
    this.meetings.set([]);
    this.location.set(m.location ?? '');
    this.form.set(m.form);
    this.link.set(null);
    this.rotating.set(false);
    this.confirmOff.set(false);
    if (m.publicJoin && m.canManage) this.loadLink(m);
    this.defaults.set(null);
    if (m.status === 'planned' && m.gremiumId) {
      this.loadDefaults(m.id, m.gremiumId);
      this.loadMeetings(m.id, m.gremiumId);
    }
    this.roster.set([]);
    this.api.listAttendance(m.id, { quiet: true }).subscribe({
      next: (rows) => {
        this.roster.set(rows);
        this.keeper.set(m.protokollantId ?? '');
      },
      error: () => this.roster.set([]),
    });
  }

  private loadDefaults(meetingId: string, gremiumId: string): void {
    this.api.meetingDefaults(gremiumId).subscribe({
      next: (d) => {
        if (this.meeting()?.id === meetingId) this.defaults.set(d);
      },
      error: () => {},
    });
  }

  private loadMeetings(meetingId: string, gremiumId: string): void {
    this.api.listMeetings(gremiumId).subscribe({
      next: (rows) => {
        if (this.meeting()?.id === meetingId) this.meetings.set(rows);
      },
      error: () => {},
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
        this.toast.show(this.i18n.translate('guests.toast.rotated'), 'success');
      },
      error: (err: unknown) => {
        this.rotating.set(false);
        const detail = problemDetail(err);
        const base = this.i18n.translate('meetings.toast.actionFailed');
        this.toast.show(detail ? `${base}: ${detail}` : base, 'error');
      },
    });
  }

  cancel(): void {
    this.closed.emit();
  }

  /**
   * Save the title, the minute-taker, the date and the times in one PATCH.
   *
   * Only a new title goes out, because the same title again costs an audit read. A final protocol
   * locks the minute-taker, so the field stays out of the request; the server would answer 409.
   */
  save(): void {
    const m = this.meeting();
    if (!m || this.saving() || this.locked()) return;
    const title = this.title().trim();
    if (!title || this.titleTooLong()) {
      this.toast.show(
        this.titleError() || this.i18n.translate('meetings.toast.titleRequired'),
        'error',
      );
      return;
    }
    if (this.repeatOfMissing()) {
      this.toast.show(this.i18n.translate('meetings.repeatOf.required'), 'error');
      return;
    }
    if (!this.valid()) {
      this.toast.show(this.i18n.translate('meetings.toast.dateTimeRequired'), 'error');
      return;
    }
    const end = this.endTime().trim();
    if (end && end <= this.time().trim()) {
      this.toast.show(this.i18n.translate('meetings.create.endBeforeStart'), 'error');
      return;
    }
    this.saving.set(true);
    this.api
      .patchMeeting(m.id, {
        ...(title !== m.title ? { title } : {}),
        ...(this.keeperLocked() ? {} : { protokollantId: this.keeper() || null }),
        date: this.date().trim(),
        startTime: this.time().trim(),
        endTime: end || null,
        ...this.placeChanges(m),
        ...this.publicChanges(m),
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.toast.show(this.i18n.translate('meetings.toast.settingsSaved'), 'success');
          this.saved.emit(updated);
        },
        error: (err: unknown) => {
          this.saving.set(false);
          if (problemCode(err) === 'protokollant_needs_protocol_write') {
            this.toast.show(this.i18n.translate('meetings.toast.needsProtocolWrite'), 'error');
            return;
          }
          if (problemCode(err) === 'protocol_final') {
            this.toast.show(this.i18n.translate('meetings.settings.closedHint'), 'error');
            return;
          }
          const code = problemCode(err);
          if (code === 'repeat_first_meeting_invalid' || code === 'repeat_needs_first_meeting') {
            this.toast.show(this.i18n.translate('meetings.repeatOf.invalid'), 'error');
            return;
          }
          if (code === 'guests_vote_off' || code === 'guests_vote_needs_no_quorum') {
            this.toast.show(this.i18n.translate('guests.toast.voteOff'), 'error');
            return;
          }
          if (problemCode(err) === 'guest_vote_open') {
            this.toast.show(this.i18n.translate('guests.toast.guestVoteOpen'), 'error');
            return;
          }
          const detail = problemDetail(err);
          const base = this.i18n.translate('meetings.toast.actionFailed');
          this.toast.show(detail ? `${base}: ${detail}` : base, 'error');
        },
      });
  }

  /**
   * The changed kind, first meeting, place and form of the PATCH. A started meeting
   * keeps its kind and its first meeting.
   */
  private placeChanges(
    m: Meeting,
  ): Pick<MeetingPatchBody, 'kind' | 'repeatOfId' | 'location' | 'form'> {
    const location = this.location().trim() || null;
    const first = this.kind() === 'repeat' ? this.repeatOf() : null;
    return {
      ...(!this.kindLocked() && this.kind() !== m.kind ? { kind: this.kind() } : {}),
      ...(!this.kindLocked() && first && first !== (m.repeatOfId ?? null)
        ? { repeatOfId: first }
        : {}),
      ...(location !== (m.location ?? null) ? { location } : {}),
      ...(this.form() !== m.form ? { form: this.form() } : {}),
    };
  }

  /** The changed public participation fields of the PATCH. */
  private publicChanges(m: Meeting): { publicJoin?: boolean; guestsMode?: GuestsMode } {
    if (this.publicLocked()) return {};
    const join = this.publicJoin() !== m.publicJoin ? { publicJoin: this.publicJoin() } : {};
    const modeChanged = this.publicJoin() && this.guestsMode() !== m.guestsMode;
    const mode = modeChanged ? { guestsMode: this.guestsMode() } : {};
    return { ...join, ...mode };
  }
}
