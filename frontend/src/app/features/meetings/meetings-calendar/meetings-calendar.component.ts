import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  Injector,
  NgZone,
} from '@angular/core';
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting } from '@core/api/models';
import { I18nService, toFormatLocale } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { meetingStatus, type StatusView } from '@shared/status-kind.util';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import { FilterSelectComponent } from '@shared/ui/filter-select/filter-select.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import type { RowMenuItem, RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { RowMenuComponent } from '@shared/ui/row-menu/row-menu.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import type { Seg } from '@shared/ui/seg-bar/seg-bar.component';
import { SegBarComponent } from '@shared/ui/seg-bar/seg-bar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { CalendarSubscribeComponent } from '../calendar-subscribe/calendar-subscribe.component';
import { MeetingDialogsService } from '../meeting-dialogs.service';
import { meetingDay, meetingTimeText, shortTime, weekdayDate } from '../meetings-display.util';
import {
  type AgendaProgress,
  type CalendarDay,
  type MeetingsView,
  type MonthRef,
  OVERVIEW_NOW,
  agendaProgress,
  gridRange,
  isoDay,
  matchesQuery,
  meetingsByDay,
  monthGrid,
  monthLabel,
  monthOf,
  openVoteOf,
  parseDay,
  shiftMonth,
  topsLabel,
  weekdayNames,
  weekdayShort,
} from '../meetings-overview.util';
import { MeetingsTimelineService } from '../meetings-timeline.service';
import { MeetingsViewSwitchComponent } from '../meetings-view-switch/meetings-view-switch.component';
import { beamerUrl } from '../../voting/beamer-link.util';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';

/** A cell shows this many meetings; the rest is "+n" and shows in the side panel. */
export const CELL_ENTRIES = 2;
/** The side panel lists this many upcoming meetings. */
export const UPCOMING_COUNT = 5;

/** One meeting of the selected day, as the side panel shows it. */
interface DayCard {
  meeting: Meeting;
  status: StatusView;
  time: string;
  progress: AgendaProgress | null;
  progressSegs: Seg[];
  vote: { voted: number; present: number; segs: Seg[] } | null;
  menu: RowMenuSection[];
}

/**
 * The calendar view of the meeting overview (board Sitzungen, variant C): a month grid,
 * Monday to Sunday, and a side panel.
 *
 * The grid marks today, shows the meetings of each day (time and a two-line title; a
 * live meeting in the accent) and selects a day on a click or with the arrow keys. The
 * toolbar moves a month back or on, or to today, and holds the search (on the loaded
 * month, in the browser only: it never asks the server), the Gremium chip and the
 * calendar subscription. "Today" moves on at midnight while the page stays open.
 *
 * The side panel shows the meetings of the selected day: status, "Sitzung öffnen", the
 * beamer (`canManage`), edit and delete in the ⋮ menu (`canManage`), and for a live
 * meeting the current item and the turnout of its open vote. Below it: the upcoming
 * meetings; a click selects their day.
 *
 * Data: `GET /meetings?dateFrom&dateTo` for the days of the grid, with the Gremium filter
 * of the overview. A phone has no calendar (the overview shows the list there).
 */
@Component({
  selector: 'app-meetings-calendar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    DateBlockComponent,
    FilterSelectComponent,
    ListItemComponent,
    RowMenuComponent,
    SearchPillComponent,
    SegBarComponent,
    StatusTextComponent,
    ScrollFadeDirective,
    MeetingsViewSwitchComponent,
    CalendarSubscribeComponent,
  ],
  host: { '[class.cal--wide]': 'wide()' },
  templateUrl: './meetings-calendar.component.html',
  styleUrl: './meetings-calendar.component.scss',
})
export class MeetingsCalendarComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  protected readonly timeline = inject(MeetingsTimelineService);
  private readonly dialogs = inject(MeetingDialogsService);

  /** "Neue Sitzung" shows (an admin, or `session.manage` in a Gremium). */
  readonly canCreate = input(false);

  readonly viewChange = output<MeetingsView>();
  readonly create = output<void>();

  /** Wide (>= 1200px): the panel beside the grid, and the page does not scroll. */
  readonly wide = mediaQuerySignal(MEDIA.wide);

  private readonly now = inject(OVERVIEW_NOW);
  /** The day of today. A timer moves it on at midnight (`scheduleMidnight`). */
  private readonly today = signal<Date>(this.now());
  readonly todayIso = computed(() => isoDay(this.today()));
  readonly month = signal<MonthRef>(monthOf(this.today()));
  readonly selectedDay = signal<string>(this.todayIso());
  private midnightTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly zone = inject(NgZone);

  /**
   * The search of the calendar. It filters the loaded month in the browser only; the
   * server search of the list (`MeetingsTimelineService.onSearch`) would read pages the
   * calendar never shows. It starts with the query of the list.
   */
  readonly query = signal(inject(MeetingsTimelineService).searchQuery());

  readonly weeks = computed<CalendarDay[][]>(() => monthGrid(this.month(), this.today()));
  readonly monthText = computed(() => monthLabel(this.month(), this.i18n.locale()));
  readonly weekdays = computed(() => weekdayNames(this.i18n.locale()));
  private readonly range = computed(() => gridRange(this.weeks()));

  /** The meetings of the days of the grid. */
  readonly items = signal<Meeting[]>([]);
  readonly loading = signal(true);
  readonly error = signal(false);
  private seq = 0;

  /** The meetings that match the search of the overview. */
  private readonly visible = computed(() => {
    const q = this.query();
    return this.items().filter((m) => matchesQuery(m, q));
  });
  readonly byDay = computed(() => meetingsByDay(this.visible()));

  readonly dayCards = computed<DayCard[]>(() =>
    (this.byDay().get(this.selectedDay()) ?? []).map((m) => this.card(m)),
  );
  /** "Di., 29.09.2026 · Heute". */
  readonly dayHeading = computed(() => {
    const day = weekdayDate(this.selectedDay(), this.i18n.formatLocale());
    return this.selectedDay() === this.todayIso()
      ? `${day} · ${this.i18n.translate('meetings.overview.today')}`
      : day;
  });

  /** The next planned meetings (the timeline of the overview), for "Anstehend". */
  readonly upcoming = computed(() => {
    const q = this.query();
    return this.timeline
      .upcomingItems()
      .filter((m) => m.status !== 'live' && matchesQuery(m, q))
      .slice(0, UPCOMING_COUNT);
  });

  /** The filter offers a choice only when the user reads more than one Gremium. */
  readonly showFilter = computed(() => this.timeline.filterGremien().length > 1);
  readonly filterLabel = computed(() => {
    const options = this.timeline.filterGremiumOptions();
    const value = this.timeline.gremiumFilter();
    // An unknown value (a Gremium that left the list) reads as "Alle Gremien".
    return options.find((o) => o.value === value)?.label ?? options[0].label;
  });

  constructor() {
    this.scheduleMidnight();
    inject(DestroyRef).onDestroy(() => {
      if (this.midnightTimer !== null) clearTimeout(this.midnightTimer);
    });

    // Read the days of the grid again when the month or the Gremium filter changes.
    effect(() => {
      const range = this.range();
      const gremium = this.timeline.gremiumFilter();
      untracked(() => this.load(range, gremium));
    });

    // A dialog changed or deleted a meeting: put it into the month.
    effect(() => {
      const change = this.timeline.lastChange();
      if (!change) return;
      untracked(() => {
        if (change.kind === 'updated') {
          this.items.update((list) =>
            list.map((m) => (m.id === change.meeting.id ? change.meeting : m)),
          );
        } else {
          this.items.update((list) => list.filter((m) => m.id !== change.id));
        }
      });
    });
  }

  prevMonth(): void {
    this.moveMonth(-1);
  }

  nextMonth(): void {
    this.moveMonth(1);
  }

  /** "Heute": the month of today, today selected. */
  goToday(): void {
    this.month.set(monthOf(this.today()));
    this.selectedDay.set(this.todayIso());
  }

  /**
   * Move "today" on at the next midnight, and again every night after. A timer of a
   * sleeping device fires late, so the clock is read again when it fires. The timer
   * runs outside the zone: a pending day-long timer would keep the app from "stable".
   */
  private scheduleMidnight(): void {
    const now = this.now();
    const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    this.midnightTimer = this.zone.runOutsideAngular(() =>
      setTimeout(
        () => {
          this.today.set(this.now());
          this.scheduleMidnight();
        },
        Math.max(next.getTime() - now.getTime(), 1000),
      ),
    );
  }

  /** Select a day; a day of the week before or after the month also shows its month. */
  selectDay(iso: string): void {
    this.selectedDay.set(iso);
    const ref = monthOf(parseDay(iso));
    const cur = this.month();
    if (ref.year !== cur.year || ref.month !== cur.month) this.month.set(ref);
  }

  /** An upcoming meeting: show its day. */
  showMeeting(m: Meeting): void {
    if (m.date) this.selectDay(m.date);
  }

  /**
   * The arrow keys move the selected day (a day left or right, a week up or down), Home
   * and End go to the start and the end of the week. The focus follows the day.
   */
  onGridKey(event: KeyboardEvent): void {
    const steps: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    };
    const day = parseDay(this.selectedDay());
    let delta = steps[event.key];
    if (event.key === 'Home') delta = -((day.getDay() + 6) % 7);
    if (event.key === 'End') delta = 6 - ((day.getDay() + 6) % 7);
    if (delta === undefined) return;
    event.preventDefault();
    const next = new Date(day.getFullYear(), day.getMonth(), day.getDate() + delta);
    this.selectDay(isoDay(next));
    afterNextRender(
      () => this.host.nativeElement.querySelector<HTMLElement>('.cal__day[tabindex="0"]')?.focus(),
      { injector: this.injector },
    );
  }

  open(m: Meeting): void {
    void this.router.navigate(['/meetings', m.id]);
  }

  beamer(m: Meeting): void {
    const url = this.router.serializeUrl(beamerUrl(this.router, m.id));
    window.open(url, '_blank', 'noopener');
  }

  onMenu(m: Meeting, item: RowMenuItem): void {
    if (item.id === 'edit') this.dialogs.openSettings(m);
    else this.dialogs.askDeleteMeeting(m);
  }

  meetingsOf(iso: string): Meeting[] {
    return this.byDay().get(iso) ?? [];
  }

  /** "18:00", or "Live" for a running meeting. */
  entryTime(m: Meeting): string {
    if (m.status === 'live') return this.i18n.translate('meetings.status.live');
    return shortTime(m.startTime);
  }

  /** The name of a day cell for a screen reader: "Dienstag, 29. September 2026, 1 Sitzung". */
  dayLabel(d: CalendarDay): string {
    const date = new Intl.DateTimeFormat(toFormatLocale(this.i18n.locale()), {
      dateStyle: 'full',
    }).format(parseDay(d.iso));
    const n = this.meetingsOf(d.iso).length;
    const count =
      n === 0
        ? this.i18n.translate('meetings.overview.dayNone')
        : n === 1
          ? this.i18n.translate('meetings.overview.dayOne')
          : this.i18n.translate('meetings.overview.dayMany', { n });
    const today = d.isToday ? `, ${this.i18n.translate('meetings.overview.today')}` : '';
    return `${date}${today}, ${count}`;
  }

  /** The meetings that a cell shows. */
  entries(iso: string): Meeting[] {
    return this.meetingsOf(iso).slice(0, CELL_ENTRIES);
  }

  /** "+2" below the entries of a full day. */
  more(iso: string): number {
    return Math.max(0, this.meetingsOf(iso).length - CELL_ENTRIES);
  }

  day(m: Meeting): string | null {
    return meetingDay(m);
  }

  status(m: Meeting): StatusView {
    return meetingStatus(m.status);
  }

  /** "Fr, 17:30" for a row of "Anstehend". */
  rowTime(m: Meeting): string {
    const start = shortTime(m.startTime);
    if (!m.date) return start;
    const weekday = weekdayShort(m.date, this.i18n.locale());
    return start ? `${weekday}, ${start}` : weekday;
  }

  tops(m: Meeting): string {
    return topsLabel(m.agendaItemCount ?? 0, (k, p) => this.i18n.translate(k, p));
  }

  private moveMonth(delta: number): void {
    const next = shiftMonth(this.month(), delta);
    this.month.set(next);
    // Keep the day of the month where it exists, else the last day of the new month.
    const cur = parseDay(this.selectedDay());
    const last = new Date(next.year, next.month + 1, 0).getDate();
    this.selectedDay.set(isoDay(new Date(next.year, next.month, Math.min(cur.getDate(), last))));
  }

  private card(m: Meeting): DayCard {
    const t = meetingTimeText(m, this.i18n.locale());
    const time = t.since ? this.i18n.translate('meetings.list.since', { time: t.text }) : t.text;
    const progress = agendaProgress(m);
    const vote = m.status === 'live' ? openVoteOf(m) : null;
    const menu: RowMenuSection[] = m.canManage
      ? [
          {
            items: [
              { id: 'edit', label: this.i18n.translate('meetings.settings.title'), icon: 'edit' },
              {
                id: 'delete',
                label: this.i18n.translate('meetings.delete.title'),
                icon: 'trash',
                danger: true,
              },
            ],
          },
        ]
      : [];
    return {
      meeting: m,
      status: meetingStatus(m.status),
      time,
      progress,
      progressSegs: progress ? [{ value: progress.position, tone: 'filled' }] : [],
      vote: vote
        ? { voted: vote.voted, present: vote.present, segs: [{ value: vote.voted, tone: 'filled' }] }
        : null,
      menu,
    };
  }

  /** The translated text of a key, for templates that build a label. */
  t(key: TranslationKey, params?: Record<string, string | number>): string {
    return this.i18n.translate(key, params);
  }

  private load(range: { from: string; to: string }, gremium: string): void {
    const seq = ++this.seq;
    this.loading.set(true);
    this.api.listMeetings(gremium || undefined, range).subscribe({
      next: (items) => {
        if (seq !== this.seq) return;
        this.items.set(items);
        this.error.set(false);
        this.loading.set(false);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.items.set([]);
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }
}
