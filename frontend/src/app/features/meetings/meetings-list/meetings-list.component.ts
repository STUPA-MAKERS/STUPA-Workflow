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
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { meetingStatus, type StatusView } from '@shared/status-kind.util';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { FilterSelectComponent } from '@shared/ui/filter-select/filter-select.component';
import { ListDetailLayoutComponent } from '@shared/ui/list-detail/list-detail-layout.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import type { RowMenuItem, RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { RowMenuComponent } from '@shared/ui/row-menu/row-menu.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { MeetingDetailSheetComponent } from '../meeting-detail-sheet/meeting-detail-sheet.component';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { meetingDay, meetingTimeText } from '../meetings-display.util';
import {
  type MeetingGroup,
  type MeetingsView,
  overviewGroups,
  topsLabel,
  weekdayShort,
} from '../meetings-overview.util';
import { MeetingsTimelineService } from '../meetings-timeline.service';
import { MeetingsViewSwitchComponent } from '../meetings-view-switch/meetings-view-switch.component';
import { beamerUrl } from '../../voting/beamer-link.util';

/**
 * The list view of the meeting overview (`/meetings`, board Sitzungen, variant A): a
 * list/detail pane page like the applications and the tasks.
 *
 * Left: the title with the switch "Liste | Kalender" and the calendar subscription, the
 * search and the Gremium chip (they never scroll away), then the groups "Jetzt",
 * "Anstehend · <Monat>" and "Vergangen · <Monat>". A row shows the date, the title, the
 * status, the Gremium, the time and the number of agenda items. "Frühere Sitzungen laden"
 * ends the list; "Neue Sitzung" is the FAB of the list (on a phone the button of the
 * header). Right: the detail sheet of the selected meeting (`?sel=<id>`); side by side
 * the live meeting, else the next one, shows while nothing is selected.
 *
 * A search collapses the groups into one list of hits by relevance (server side).
 * `MeetingsComponent` provides the timeline and the dialog services.
 */
@Component({
  selector: 'app-meetings-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    DateBlockComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    RowMenuComponent,
    SearchPillComponent,
    SkeletonComponent,
    StatusTextComponent,
    StickyBarComponent,
    ScrollFadeDirective,
    MeetingDetailSheetComponent,
    MeetingsViewSwitchComponent,
  ],
  templateUrl: './meetings-list.component.html',
  styleUrl: './meetings-list.component.scss',
})
export class MeetingsListComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  protected readonly timeline = inject(MeetingsTimelineService);
  private readonly dialogs = inject(MeetingDialogsService);

  /** "Neue Sitzung" shows (an admin, or `session.manage` in a Gremium). */
  readonly canCreate = input(false);
  /** The switch to the calendar shows (not on a phone). */
  readonly showSwitch = input(true);

  readonly viewChange = output<MeetingsView>();
  readonly create = output<void>();

  /** A phone viewport: the header holds one button and one menu. */
  readonly phone = mediaQuerySignal(MEDIA.phone);

  private readonly layout = viewChild(ListDetailLayoutComponent);
  /** The list and the detail sit side by side: the page does not scroll. */
  readonly split = computed(() => this.layout()?.collapsed() === false);

  /** The meeting of `?sel=<id>`. */
  readonly selParam = toSignal(
    this.route.queryParamMap.pipe(map((q) => q.get('sel'))),
    { initialValue: null },
  );
  /** A selected meeting that is not in the loaded pages (a deep link). */
  private readonly extra = signal<Meeting | null>(null);
  /**
   * The read of a deep-linked meeting failed for another reason than "not found": the
   * selection stays, and the detail pane says why (`forbidden` for 403, else `failed`).
   */
  readonly selError = signal<{ id: Uuid; kind: 'forbidden' | 'failed' } | null>(null);
  private requested: string | null = null;

  /** Every loaded meeting, to find the selected one. */
  private readonly loaded = computed(() => [
    ...this.timeline.upcomingItems(),
    ...this.timeline.pastItems(),
    ...this.timeline.searchItems(),
  ]);

  /**
   * Side by side a sheet always shows: without a selection the live meeting, else the
   * next one. One pane at a time only a selection opens the detail.
   */
  private readonly fallback = computed<Meeting | null>(() => {
    if (!this.split()) return null;
    const upcoming = this.timeline.upcomingItems();
    return upcoming.find((m) => m.status === 'live') ?? upcoming[0] ?? null;
  });

  readonly selected = computed<Meeting | null>(() => {
    const id = this.selParam();
    if (!id) return this.fallback();
    const found = this.loaded().find((m) => m.id === id);
    if (found) return found;
    const extra = this.extra();
    return extra?.id === id ? extra : null;
  });

  readonly groups = computed<MeetingGroup[]>(() =>
    overviewGroups(this.timeline.upcomingItems(), this.timeline.pastItems(), this.i18n.locale()),
  );
  readonly hasUpcoming = computed(() =>
    this.groups().some((g) => g.kind !== 'past'),
  );

  /** The filter offers a choice only when the user reads more than one Gremium. */
  readonly showFilter = computed(() => this.timeline.filterGremien().length > 1);
  readonly filterLabel = computed(() => {
    const options = this.timeline.filterGremiumOptions();
    const value = this.timeline.gremiumFilter();
    // An unknown value (a Gremium that left the list) reads as "Alle Gremien".
    return options.find((o) => o.value === value)?.label ?? options[0].label;
  });

  /** The ⋮ menu of the phone header: the calendar subscription. */
  readonly phoneMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        { id: 'calendar', label: this.i18n.translate('meetings.overview.subscribe'), icon: 'cal' },
      ],
    },
  ]);

  constructor() {
    // A deep link to a meeting that is not in the first pages: read it once.
    effect(() => {
      const id = this.selParam();
      const loading = this.timeline.loadingList();
      if (!id || loading) return;
      untracked(() => {
        if (this.requested === id || this.loaded().some((m) => m.id === id)) return;
        this.readSelected(id);
      });
    });

    // A dialog changed or deleted a meeting: keep the deep-linked one current, and drop
    // the selection of a deleted one.
    effect(() => {
      const change = this.timeline.lastChange();
      if (!change) return;
      untracked(() => {
        if (change.kind === 'updated') {
          if (this.extra()?.id === change.meeting.id) this.extra.set(change.meeting);
          return;
        }
        if (this.extra()?.id === change.id) this.extra.set(null);
        if (this.selParam() === change.id) this.clearSelection();
      });
    });
  }

  /**
   * Read a deep-linked meeting. Only a 404 drops the selection (the meeting is gone).
   * A 403, a server error or a network error keeps it and shows the reason, so a reload
   * or "Erneut laden" can still reach the meeting.
   */
  private readSelected(id: Uuid): void {
    this.requested = id;
    this.selError.set(null);
    this.api.getMeeting(id).subscribe({
      next: (m) => this.extra.set(m),
      error: (err: unknown) => {
        this.requested = null;
        const status = err instanceof HttpErrorResponse ? err.status : 0;
        if (status === 404) {
          this.clearSelection();
          return;
        }
        this.selError.set({ id, kind: status === 403 ? 'forbidden' : 'failed' });
      },
    });
  }

  /** "Erneut laden" after a failed read of the deep-linked meeting. */
  retrySelected(): void {
    const id = this.selParam();
    if (id) this.readSelected(id);
  }

  /** Select a meeting: its sheet shows beside the list, or as the next step. */
  select(m: Meeting): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { sel: m.id },
      queryParamsHandling: 'merge',
    });
  }

  /** Open the meeting page (double click on a row). */
  open(id: Uuid): void {
    void this.router.navigate(['/meetings', id]);
  }

  /** "Zur Liste": close the detail of the one-pane layout. */
  clearSelection(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { sel: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  edit(m: Meeting): void {
    this.dialogs.openSettings(m);
  }

  remove(m: Meeting): void {
    this.dialogs.askDeleteMeeting(m);
  }

  /** "Beamer-Ansicht" in a new tab, so the overview stays. */
  beamer(m: Meeting): void {
    const url = this.router.serializeUrl(beamerUrl(this.router, m.id));
    window.open(url, '_blank', 'noopener');
  }

  onPhoneMenu(item: RowMenuItem): void {
    if (item.id === 'calendar') void this.router.navigate(['/account/calendar']);
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
    const weekday = weekdayShort(m.date, this.i18n.locale());
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
