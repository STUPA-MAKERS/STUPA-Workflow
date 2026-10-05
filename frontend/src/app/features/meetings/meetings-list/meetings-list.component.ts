import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { Router } from '@angular/router';
import type { Meeting, Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { meetingStatus, type StatusView } from '@shared/status-kind.util';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import { FilterSelectComponent } from '@shared/ui/filter-select/filter-select.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { CreateMeetingDialogComponent } from '../create-meeting-dialog/create-meeting-dialog.component';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { type MeetingTimeText, meetingDay, meetingTimeText } from '../meetings-display.util';
import { MeetingsTimelineService } from '../meetings-timeline.service';

/**
 * The meeting list (`/meetings`, board "Arbeit-Sitzungen").
 *
 * Past meetings sit above the "Jetzt" marker, the live and the upcoming ones below it.
 * The first load shows the most recent past meetings; "Frühere Sitzungen laden" adds
 * older ones on top, "Weitere Sitzungen laden" adds later ones at the end. A search
 * collapses the list into one list of hits, sorted by relevance. The server filters
 * every page to the meetings that the user may read.
 *
 * A row shows the date, the title, the status as coloured text, the Gremium, the time
 * and the minute-taker. A Gremium lead (`canManage` of the meeting) gets "Bearbeiten"
 * and "Löschen" on the row. "Neue Sitzung" needs `session.manage` in a Gremium.
 *
 * MeetingsComponent provides the timeline and the dialog services.
 */
@Component({
  selector: 'app-meetings-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    FilterSelectComponent,
    IconComponent,
    PageHeaderComponent,
    SearchPillComponent,
    StickyBarComponent,
    ListItemComponent,
    DateBlockComponent,
    StatusTextComponent,
    SkeletonComponent,
    CreateMeetingDialogComponent,
  ],
  templateUrl: './meetings-list.component.html',
  styleUrl: './meetings-list.component.scss',
})
export class MeetingsListComponent {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  protected readonly timeline = inject(MeetingsTimelineService);
  private readonly dialogs = inject(MeetingDialogsService);

  /** "Neue Sitzung": an admin, or `session.manage` in at least one Gremium. */
  readonly canCreate = computed(
    () => this.auth.isAdmin() || this.auth.sessionManageGremien().length > 0,
  );
  readonly createOpen = signal(false);

  /** The filter offers a choice only when the user reads more than one Gremium. */
  readonly showFilter = computed(() => this.timeline.filterGremien().length > 1);
  /** The label of the selected filter option, which the chip shows. */
  readonly filterLabel = computed(() => {
    const options = this.timeline.filterGremiumOptions();
    const value = this.timeline.gremiumFilter();
    return (options.find((o) => o.value === value) ?? options[0])?.label ?? '';
  });
  /** A phone viewport: the sub line of a row puts the time first. */
  readonly phone = mediaQuerySignal(MEDIA.phone);

  open(id: Uuid): void {
    void this.router.navigate(['/meetings', id]);
  }

  edit(m: Meeting): void {
    this.dialogs.openSettings(m);
  }

  remove(m: Meeting): void {
    this.dialogs.askDeleteMeeting(m);
  }

  status(m: Meeting): StatusView {
    return meetingStatus(m.status);
  }

  time(m: Meeting): MeetingTimeText {
    return meetingTimeText(m, this.i18n.locale());
  }

  day(m: Meeting): string | null {
    return meetingDay(m);
  }
}
