import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Attendance, AttendanceStatus, SelfAttendanceStatus } from '@core/api/models';
import { BadgeComponent, IconComponent } from '@stupa-makers/ui-kit';
import {
  SELF_ATTENDANCE_STATUSES,
  attendanceBadgeVariant,
  attendanceIcon,
  attendanceKey,
  selfAttendanceKey,
} from './meetings-display.util';

/** One attendance change. `note` is the reason of an excuse; omitted keeps the stored one. */
export interface AttendanceChange {
  member: Attendance;
  status: AttendanceStatus;
  note?: string | null;
}

/**
 * Attendance roster table (Z2, O15).
 *
 * The meeting lead (`editAll`) sets every row to present, excused or unexcused, and
 * resets a row to "open". A member reports only the own row, as present or absent
 * (`excused`), with an optional reason. A row that the lead set shows read-only to the
 * member. The reason shows only when the server sends it: to the member and to the lead.
 */
@Component({
  selector: 'app-meeting-attendance-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, BadgeComponent, IconComponent],
  templateUrl: './meeting-attendance-table.component.html',
  styleUrl: './meeting-attendance-table.component.scss',
})
export class MeetingAttendanceTableComponent {
  readonly rows = input.required<Attendance[]>();
  /** The protokollant of the meeting. The roster marks that row. */
  readonly protokollantId = input<string | null>(null);
  /** True for the meeting lead. False limits the edit to the own row. */
  readonly editAll = input.required<boolean>();
  readonly locked = input.required<boolean>();
  readonly saving = input.required<boolean>();
  readonly statusChange = output<AttendanceChange>();
  /** The lead resets a row to "open". */
  readonly reset = output<Attendance>();

  protected readonly statuses: readonly AttendanceStatus[] = ['present', 'excused', 'absent'];
  protected readonly selfStatuses = SELF_ATTENDANCE_STATUSES;
  protected readonly key = attendanceKey;
  protected readonly selfKey = selfAttendanceKey;
  protected readonly icon = attendanceIcon;
  protected readonly badge = attendanceBadgeVariant;

  /** The member edits the own row while the lead did not set it (O15). */
  protected selfEditable(a: Attendance): boolean {
    return !this.editAll() && a.isSelf && a.source !== 'lead';
  }

  /** The reason field shows for an excused row that the viewer may edit. */
  protected noteEditable(a: Attendance): boolean {
    return a.status === 'excused' && (this.editAll() || this.selfEditable(a));
  }

  protected pickSelf(a: Attendance, status: SelfAttendanceStatus): void {
    this.statusChange.emit({ member: a, status });
  }

  /** Save a changed reason. An empty field removes it. */
  protected saveNote(a: Attendance, value: string): void {
    const note = value.trim() || null;
    if (note === a.note) return;
    this.statusChange.emit({ member: a, status: 'excused', note });
  }
}
