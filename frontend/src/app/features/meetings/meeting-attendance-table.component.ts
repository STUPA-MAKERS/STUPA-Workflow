import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Attendance, AttendanceStatus, SelfAttendanceStatus } from '@core/api/models';
import { BadgeComponent, IconComponent } from '@stupa-makers/ui-kit';
import {
  SELF_ATTENDANCE_STATUSES,
  attendanceIcon,
  attendanceKey,
  memberAttendanceBadgeVariant,
  memberAttendanceKey,
  selfAttendanceKey,
} from './meetings-display.util';
import type { AttendanceChange } from './attendance-sheet/attendance-sheet.component';

export type { AttendanceChange };

/**
 * Attendance roster table of the follow view (Z2, O15). The session page uses the
 * attendance sheet (`AttendanceSheetComponent`).
 *
 * The meeting lead (`editAll`) sets every row to present, excused or unexcused, and
 * resets a row to "open". A member reports only the own row, as present or absent
 * (`excused`), with an optional reason. A row that the lead set shows read-only to the
 * member. The reason shows only when the server sends it: to the member and to the lead.
 *
 * Labels (Z2): the lead sees "Anwesend / Entschuldigt / Unentschuldigt / Offen". A member
 * sees "Anwesend / Abwesend" on every row; `excused` and `absent` both show as "Abwesend".
 *
 * Every change of the lead takes the record over (`source='lead'`, O15). So the lead
 * edits the reason only on a row that the lead set and on the own row. The reason of a
 * member's own excuse stays the member's and shows read-only to the lead.
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
  protected readonly memberKey = memberAttendanceKey;
  protected readonly memberBadge = memberAttendanceBadgeVariant;

  /** The member edits the own row while the lead did not set it (O15). */
  protected selfEditable(a: Attendance): boolean {
    return !this.editAll() && a.isSelf && a.source !== 'lead';
  }

  /**
   * The reason field shows for an excused row that the viewer may edit. The lead edits
   * it on a lead row and on the own row only: a save from the lead takes the record
   * over (O15), so the member's own excuse stays read-only for the lead.
   */
  protected noteEditable(a: Attendance): boolean {
    if (a.status !== 'excused') return false;
    if (this.editAll()) return a.source === 'lead' || a.isSelf;
    return this.selfEditable(a);
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
