import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { catchError, map, of, startWith, Subject, switchMap, throwError, type Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { TodosApiService, type TodoMineItem } from '@core/api/todos.service';
import { FeatureService } from '@core/features/feature.service';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { formatMoment } from '@core/i18n/localized-date.pipe';
import {
  calendarDaysSince,
  clock,
  daysUntil,
  isoDay,
  shortDay,
  shortTime,
  weekdayName,
} from '@shared/date-format';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import { TodoDueComponent } from '../../features/todos/card-facts/todo-due.component';
import { dueInfo } from '../../features/todos/todos.util';
import type {
  ApplicationListItem,
  ApplicationType,
  IsoDateTime,
  Meeting,
  MeetingPage,
  Page,
  Uuid,
} from '@core/api/models';
import {
  AvatarComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DateBlockComponent,
  EmptyStateComponent,
  IconComponent,
  ListItemComponent,
  MEDIA,
  mediaQuery,
  ScrollFadeDirective,
  SearchPillComponent,
  SegBarComponent,
  SideSheetComponent,
  SkeletonComponent,
  type StatusKind,
  StatusTextComponent,
  type TabItem,
  TabPageDirective,
  TabPagerComponent,
  TabsComponent,
  FabComponent,
  PageHeaderComponent,
  SectionComponent,
  StickyBarComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../layout/breadcrumbs.component';
import { flowColorKind } from '@shared/status-kind.util';
import { FabLinkDirective, CommandPalette } from '@stupa-makers/ui-kit/shell';
import { AppAccountMenuComponent } from '../../layout/account-menu/account-menu.component';
import { NavService } from '../../layout/nav.service';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';

/** The rows a tab loads. The list scrolls inside its pane; "Alle … öffnen" shows the rest. */
const ROWS = 25;
/** The rows of a tab on a phone, where the page scrolls. */
const PHONE_ROWS = 5;
/** Upcoming meetings in the sheet: three, five on a very wide screen, two on a phone. */
const MEETINGS = 3;
const MEETINGS_XL = 5;
const PHONE_MEETINGS = 2;
/** Meetings the timeline loads: the live ones and enough planned ones for every width. */
const TIMELINE_LIMIT = 8;

/** The tabs of the work list. The URL keeps the choice as `?tab=`. */
export type WorkTab = 'tasks' | 'mine';
const TABS: readonly WorkTab[] = ['tasks', 'mine'];

/** A row of "Offene Aufgaben" or "Meine Anträge". */
export interface WorkRow {
  readonly id: Uuid;
  readonly link: readonly string[];
  readonly title: string;
  readonly statusLabel: string;
  readonly statusKind: StatusKind;
  /** "4 Tage" (tasks) or "28.08." (own applications). */
  readonly since: string;
  /** The exact moment, for the tooltip. */
  readonly sinceTitle: string | null;
}

/** A live meeting in the sheet. */
export interface LiveCard {
  readonly meeting: Meeting;
  /** "seit 18:04 · Du führst Protokoll". */
  readonly sub: string;
  readonly now: {
    readonly position: number;
    readonly title: string;
    readonly count: number;
  } | null;
  /** The open vote of the meeting and the own state in it, or null without one. */
  readonly vote: { readonly ballot: 'cast' | 'pending' | null } | null;
}

/** A planned meeting in the sheet. */
export interface UpcomingRow {
  readonly meeting: Meeting;
  /** "Du vertrittst Konrad Pfeiffer" while a delegation of the user is on it. */
  readonly note: string | null;
  /** "Fr, 17:30". */
  readonly when: string;
}

type Loaded<T> = T | null | undefined;

/** A request as a signal, and the trigger that sends it again. */
interface Load<T> {
  readonly value: () => Loaded<T>;
  readonly reload: () => void;
}

/**
 * The start page of a signed-in person (variant B "Arbeitsliste + Seitenleiste").
 *
 * Left: the search pill, the greeting, and ONE work list with the
 * tabs "Offene Aufgaben" and "Meine Anträge". The tabs show no counts (spec 000560),
 * and the URL keeps the choice (`?tab=`). Each tab is a table with real columns; a row
 * opens its detail page, and "Alle … öffnen" opens the full list. Wide, "Antrag stellen"
 * is a floating button at the foot of the list column; narrower, at the foot of the page.
 *
 * Right: the sheet "Heute" with the live meeting (progress, the own vote state, "Live
 * beitreten") and the next meetings (with "Du vertrittst …" from the delegations).
 *
 * Wide, the page is a pane page: the document does not scroll, the list and the sheet
 * scroll inside themselves and reach down to the pane gap, because the page has no
 * footer. Narrow and on a phone the page scrolls: the "Heute" band comes first, then the
 * work list. A phone shows the rows as list rows and a floating "Antrag" button.
 * On a phone the search bar with the avatar button is a sticky bar: it stays pinned at the
 * top while the page scrolls, as frosted glass like the bar of a list page.
 *
 * A person without tasks and without own applications sees the empty tab next to the
 * card "Antrag stellen" with the active application types.
 *
 * No request shows the global loading overlay: each block shows its own skeleton, empty
 * or error state.
 *
 * It imports the shared blocks by path, not through the `@shared/ui` barrel, so this lazy
 * chunk takes only the blocks it uses.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SectionComponent,
    LoadErrorComponent,
    NgTemplateOutlet,
    RouterLink,
    IconComponent,
    TodoDueComponent,
    TranslatePipe,
    TabPageDirective,
    TabPagerComponent,
    TabsComponent,
    DataTableComponent,
    CellDirective,
    AvatarComponent,
    DateBlockComponent,
    EmptyStateComponent,
    FabComponent,
    FabLinkDirective,
    ListItemComponent,
    PageHeaderComponent,
    BreadcrumbsComponent,
    SearchPillComponent,
    SegBarComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    ScrollFadeDirective,
    StickyBarComponent,
    AppAccountMenuComponent,
  ],
  host: {
    '[class.dash--phone]': 'phone()',
    '[class.dash--wide]': 'wide()',
    '[class.pane-page]': 'wide()',
    '[class.dash--noToday]': '!todayShown()',
  },
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  /** The search pill at the top opens the global search. */
  protected readonly palette = inject(CommandPalette);
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly nav = inject(NavService);
  private readonly features = inject(FeatureService);
  private readonly delegationsApi = inject(DelegationsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  /** Phone width (<= 768px): compact head, the band first, list rows, floating button. */
  readonly phone = mediaQuery(MEDIA.phone);
  /** Wide (>= 1200px): the list and the sheet side by side, no page scroll. */
  readonly wide = mediaQuery(MEDIA.wide);
  /** A very wide screen shows more meetings in the sheet. */
  private readonly extraWide = mediaQuery('(min-width: 1680px)');
  /** The account sheet of the compact phone head. */
  readonly accountOpen = signal(false);

  private readonly tasksLoad = this.load(this.api.listTasks());
  private readonly tasks = this.tasksLoad.value;
  /** The own applications (`mine=true`), newest status change first: the date the rows
   *  show. `mine` forces the owner filter, also for a reader with `application.read`. */
  private readonly mineLoad = this.load<Page<ApplicationListItem>>(
    this.api.listApplications({ mine: true, limit: ROWS, sort: 'stateSince', order: 'desc' }),
  );
  private readonly mine = this.mineLoad.value;
  /** The live and the next meetings. The timeline already scopes and sorts them. */
  private readonly timeline = this.load<MeetingPage>(
    this.features.isOn('meetings')
      ? this.api.listMeetingsTimeline({ direction: 'upcoming', limit: TIMELINE_LIMIT })
      : throwError(() => null),
  ).value;
  /** `Sitzungen` is on: the sheet shows the meetings. */
  readonly meetingsOn = computed(() => this.features.isOn('meetings'));
  private readonly delegationsRaw = toSignal(
    (this.features.isOn('meetings') ? this.delegationsApi.list() : of([] as Delegation[])).pipe(
      catchError(() => of([] as Delegation[])),
    ),
    { initialValue: [] as Delegation[] },
  );
  private readonly types = toSignal(
    this.api.applicationTypes({ quiet: true }).pipe(catchError(() => of([] as ApplicationType[]))),
    { initialValue: [] as ApplicationType[] },
  );

  /** There is no raw id as a fallback, because the types load late or can fail. */
  private readonly typeName = computed(() => {
    const names = new Map(this.types().map((t) => [t.id, t.name]));
    return (id: Uuid): string => names.get(id) ?? '';
  });

  /** The active application types, for the card "Antrag stellen" of a new user. */
  readonly applyTypes = computed(() => this.types().filter((t) => t.active));

  /** The first word of the display name: "Willkommen, Mara". */
  readonly firstName = computed(() => this.auth.displayName().trim().split(/\s+/)[0]);

  /** The open tab, from `?tab=`. An unknown value opens the first tab. */
  readonly tab = toSignal(
    this.route.queryParamMap.pipe(
      map((params) => {
        const value = params.get('tab');
        return TABS.find((t) => t === value) ?? 'tasks';
      }),
    ),
    { initialValue: 'tasks' as WorkTab },
  );

  readonly tabs = computed<TabItem[]>(() => {
    const short = this.phone();
    return [
      { id: 'tasks', label: this.i18n.translate(short ? 'dashboard.tab.tasksShort' : 'dashboard.tasks.title') },
      { id: 'mine', label: this.i18n.translate(short ? 'dashboard.tab.mineShort' : 'dashboard.applications.title') },
    ];
  });

  setTab(id: string | null): void {
    const tab = TABS.find((t) => t === id) ?? 'tasks';
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { tab: tab === 'tasks' ? null : tab },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** `true` while the request of the open tab has not answered. */
  readonly tabLoading = computed(() => this.loadingOf(this.tab()));
  /** `true` when the request of the open tab failed. */
  readonly tabError = computed(() => this.errorOf(this.tab()));

  /**
   * The state of one tab. On a phone each tab has its own page beside the others, so a
   * swipe shows the next tab with its rows before it is the open tab.
   */
  loadingOf(tab: string): boolean {
    return this.sourceOf(tab) === undefined;
  }

  errorOf(tab: string): boolean {
    return this.sourceOf(tab) === null;
  }

  rowsOf(tab: string): WorkRow[] {
    return tab === 'mine' ? this.mineRows() : this.taskRows();
  }

  /** The rows of the tab are empty (and loaded). */
  emptyOf(tab: string): boolean {
    return !this.loadingOf(tab) && !this.errorOf(tab) && this.rowsOf(tab).length === 0;
  }

  /** "Alle … öffnen" of the tab. */
  allLinkOf(tab: string): { key: TranslationKey; link: string; query: Record<string, string> | null } {
    return tab === 'mine'
      ? { key: 'dashboard.all.mine', link: '/applications', query: { mine: 'true' } }
      : { key: 'dashboard.all.tasks', link: '/tasks', query: null };
  }

  private sourceOf(tab: string): Loaded<unknown> {
    return tab === 'mine' ? this.mine() : this.tasks();
  }

  private readonly rowCap = computed(() => (this.phone() ? PHONE_ROWS : ROWS));

  readonly taskRows = computed<WorkRow[]>(() =>
    (this.tasks() ?? []).slice(0, this.rowCap()).map((item) => {
      const at = item.stateSince ?? item.updatedAt;
      return this.workRow(item, ['/tasks', item.id], this.waited(at), at);
    }),
  );

  readonly mineRows = computed<WorkRow[]>(() =>
    (this.mine()?.items ?? []).slice(0, this.rowCap()).map((item) => {
      const at = item.stateSince ?? item.updatedAt;
      return this.workRow(item, ['/applications', item.id], this.shortDay(at), at);
    }),
  );

  /** The rows of the open tab are empty (and loaded). */
  readonly tabEmpty = computed(() => this.emptyOf(this.tab()));

  /** No own application yet: the empty tab gets the card "Antrag stellen" beside it. */
  readonly newUser = computed(() => this.mine()?.total === 0);


  /** The columns of "Offene Aufgaben" and "Meine Anträge". */
  readonly workColumns = computed<ColumnDef[]>(() => [
    { key: 'title', label: this.i18n.translate('dashboard.col.application'), card: 'title' },
    { key: 'status', label: this.i18n.translate('dashboard.col.status'), width: '9rem' },
    {
      key: 'since',
      label: this.i18n.translate(this.tab() === 'mine' ? 'dashboard.col.since' : 'dashboard.col.waiting'),
      width: '6.5rem',
    },
    { key: 'go', label: '', align: 'end', width: '3.25rem' },
  ]);

  readonly rowKey = (row: unknown): unknown => (row as { id: Uuid }).id;

  /** A row of the table opens its detail page. */
  openRow(row: unknown): void {
    void this.router.navigate((row as WorkRow).link as string[]);
  }

  private workRow(
    item: ApplicationListItem,
    link: string[],
    since: string,
    at: IsoDateTime,
  ): WorkRow {
    const type = this.typeName()(item.typeId);
    return {
      id: item.id,
      link,
      title: item.title?.trim() || type || this.i18n.translate('applications.list.untitled'),
      statusLabel: item.state?.label ?? '',
      statusKind: flowColorKind(item.state?.color),
      since,
      sinceTitle: this.longMoment(at),
    };
  }

  private ballotOf(cast: boolean, canCast: boolean): 'cast' | 'pending' | null {
    if (cast) return 'cast';
    return canCast ? 'pending' : null;
  }

  /** "Di, 29.09.2026". */

  readonly meetingsLoading = computed(() => this.meetingsOn() && this.timeline() === undefined);
  /** The meetings page is open to the user: the sheet links to it. */
  readonly canSeeMeetings = computed(() => this.nav.meetingsVisible());

  private readonly meetings = computed(() => this.timeline()?.items ?? []);

  readonly live = computed<LiveCard[]>(() =>
    this.meetings()
      .filter((m) => m.status === 'live')
      .map((m) => this.liveCard(m)),
  );

  /** The planned meetings, in the order of the timeline. */
  private readonly planned = computed(() => this.meetings().filter((m) => m.status === 'planned'));

  readonly upcoming = computed<UpcomingRow[]>(() => {
    const cap = this.phone() ? PHONE_MEETINGS : this.extraWide() ? MEETINGS_XL : MEETINGS;
    return this.planned()
      .slice(0, cap)
      .map((m) => ({ meeting: m, note: this.delegationNote(m.id), when: this.plannedLabel(m) }));
  });

  private readonly todos = inject(TodosApiService);
  private readonly myCards = toSignal(
    (this.features.isOn('todos')
      ? this.todos.mine().pipe(map((m) => m.items))
      : of([] as TodoMineItem[])
    ).pipe(
      catchError(() => of([] as TodoMineItem[])),
    ),
    { initialValue: [] as readonly TodoMineItem[] },
  );
  /** "Fällige To-Dos" (spec 000550): my cards due within 7 days or overdue, the oldest first. */
  readonly dueTodos = computed(() => {
    const today = isoDay(new Date(Date.now()));
    const t: Translate = (key, params) => this.i18n.translate(key, params);
    return dueCards(this.myCards(), today, this.phone() ? DUE_PHONE : DUE_MAX).map(({ card, day }) => ({
      card,
      due: dueInfo(day, today, this.i18n.formatLocale(), t),
    }));
  });

  /** A meeting runs or is planned for today: only then the sheet has the title "Heute". */
  readonly hasToday = computed(
    () =>
      this.live().length > 0 ||
      this.planned().some((m) => daysUntil(m.date, new Date(Date.now())) === 0),
  );

  /** No live and no planned meeting (after the load): the sheet says so. */
  readonly noMeetings = computed(
    () =>
      this.meetingsOn() &&
      !this.meetingsLoading() &&
      this.live().length === 0 &&
      this.planned().length === 0,
  );

  /**
   * The sheet shows while it has a part: the meetings while `Sitzungen` is on, or a due
   * card. Without a part the list takes the whole width.
   */
  readonly todayShown = computed(() => this.meetingsOn() || this.dueTodos().length > 0);

  private liveCard(m: Meeting): LiveCard {
    const since = m.startedAt ? clock(m.startedAt, this.i18n.formatLocale()) : shortTime(m.startTime);
    const sub = [
      since ? this.i18n.translate('dashboard.sessions.since', { time: since }) : '',
      m.isProtokollant ? this.i18n.translate('dashboard.today.keeper') : '',
    ]
      .filter((s) => !!s)
      .join(' · ');
    const item = m.currentAgendaItem;
    const count = m.agendaItemCount;
    const open = m.votes.find((v) => v.status === 'open');
    return {
      meeting: m,
      sub,
      now: item && count ? { position: item.position, title: item.title ?? '', count } : null,
      vote: open ? { ballot: this.ballotOf(open.myBallot?.cast ?? false, m.canVote) } : null,
    };
  }

  /**
   * The delegation of the user on a meeting, as a note in its row. Incoming: the user
   * represents another member. Outgoing: another person represents the user. A row of
   * other persons (the admin view) has no direction and stays out.
   */
  private delegationNote(meetingId: Uuid): string | null {
    const d = this.delegationsRaw().find((x) => x.meetingId === meetingId && x.direction !== null);
    if (!d) return null;
    return d.direction === 'outgoing'
      ? this.i18n.translate('delegation.dash.outgoing', { name: d.delegateName || '?' })
      : this.i18n.translate('delegation.dash.incoming', { name: d.delegatorName || '?' });
  }

  /** "Fr, 17:30": the weekday of the date and the planned start. */
  private plannedLabel(m: Meeting): string {
    const day = weekdayName(m.date, this.i18n.formatLocale());
    return [day, shortTime(m.startTime)].filter((s) => !!s).join(', ');
  }

  /** How long a task waits, in calendar days: "heute", "1 Tag", "5 Tage". */
  private waited(at: IsoDateTime): string {
    const days = calendarDaysSince(at, new Date(Date.now()));
    if (days === null) return '—';
    if (days === 0) return this.i18n.translate('dashboard.waiting.today');
    if (days === 1) return this.i18n.translate('dashboard.waiting.one');
    return this.i18n.translate('dashboard.waiting.other', { n: days });
  }

  /** "28.08." in the current year, "28.08.2025" before. */
  private shortDay(at: IsoDateTime): string {
    return shortDay(at, this.i18n.formatLocale(), new Date(Date.now())) || '—';
  }

  /** The full date and time, for a tooltip. */
  private longMoment(at: IsoDateTime): string | null {
    return formatMoment(at, this.i18n.formatLocale()) || null;
  }


  /** Send the request of the open tab again after it failed. */
  retryTab(tab: string = this.tab()): void {
    const source = tab === 'mine' ? this.mineLoad : this.tasksLoad;
    source.reload();
  }

  /**
   * A request as a signal: `undefined` while it runs, `null` when it failed. `reload`
   * sends it again, and the signal is `undefined` until the answer arrives.
   */
  private load<T>(source: Observable<T>): Load<T> {
    const again = new Subject<void>();
    const value = toSignal(
      again.pipe(
        startWith(undefined),
        switchMap(() =>
          source.pipe(
            catchError(() => of(null)),
            startWith(undefined),
          ),
        ),
      ),
      { initialValue: undefined },
    ) as () => Loaded<T>;
    return { value, reload: () => again.next() };
  }

  openAccount(): void {
    this.accountOpen.set(true);
  }

  closeAccount(): void {
    this.accountOpen.set(false);
  }
}

/** The most due cards on the start page, and on a phone. */
export const DUE_MAX = 5;
export const DUE_PHONE = 3;
/** Days ahead that count as due. */
export const DUE_DAYS = 7;

/** The cards due within {@link DUE_DAYS} days or overdue, the oldest due date first. */
export function dueCards<T extends { readonly dueDate: string | null }>(
  cards: readonly T[],
  today: string,
  max: number,
): readonly { readonly card: T; readonly day: string }[] {
  const end = isoDay(new Date(Date.parse(`${today}T12:00:00`) + DUE_DAYS * 86_400_000));
  return cards
    .filter((c): c is T & { readonly dueDate: string } => !!c.dueDate && c.dueDate <= end)
    .sort((a, b) => a.dueDate.localeCompare(b.dueDate))
    .slice(0, max)
    .map((card) => ({ card, day: card.dueDate }));
}
