import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { CreateMeetingDialogComponent } from '../create-meeting-dialog/create-meeting-dialog.component';
import { MeetingsListComponent } from '../meetings-list/meetings-list.component';
import { MeetingsTimelineService } from '../meetings-timeline.service';

/**
 * The meeting overview (`/meetings`): the list (`app-meetings-list`, one column, a row
 * opens the meeting) and the create dialog of "Neue Sitzung".
 *
 * The month grid of the meetings is on the Kalender page (`/calendar`), which shows them
 * with the other dates of the person, so Sitzungen has no second view.
 */
@Component({
  selector: 'app-meetings-overview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MeetingsListComponent, CreateMeetingDialogComponent],
  templateUrl: './meetings-overview.component.html',
  styleUrl: './meetings-overview.component.scss',
})
export class MeetingsOverviewComponent {
  private readonly auth = inject(AuthService);
  protected readonly timeline = inject(MeetingsTimelineService);

  /** "Neue Sitzung": an admin, or `session.manage` in at least one Gremium. */
  readonly canCreate = computed(
    () => this.auth.isAdmin() || this.auth.sessionManageGremien().length > 0,
  );
  readonly createOpen = signal(false);
}
