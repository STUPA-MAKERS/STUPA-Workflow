import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { PageFrameService } from '../../../layout/page-frame.service';
import { CreateMeetingDialogComponent } from '../create-meeting-dialog/create-meeting-dialog.component';
import { MeetingsCalendarComponent } from '../meetings-calendar/meetings-calendar.component';
import { MeetingsListComponent } from '../meetings-list/meetings-list.component';
import { type MeetingsView, readStoredView, storeView } from '../meetings-overview.util';
import { MeetingsTimelineService } from '../meetings-timeline.service';

/**
 * The meeting overview (`/meetings`, board Sitzungen, variant C): the list view
 * (`app-meetings-list`, list and detail) or the calendar view (`app-meetings-calendar`),
 * with the switch "Liste | Kalender" in the header of both.
 *
 * The browser keeps the chosen view (`localStorage`). A phone shows only the list: a
 * month grid does not fit, and the list there is the step before the detail. "Neue
 * Sitzung" opens the create dialog from both views.
 *
 * `pane` tells `MeetingsComponent` that the view fills the free height and scrolls only
 * inside its panes (the list beside the detail, or the wide calendar).
 */
@Component({
  selector: 'app-meetings-overview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MeetingsListComponent, MeetingsCalendarComponent, CreateMeetingDialogComponent],
  templateUrl: './meetings-overview.component.html',
  styleUrl: './meetings-overview.component.scss',
})
export class MeetingsOverviewComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  private readonly frame = inject(PageFrameService);
  protected readonly timeline = inject(MeetingsTimelineService);

  readonly phone = mediaQuerySignal(MEDIA.phone);
  private readonly wide = mediaQuerySignal(MEDIA.wide);

  /** The view this browser chose. */
  private readonly chosen = signal<MeetingsView>(readStoredView());
  /** The view that shows: a phone always shows the list. */
  readonly view = computed<MeetingsView>(() => (this.phone() ? 'list' : this.chosen()));

  /** "Neue Sitzung": an admin, or `session.manage` in at least one Gremium. */
  readonly canCreate = computed(
    () => this.auth.isAdmin() || this.auth.sessionManageGremien().length > 0,
  );
  readonly createOpen = signal(false);

  private readonly list = viewChild(MeetingsListComponent);
  /** The view fills the free height of the page and does not scroll as a page. */
  readonly pane = computed(() =>
    this.view() === 'calendar' ? this.wide() : this.list()?.split() === true,
  );

  constructor() {
    // A pane view drops the footer of the frame below it, so only the panes scroll.
    effect(() => this.frame.fill.set(this.pane()));
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
  }

  setView(view: MeetingsView): void {
    this.chosen.set(view);
    storeView(view);
  }
}
