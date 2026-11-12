import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import type { Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { meetingStatus, type StatusView } from '@shared/status-kind.util';
import {
  FabComponent,
  ButtonComponent,
  DateBlockComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  IconComponent,
  ListGroupComponent,
  ListItemComponent,
  MEDIA,
  mediaQuery,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SearchPillComponent,
  SkeletonComponent,
  StatusTextComponent,
  StickyBarComponent,
  PageHeaderComponent,
} from '@stupa-makers/ui-kit';
import { meetingDay, meetingTimeText } from '../meetings-display.util';
import { type MeetingGroup, overviewGroups, topsLabel } from '../meetings-overview.util';
import { MeetingsTimelineService } from '../meetings-timeline.service';
import { RowChevronComponent } from '@shared/ui/row-chevron/row-chevron.component';
import { weekdayName } from '@shared/date-format';
import { PullRefreshDirective } from '@shared/ui/pull-refresh/pull-refresh.directive';
import { isRefreshItem, refreshMenuSection, reloadLikePull } from '@shared/ui/pull-refresh/refresh-menu';

/**
 * The list view of the meeting overview (`/meetings`): one column on every screen, with no
 * detail pane, because the meeting page itself is the detail. A row opens the meeting
 * page; an old `?sel=<id>` link opens it as well.
 *
 * The title, the search and the Gremium chip (they never scroll away), then the groups "Jetzt",
 * "Anstehend · <Monat>" and "Vergangen · <Monat>". A row shows the date, the title, the
 * status, the Gremium, the time and the number of agenda items. "Frühere Sitzungen laden"
 * ends the list; "Neue Sitzung" is the FAB of the list (on a phone the button of the
 * header). Edit, beamer and delete are in the ⋮ menu of the meeting page.
 *
 * A search collapses the groups into one list of hits by relevance (server side).
 * `MeetingsComponent` provides the timeline and the dialog services.
 */
@Component({
  selector: 'app-meetings-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PullRefreshDirective,
    RowChevronComponent,
    PageHeaderComponent,
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    DateBlockComponent,
    EmptyStateComponent,
    FabComponent,
    FilterSelectComponent,
    ListGroupComponent,
    ListItemComponent,
    RowMenuComponent,
    SearchPillComponent,
    SkeletonComponent,
    StatusTextComponent,
    StickyBarComponent,
    ScrollFadeDirective,
  ],
  templateUrl: './meetings-list.component.html',
  styleUrl: './meetings-list.component.scss',
})
export class MeetingsListComponent {
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly timeline = inject(MeetingsTimelineService);

  /** "Neue Sitzung" shows (an admin, or `session.manage` in a Gremium). */
  readonly canCreate = input(false);

  readonly create = output<void>();

  /** A phone viewport: the header holds one button and one menu. */
  readonly phone = mediaQuery(MEDIA.phone);

  /** The meeting of an old `?sel=<id>` link: it opens the meeting page. */
  private readonly selParam = toSignal(
    this.route.queryParamMap.pipe(map((q) => q.get('sel'))),
    { initialValue: null },
  );

  readonly groups = computed<readonly MeetingGroup[]>(() =>
    overviewGroups(this.timeline.upcomingItems(), this.timeline.pastItems(), this.i18n.locale()),
  );
  readonly hasUpcoming = computed(() =>
    this.groups().some((g) => g.kind !== 'past'),
  );

  /** The ⋮ menu of the phone header: read the list again. */
  readonly phoneMenu = computed<RowMenuSection[]>(() => [
    refreshMenuSection((key) => this.i18n.translate(key)),
  ]);

  constructor() {
    effect(() => {
      const id = this.selParam();
      if (id) void this.router.navigate(['/meetings', id], { replaceUrl: true });
    });
  }

  /** Open the meeting page. */
  open(id: Uuid): void {
    void this.router.navigate(['/meetings', id]);
  }

  /** The ⋮ menu of the phone header. */
  onPhoneMenu(item: RowMenuItem): void {
    if (isRefreshItem(item)) reloadLikePull(() => this.timeline.refreshList());
  }

  status(m: Meeting): StatusView {
    return meetingStatus(m.status);
  }

  day(m: Meeting): string | null {
    return meetingDay(m);
  }

  /** "seit 18:04" for a live meeting, else "Di, 18:00" (the start of the meeting). */
  time(m: Meeting): string {
    const t = meetingTimeText(m, this.i18n.locale());
    if (t.since) return this.i18n.translate('meetings.list.since', { time: t.text });
    const start = t.text.split('–')[0];
    if (!m.date) return start;
    const weekday = weekdayName(m.date, this.i18n.formatLocale());
    return start ? `${weekday}, ${start}` : weekday;
  }

  tops(m: Meeting): string {
    return topsLabel(m.agendaItemCount ?? 0, (k, p) => this.i18n.translate(k, p));
  }

  /** The heading of a group: "Jetzt", "Anstehend · Oktober 2026", "Vergangen · …". */
  groupLabel(g: MeetingGroup): string {
    if (g.kind === 'now') return this.i18n.translate('meetings.list.now');
    const month = g.month || this.i18n.translate('meetings.overview.undated');
    return this.i18n.translate(
      g.kind === 'upcoming' ? 'meetings.overview.groupUpcoming' : 'meetings.overview.groupPast',
      { month },
    );
  }
}
