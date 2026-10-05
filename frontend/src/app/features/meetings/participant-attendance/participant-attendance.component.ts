import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Attendance, MeetingStatus, SelfAttendanceStatus } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { StatusKind } from '@shared/status-kind.util';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { InputComponent, SegmentedComponent, type SegmentedOption } from '@stupa-makers/ui-kit';

let nextId = 0;

/** An own attendance report: the status and, for an excuse, the reason. Without `note`
 *  the server keeps the stored reason. */
export interface OwnAttendanceChange {
  status: SelfAttendanceStatus;
  note?: string | null;
}

/**
 * "Deine Anwesenheit" of a member (board Teilnahme-Vorher): "Anwesend" or "Abwesend"
 * (Z2; "Abwesend" sends an excuse, `excused`) and an optional reason, which only the
 * member and the meeting lead read.
 *
 * The member reports only while the meeting is planned or live, and only while the lead
 * did not set the record (O15). The record of the lead, and every record of a closed
 * meeting, shows as text. A member with an active delegation of the meeting cannot
 * report "Anwesend" (O23): the option is off and the reason stands below it.
 */
@Component({
  selector: 'app-participant-attendance',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, InputComponent, SegmentedComponent, StatusTextComponent],
  templateUrl: './participant-attendance.component.html',
  styleUrl: './participant-attendance.component.scss',
})
export class ParticipantAttendanceComponent {
  private readonly i18n = inject(I18nService);
  protected readonly capId = `pa-cap-${nextId++}`;

  /** The own row of the roster. */
  readonly member = input.required<Attendance>();
  readonly meetingStatus = input.required<MeetingStatus>();
  readonly saving = input(false);
  /** The member handed the meeting over to a substitute (O23). */
  readonly delegated = input(false);

  readonly change = output<OwnAttendanceChange>();

  /** The reason as the member types it. */
  protected readonly draft = signal('');

  constructor() {
    effect(() => this.draft.set(this.member().note ?? ''));
  }

  /** The lead set the record (O15), or the meeting is over: text only. */
  protected readonly locked = computed(
    () => this.member().source === 'lead' || this.meetingStatus() === 'closed',
  );

  /** "Abwesend" covers an excuse and an absence (Z2). */
  protected readonly value = computed<SelfAttendanceStatus | null>(() => {
    const status = this.member().status;
    if (status === 'present') return 'present';
    return status ? 'excused' : null;
  });

  protected readonly options = computed<SegmentedOption[]>(() => [
    {
      value: 'present',
      label: this.i18n.translate('meetings.attendance.selfPresent'),
      disabled: this.delegated() && this.value() !== 'present',
    },
    { value: 'excused', label: this.i18n.translate('meetings.attendance.selfExcused') },
  ]);

  /** The record as text: "Anwesend", "Abwesend" or "Offen". */
  protected readonly statusText = computed<{ kind: StatusKind; key: TranslationKey }>(() => {
    const value = this.value();
    if (value === 'present') return { kind: 'accent', key: 'meetings.attendance.selfPresent' };
    if (value === 'excused') return { kind: 'neutral', key: 'meetings.attendance.selfExcused' };
    return { kind: 'muted', key: 'meetings.attendance.unknown' };
  });

  protected pick(value: string | null): void {
    if (this.saving() || (value !== 'present' && value !== 'excused')) return;
    if (value === this.value()) return;
    this.change.emit({ status: value });
  }

  /** Send a changed reason with the excuse (the field shows only for an absence). An
   *  empty field removes the reason. */
  protected saveNote(): void {
    const note = this.draft().trim();
    if (this.saving() || note === (this.member().note ?? '')) return;
    this.change.emit({ status: 'excused', note: note || null });
  }
}
