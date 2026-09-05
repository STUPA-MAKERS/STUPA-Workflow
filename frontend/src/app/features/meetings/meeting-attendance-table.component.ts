import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Attendance, AttendanceStatus } from '@core/api/models';
import { BadgeComponent, IconComponent } from '@stupa-makers/ui-kit';
import {
  attendanceBadgeVariant,
  attendanceIcon,
  attendanceKey,
} from './meetings-display.util';

/** Attendance roster table. A user edits the own row. The meeting lead edits all rows. */
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
  readonly statusChange = output<{ member: Attendance; status: AttendanceStatus }>();

  protected readonly statuses: readonly AttendanceStatus[] = ['present', 'excused', 'absent'];
  protected readonly key = attendanceKey;
  protected readonly icon = attendanceIcon;
  protected readonly badge = attendanceBadgeVariant;
}
