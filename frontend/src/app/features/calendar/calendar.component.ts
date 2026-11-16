import { FeatureService } from '@core/features/feature.service';
import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  NgZone,
  type OnDestroy,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import {
  type Appointment,
  CalendarApiService,
  type CalendarEntry,
  type CalendarGremium,
  type ExternalEntry,
  PublicCalendarApiService,
} from '@core/api/calendar.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { dayMonth, dayMonthYear, isoDay, monthYear, parseDay, weekdayDate } from '@shared/date-format';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { isRefreshItem, refreshMenuSection, reloadLikePull } from '@shared/ui/pull-refresh/refresh-menu';
import {
  ButtonComponent,
  EmptyStateComponent,
  FabComponent,
  FilterSelectComponent,
  IconComponent,
  ListGroupComponent,
  ListItemComponent,
  MEDIA,
  PageFrame,
  PageHeaderComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SearchPillComponent,
  SegmentedComponent,
  SkeletonComponent,
  StatusTextComponent,
  StickyBarComponent,
  ToastService,
  liveSearch,
  mediaQuery,
} from '@stupa-makers/ui-kit';
import { useNoindex } from '../public-protocols/public-protocols.util';
import { CalendarSubscribeComponent } from '../meetings/calendar-subscribe/calendar-subscribe.component';
import { AppointmentDetailComponent } from './appointment-detail/appointment-detail.component';
import { ExternalEntryComponent } from './external-entry/external-entry.component';
import { type PublicEntry, PublicEntryComponent } from './public-entry/public-entry.component';
import { AppointmentDialogComponent } from './appointment-dialog/appointment-dialog.component';
import {
  CALENDAR_NOW,
  type CalendarDay,
  type MonthRef,
  gridRange,
  monthGrid,
  monthOf,
  shiftDay,
  shiftMonth,
  weekOf,
  weekdayNames,
} from './calendar-grid.util';
import { CalendarWeekComponent } from './calendar-week/calendar-week.component';
import {
  type CalendarView,
  type DayRange,
  FILTER_KINDS,
  LIST_CHUNK,
  answerKey,
  answerKind,
  dayList,
  daysBetween,
  entryIcon,
  entryLink,
  entryOf,
  entryTime,
  kindKey,
  mergeEntries,
  monthRows,
  onDay,
  readStoredView,
  storeView,
  visibleEntries,
} from './calendar.util';

/** The steps of the arrow keys in the month grid, in days. */
const KEY_STEPS: Readonly<Record<string, number>> = {
  ArrowLeft: -1,
  ArrowRight: 1,
  ArrowUp: -7,
  ArrowDown: 7,
};

/**
 * The Kalender (`/calendar`, § 000710-000714, 000726-000728, 000737): the meetings, the
 * due cards, the Events and the Termine that the person reads, in one page.
 *
 * A desktop shows the month grid or the week view (`Woche | Monat`, kept per browser)
 * and beside it the entries of the picked day as pressable cards. A phone shows the days
 * with entries as a list from today on and loads earlier and later days on demand. A
 * meeting and a card open their own page, a Termin opens in a dialog.
 *
 * The filters by kind and by Gremium work in the browser on the loaded entries; "Nur
 * meine" asks the server, because the rule of "mine" is a rule of each module. The
 * search asks the server and finds entries of every month: a hit shows its month and
 * picks its day (on a phone it opens the entry). `?appointment=<id>` opens a Termin,
 * so the link of a mail lands on it.
 *
 * The route `/public-calendar` (route data `public`, § 000731-000733) shows the same
 * views without a sign-in. It reads the public API, which gives only the public Termine
 * and the meetings of the Gremien with public protocols. It has the filter by Gremium
 * and no other filter, no button that creates a Termin, and an entry opens its public
 * fields in a dialog. "Kalender abonnieren" shows the address of the feed without a token.
 */
@Component({
  selector: 'app-calendar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    AppointmentDetailComponent,
    AppointmentDialogComponent,
    ButtonComponent,
    CalendarSubscribeComponent,
    CalendarWeekComponent,
    EmptyStateComponent,
    ExternalEntryComponent,
    FabComponent,
    FilterSelectComponent,
    IconComponent,
    ListGroupComponent,
    ListItemComponent,
    LoadErrorComponent,
    PageHeaderComponent,
    PublicEntryComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    SegmentedComponent,
    SkeletonComponent,
    StatusTextComponent,
    StickyBarComponent,
    TranslatePipe,
  ],
  host: { '[class.cal--wide]': 'wide()' },
  templateUrl: './calendar.component.html',
  styleUrl: './calendar.component.scss',
})
export class CalendarComponent implements OnDestroy {
  private readonly api = inject(CalendarApiService);
  private readonly features = inject(FeatureService);
  private readonly publicApi = inject(PublicCalendarApiService);
  private readonly client = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);
  private readonly frame = inject(PageFrame);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);
  private readonly zone = inject(NgZone);
  private readonly now = inject(CALENDAR_NOW);

  /** The public calendar: the page without a sign-in. */
  readonly isPublic = this.route.snapshot.data['public'] === true;
  readonly titleKey = this.isPublic ? 'calendar.public.title' : 'nav.calendar';
  /** The address of the public feed, which needs no token. */
  readonly publicFeed = this.isPublic ? this.publicApi.feedUrl() : null;

  readonly phone = mediaQuery(MEDIA.phone);
  /** Wide (>= 1200px): the cards beside the grid, and the page does not scroll. */
  readonly wide = mediaQuery(MEDIA.wide);

  /** The day of today. A timer moves it on at midnight (`scheduleMidnight`). */
  private readonly today = signal<Date>(this.now());
  readonly todayIso = computed(() => isoDay(this.today()));
  private midnightTimer: ReturnType<typeof setTimeout> | null = null;

  readonly view = signal<CalendarView>(readStoredView());
  readonly month = signal<MonthRef>(monthOf(this.today()));
  readonly selectedDay = signal<string>(this.todayIso());

  readonly week = computed(() => weekOf(this.selectedDay(), this.today()));
  readonly weeks = computed<readonly (readonly CalendarDay[])[]>(() =>
    this.view() === 'week' ? [this.week()] : monthGrid(this.month(), this.today()),
  );
  readonly weekdays = computed(() => weekdayNames(this.i18n.formatLocale()));
  /** "November 2026", or "09.11. – 15.11.2026" for a week. */
  readonly heading = computed(() => {
    const locale = this.i18n.formatLocale();
    if (this.view() === 'month') return monthYear(new Date(this.month().year, this.month().month, 1), locale);
    const days = this.week();
    return `${dayMonth(days[0].iso, locale)} – ${dayMonthYear(days[6].iso, locale)}`;
  });
  readonly viewOptions = computed(() => [
    { value: 'week', label: this.i18n.translate('calendar.view.week') },
    { value: 'month', label: this.i18n.translate('calendar.view.month') },
  ]);

  /** The days that the phone list holds: from today on, wider with each "load more". */
  private readonly listRanges = signal<readonly DayRange[]>([this.chunkFrom(this.todayIso())]);
  /** The days to read. A pick of a day inside the grid keeps the range, so it reads nothing. */
  private readonly ranges = computed<readonly DayRange[]>(
    () => (this.phone() ? this.listRanges() : [gridRange(this.weeks())]),
    { equal: (a, b) => a.length === b.length && a.every((r, i) => r.from === b[i].from && r.to === b[i].to) },
  );

  readonly kinds = signal<readonly string[]>([]);
  readonly gremium = signal('');
  readonly mine = signal('');
  readonly kindOptions = computed(() =>
    FILTER_KINDS.filter(
      (kind) =>
        (kind !== 'meeting' || this.features.isOn('meetings')) &&
        (kind !== 'card' || this.features.isOn('todos')),
    ).map((kind) => ({ value: kind, label: this.i18n.translate(`calendar.kind.${kind}`) })),
  );
  readonly mineOptions = computed(() => [
    { value: '', label: this.i18n.translate('calendar.filter.all') },
    { value: 'mine', label: this.i18n.translate('calendar.filter.mine') },
  ]);
  private readonly gremien = signal<readonly CalendarGremium[]>([]);
  readonly gremiumOptions = computed(() => [
    { value: '', label: this.i18n.translate('calendar.filter.allGremien') },
    ...this.gremien().map((g) => ({ value: g.id, label: g.name })),
  ]);
  readonly gremiumText = computed(
    () => this.gremiumOptions().find((o) => o.value === this.gremium())?.label ?? '',
  );

  readonly items = signal<readonly CalendarEntry[]>([]);
  readonly loading = signal(true);
  readonly error = signal(false);
  /** The first read is out: the page draws the shape of its rows. */
  readonly firstLoad = computed(() => this.loading() && !this.items().length);
  private seq = 0;

  readonly visible = computed(() => visibleEntries(this.items(), this.kinds(), this.gremium()));
  readonly rows = computed(() => monthRows(this.visible(), this.weeks()));
  readonly dayEntries = computed(() => onDay(this.visible(), this.selectedDay()));
  /** "Mi, 11.11.2026 · Heute": the name of the cards column for a screen reader. */
  readonly dayHeading = computed(() => this.dayText(this.selectedDay()));
  /** The days of the phone list with their entries. */
  readonly days = computed(() =>
    dayList(
      this.visible(),
      this.listRanges().flatMap((r) => daysBetween(r.from, r.to)),
    ).map((day) => ({ ...day, label: this.dayText(day.iso) })),
  );

  readonly query = signal('');
  readonly hits = signal<readonly CalendarEntry[]>([]);
  /** The search answered for the text in the field, so "Keine Treffer" is true. */
  readonly searched = signal(false);
  readonly activeHit = signal(0);
  readonly searching = computed(() => this.query().trim().length >= 2);
  private readonly search = liveSearch<readonly CalendarEntry[]>({
    run: (q) => (this.isPublic ? this.publicApi.search(q) : this.api.search(q)),
    result: (hits) => {
      this.hits.set(hits);
      this.activeHit.set(0);
      this.searched.set(true);
    },
    reset: () => this.clearHits(),
    error: () => this.clearHits(),
  });

  /** The Termin of the detail dialog. */
  readonly detail = signal<Appointment | null>(null);
  readonly detailOpen = signal(false);
  /** The external entry of the read-only dialog. */
  readonly external = signal<ExternalEntry | null>(null);
  readonly externalOpen = signal(false);
  /** The entry of the dialog of the public calendar. */
  readonly publicEntry = signal<PublicEntry | null>(null);
  readonly publicOpen = signal(false);
  /** The Termin of the form dialog, or null for a new one. */
  readonly editing = signal<Appointment | null>(null);
  readonly formOpen = signal(false);

  private readonly linked = toSignal(this.route.queryParamMap.pipe(map((q) => q.get('appointment'))), {
    initialValue: null,
  });

  readonly phoneMenu = computed<RowMenuSection[]>(() => [
    { items: [{
          id: 'calendar',
          label: this.i18n.translate(this.isPublic ? 'calendar.public.subscribe' : 'meetings.overview.subscribe'),
          icon: 'cal',
        },] },
    refreshMenuSection((key) => this.i18n.translate(key)),
  ]);

  readonly icon = entryIcon;
  readonly kindKey = kindKey;
  readonly answerKey = answerKey;
  readonly answerKind = answerKind;

  constructor() {
    this.scheduleMidnight();
    if (this.isPublic) useNoindex();
    inject(DestroyRef).onDestroy(() => {
      if (this.midnightTimer !== null) clearTimeout(this.midnightTimer);
    });
    (this.isPublic ? this.publicApi.gremien() : this.client.listMeetingFilterGremien()).subscribe({
      next: (list) => this.gremien.set(list),
      error: () => this.gremien.set([]),
    });

    effect(() => this.frame.fill.set(this.wide()));
    effect(() => {
      const ranges = this.ranges();
      const mine = this.mine() === 'mine';
      untracked(() => this.load(ranges, mine));
    });
    effect(() => {
      const id = this.linked();
      if (id && !this.isPublic) untracked(() => this.openAppointment(id));
    });
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
  }

  setView(value: string | null): void {
    const view: CalendarView = value === 'week' ? 'week' : 'month';
    this.view.set(view);
    storeView(view);
  }

  /** A month back or on in the month view, a week in the week view. */
  step(delta: number): void {
    if (this.view() === 'week') return this.selectDay(shiftDay(this.selectedDay(), 7 * delta));
    const next = shiftMonth(this.month(), delta);
    const day = parseDay(this.selectedDay())?.getDate() ?? 1;
    const last = new Date(next.year, next.month + 1, 0).getDate();
    this.month.set(next);
    this.selectedDay.set(isoDay(new Date(next.year, next.month, Math.min(day, last))));
  }

  /** "Heute": the month of today, today picked. */
  goToday(): void {
    this.selectDay(this.todayIso());
  }

  /** Pick a day. A day of another month also shows its month. */
  selectDay(iso: string): void {
    const day = parseDay(iso);
    if (!day) return;
    this.selectedDay.set(iso);
    this.month.set(monthOf(day));
  }

  /**
   * The arrow keys move the picked day (a day left or right, a week up or down), Home
   * and End go to the start and the end of the week. The focus follows the day.
   */
  onGridKey(event: KeyboardEvent): void {
    const day = parseDay(this.selectedDay());
    if (!day) return;
    const weekday = (day.getDay() + 6) % 7;
    const delta: number | undefined =
      event.key === 'Home' ? -weekday : event.key === 'End' ? 6 - weekday : KEY_STEPS[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    this.selectDay(shiftDay(this.selectedDay(), delta));
    afterNextRender(
      () => this.host.nativeElement.querySelector<HTMLElement>('.cal__day[tabindex="0"]')?.focus(),
      { injector: this.injector },
    );
  }

  /** The name of a day cell for a screen reader: "Mittwoch, 11. November 2026, Heute, 2 Einträge". */
  dayLabel(day: CalendarDay, count: number): string {
    const date = parseDay(day.iso);
    const text = date
      ? new Intl.DateTimeFormat(this.i18n.formatLocale(), { dateStyle: 'full' }).format(date)
      : day.iso;
    const today = day.isToday ? `, ${this.i18n.translate('meetings.overview.today')}` : '';
    const entries =
      count === 0
        ? this.i18n.translate('calendar.day.none')
        : count === 1
          ? this.i18n.translate('calendar.day.one')
          : this.i18n.translate('calendar.day.many', { n: count });
    return `${text}${today}, ${entries}`;
  }

  /** "14:00 – 15:30", or the days of an entry over several days. */
  time(e: CalendarEntry): string {
    return entryTime(e, this.i18n.formatLocale());
  }

  /** "Mi, 11.11.2026 · 14:00": the day and the time of a search hit. */
  hitWhen(e: CalendarEntry): string {
    const day = weekdayDate(e.startsOn, this.i18n.formatLocale());
    const time = e.startsOn === e.endsOn ? this.time(e) : '';
    return time ? `${day} · ${time}` : day;
  }

  onQuery(text: string): void {
    this.query.set(text);
    this.searched.set(false);
    this.search.set(text);
  }

  /** The keys of the search: the arrows move the mark, Enter takes the hit, Escape ends it. */
  onSearchKey(event: KeyboardEvent): void {
    const hits = this.hits();
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp': {
        if (!hits.length) return;
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : -1;
        this.activeHit.update((i) => (i + step + hits.length) % hits.length);
        return;
      }
      case 'Enter': {
        const hit = hits[this.activeHit()];
        if (hit) this.jump(hit);
        return;
      }
      case 'Escape':
        if (this.query()) this.endSearch();
        return;
      default:
        return;
    }
  }

  /** Take a hit: show its month and pick its day. A phone has no grid, so it opens the entry. */
  jump(e: CalendarEntry): void {
    this.endSearch();
    if (this.phone()) return this.openEntry(e);
    this.selectDay(e.startsOn);
  }

  /** A meeting and a card open their own page, a Termin and an external entry a dialog. */
  openEntry(e: CalendarEntry): void {
    if (this.isPublic) return this.openPublic(e);
    const link = entryLink(e);
    if (link) void this.router.navigate([...link.commands], { queryParams: link.queryParams });
    else if (e.kind === 'external') this.openExternal(e.id);
    else this.openAppointment(e.id);
  }

  createAppointment(): void {
    this.editing.set(null);
    this.formOpen.set(true);
  }

  editAppointment(a: Appointment): void {
    this.detailOpen.set(false);
    this.editing.set(a);
    this.formOpen.set(true);
  }

  closeDetail(): void {
    this.detailOpen.set(false);
    if (this.linked()) {
      void this.router.navigate([], {
        relativeTo: this.route,
        queryParams: { appointment: null },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
    }
  }

  /** A saved Termin shows at once on its day, then the page reads the entries again. */
  onSaved(a: Appointment): void {
    this.formOpen.set(false);
    this.items.update((list) => mergeEntries(list, [entryOf(a, a.gremien, a.myAnswer)]));
    if (!this.phone()) this.selectDay(a.startsOn);
    this.reload();
  }

  onAnswered(a: Appointment): void {
    this.detail.set(a);
    this.items.update((list) =>
      list.map((e) => (e.kind === 'appointment' && e.id === a.id ? { ...e, myAnswer: a.myAnswer } : e)),
    );
  }

  onRemoved(a: Appointment): void {
    this.closeDetail();
    this.items.update((list) => list.filter((e) => !(e.kind === 'appointment' && e.id === a.id)));
  }

  /** Load the days before the first day of the phone list. */
  loadEarlier(): void {
    const first = this.listRanges()[0].from;
    this.listRanges.update((list) => [
      { from: shiftDay(first, -LIST_CHUNK), to: shiftDay(first, -1) },
      ...list,
    ]);
  }

  /** Load the days after the last day of the phone list. */
  loadLater(): void {
    const ranges = this.listRanges();
    this.listRanges.update((list) => [...list, this.chunkFrom(shiftDay(ranges[ranges.length - 1].to, 1))]);
  }

  onPhoneMenu(item: RowMenuItem, abo: CalendarSubscribeComponent): void {
    if (isRefreshItem(item)) return reloadLikePull(() => this.reload());
    if (item.id === 'calendar') abo.open();
  }

  /** Read the entries again, after a failed read or a change. */
  reload(): void {
    this.load(this.ranges(), this.mine() === 'mine');
  }

  private chunkFrom(from: string): DayRange {
    return { from, to: shiftDay(from, LIST_CHUNK - 1) };
  }

  private dayText(iso: string): string {
    const day = weekdayDate(iso, this.i18n.formatLocale());
    return iso === this.todayIso() ? `${day} · ${this.i18n.translate('meetings.overview.today')}` : day;
  }

  private endSearch(): void {
    this.query.set('');
    this.search.sync('');
    this.clearHits();
  }

  private clearHits(): void {
    this.hits.set([]);
    this.activeHit.set(0);
    this.searched.set(false);
  }

  private openExternal(id: string): void {
    this.api.externalEntry(id).subscribe({
      next: (entry) => {
        this.external.set(entry);
        this.externalOpen.set(true);
      },
      error: () => this.toast.error(this.i18n.translate('calendar.external.loadFailed')),
    });
  }

  /** Read the public fields of a meeting or a Termin and show them. */
  private openPublic(e: CalendarEntry): void {
    const read =
      e.kind === 'meeting'
        ? this.publicApi.meeting(e.id).pipe(map((data): PublicEntry => ({ kind: 'meeting', data })))
        : this.publicApi.appointment(e.id).pipe(map((data): PublicEntry => ({ kind: 'appointment', data })));
    read.subscribe({
      next: (entry) => {
        this.publicEntry.set(entry);
        this.publicOpen.set(true);
      },
      error: () => this.toast.error(this.i18n.translate('calendar.external.loadFailed')),
    });
  }

  private openAppointment(id: string): void {
    this.api.appointment(id).subscribe({
      next: (a) => {
        this.detail.set(a);
        this.detailOpen.set(true);
      },
      error: () => this.toast.error(this.i18n.translate('calendar.toast.loadFailed')),
    });
  }

  private load(ranges: readonly DayRange[], mine: boolean): void {
    this.seq += 1;
    const seq = this.seq;
    this.loading.set(true);
    const read = (r: DayRange) =>
      this.isPublic ? this.publicApi.entries(r.from, r.to) : this.api.entries(r.from, r.to, mine);
    forkJoin(ranges.map(read)).subscribe({
      next: (parts) => {
        if (seq !== this.seq) return;
        this.items.set(parts.reduce<readonly CalendarEntry[]>(mergeEntries, []));
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
}
