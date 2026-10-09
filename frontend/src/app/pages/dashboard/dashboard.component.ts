import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { catchError, distinctUntilChanged, forkJoin, map, of, switchMap, type Observable } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { type Delegation, DelegationsApiService } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  ApplicationListItem,
  ApplicationType,
  IsoDateTime,
  Meeting,
  MeetingPage,
  Page,
  Uuid,
  VoteListItem,
} from '@core/api/models';
import {
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  IconComponent,
  MEDIA,
  TabsComponent,
  type TabItem,
} from '@stupa-makers/ui-kit';
// By path, not through the `@shared/ui` barrel, so this lazy chunk takes only the blocks
// it uses.
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SegBarComponent } from '@shared/ui/seg-bar/seg-bar.component';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import {
  type StatusKind,
  flowColorKind,
  meetingVoteStatus,
} from '@shared/status-kind.util';
import { closedStatus } from '../../features/voting/election.util';
import { shortTime } from '../../features/meetings/meetings-display.util';
import { CommandPaletteService } from '../../features/search/command-palette.service';
import { AccountMenuComponent } from '../../layout/account-menu/account-menu.component';
import { mediaQuerySignal } from '../../layout/media-query';
import { NavService } from '../../layout/nav.service';
import {
  type BudgetAllocationView,
  type BudgetTreeNode,
  BudgetTreeApi,
  type FiscalYear,
} from '../budget/budget-tree.api';

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
/** At most this many cost-centre roots in the budget summary. */
const BUDGET_ROOTS = 2;
const DAY_MS = 86_400_000;

/** The tabs of the work list. The URL keeps the choice as `?tab=`. */
export type WorkTab = 'tasks' | 'mine' | 'votes';
const TABS: readonly WorkTab[] = ['tasks', 'mine', 'votes'];

/** A row of "Offene Aufgaben" or "Meine Anträge". */
export interface WorkRow {
  id: Uuid;
  link: readonly string[];
  title: string;
  type: string;
  statusLabel: string;
  statusKind: StatusKind;
  /** "4 Tage" (tasks) or "28.08." (own applications). */
  since: string;
  /** The exact moment, for the tooltip. */
  sinceTitle: string | null;
  amount: string | null;
}

/** A row of "Abstimmungen". */
export interface VoteRow {
  id: Uuid;
  link: readonly string[];
  title: string;
  /** "34. Sitzung · TOP 3", the gremium of a vote without a meeting, or null. */
  where: string | null;
  statusKey: TranslationKey;
  statusKind: StatusKind;
  ballot: 'cast' | 'pending' | null;
}

/** A live meeting in the sheet. */
export interface LiveCard {
  meeting: Meeting;
  /** "seit 18:04 · Du führst Protokoll". */
  sub: string;
  now: { position: number; title: string; count: number } | null;
  /** The open vote of the meeting and the own state in it, or null without one. */
  vote: { ballot: 'cast' | 'pending' | null } | null;
}

/** A planned meeting in the sheet. */
export interface UpcomingRow {
  meeting: Meeting;
  /** "Du vertrittst Konrad Pfeiffer" while a delegation of the user is on it. */
  note: string | null;
  /** "Fr, 17:30". */
  when: string;
}

/** The figures of one cost-centre root for its current fiscal year. */
export interface BudgetSummary {
  id: Uuid;
  fyId: Uuid;
  title: string;
  available: string;
  /** Bound plus spent, in percent of the allocation. */
  used: number;
  allocated: number;
  committed: number;
}

type Loaded<T> = T | null | undefined;

/**
 * The start page of a signed-in person (variant B "Arbeitsliste + Seitenleiste").
 *
 * Left: the search pill with "Antrag stellen", the greeting, and ONE work list with the
 * tabs "Offene Aufgaben", "Meine Anträge" and "Abstimmungen". The tabs show their counts
 * and the URL keeps the choice (`?tab=`). Each tab is a table with real columns; a row
 * opens its detail page, and "Alle … öffnen" opens the full list.
 *
 * Right: the sheet "Heute" with the live meeting (progress, the own vote state, "Live
 * beitreten"), the next meetings (with "Du vertrittst …" from the delegations) and, for a
 * person who may see budgets, a budget summary.
 *
 * Wide, the page is a pane page: the document does not scroll, the list and the sheet
 * scroll inside themselves. The start page keeps the footer. Narrow and on a phone the
 * page scrolls: the "Heute" band comes first, then the work list. A phone shows the rows
 * as list rows and a floating "Antrag" button.
 *
 * A person without tasks and without own applications sees the empty tab next to the
 * card "Antrag stellen" with the active application types.
 *
 * No request shows the global loading overlay: each block shows its own skeleton, empty
 * or error state.
 */
@Component({
  selector: 'app-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    RouterLink,
    IconComponent,
    TranslatePipe,
    TabsComponent,
    DataTableComponent,
    CellDirective,
    AvatarComponent,
    DateBlockComponent,
    EmptyStateComponent,
    ListItemComponent,
    PageHeaderComponent,
    SearchPillComponent,
    SegBarComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    ScrollFadeDirective,
    AccountMenuComponent,
  ],
  host: {
    '[class.dash--phone]': 'phone()',
    '[class.dash--wide]': 'wide()',
    '[class.pane-page]': 'wide()',
  },
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  /** The search pill at the top opens the global search. */
  protected readonly palette = inject(CommandPaletteService);
  private readonly api = inject(ApiClient);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly nav = inject(NavService);
  private readonly delegationsApi = inject(DelegationsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  /** Phone width (<= 768px): compact head, the band first, list rows, floating button. */
  readonly phone = mediaQuerySignal(MEDIA.phone);
  /** Wide (>= 1200px): the list and the sheet side by side, no page scroll. */
  readonly wide = mediaQuerySignal(MEDIA.wide);
  /** A very wide screen shows more meetings in the sheet. */
  private readonly extraWide = mediaQuerySignal('(min-width: 1680px)');
  /** The account sheet of the compact phone head. */
  readonly accountOpen = signal(false);

  // ---------------------------------------------------------------- data

  private readonly tasks = this.load(this.api.listTasks());
  /** The own applications (`mine=true`), newest status change first: the date the rows
   *  show. `mine` forces the owner filter, also for a reader with `application.read`. */
  private readonly mine = this.load<Page<ApplicationListItem>>(
    this.api.listApplications({ mine: true, limit: ROWS, sort: 'stateSince', order: 'desc' }),
  );
  /** The votes the server lets the user read, the open ones first. */
  private readonly votes = this.load<Page<VoteListItem>>(this.api.listVotes({ limit: ROWS }));
  /** The live and the next meetings. The timeline already scopes and sorts them. */
  private readonly timeline = this.load<MeetingPage>(
    this.api.listMeetingsTimeline({ direction: 'upcoming', limit: TIMELINE_LIMIT }),
  );
  private readonly delegationsRaw = toSignal(
    this.delegationsApi.list().pipe(catchError(() => of([] as Delegation[]))),
    { initialValue: [] as Delegation[] },
  );
  private readonly types = toSignal(
    this.api.applicationTypes({ quiet: true }).pipe(catchError(() => of([] as ApplicationType[]))),
    { initialValue: [] as ApplicationType[] },
  );

  /** The budget pages are open to the user (a global budget right or a scoped view). */
  readonly canSeeBudget = computed(() => this.navVisible('budget'));
  /** The invoice list is open to the user (a global budget right). */
  private readonly canSeeInvoices = computed(() => this.navVisible('invoices'));
  /** The budget summary. It loads once the session shows the right, never without it. */
  readonly budgets = toSignal(
    toObservable(this.canSeeBudget).pipe(
      distinctUntilChanged(),
      switchMap((allowed) => (allowed ? this.budgetSummaries() : of([] as BudgetSummary[]))),
    ),
    { initialValue: [] as BudgetSummary[] },
  );
  /** Open invoices, counted only for a person who may open the invoice list. */
  readonly openInvoices = toSignal(
    toObservable(this.canSeeInvoices).pipe(
      distinctUntilChanged(),
      switchMap((allowed) =>
        allowed
          ? this.budgetApi.listInvoicesPaged({ status: 'open', limit: 1 }).pipe(
              map((page) => page.total),
              catchError(() => of(0)),
            )
          : of(0),
      ),
    ),
    { initialValue: 0 },
  );

  private readonly typeName = computed(() => {
    const names = new Map(this.types().map((t) => [t.id, t.name]));
    // No raw id as a fallback: the types load late or can fail.
    return (id: Uuid): string => names.get(id) ?? '';
  });

  /** The active application types, for the card "Antrag stellen" of a new user. */
  readonly applyTypes = computed(() => this.types().filter((t) => t.active));

  // ---------------------------------------------------------------- head

  /** The first word of the display name: "Willkommen, Mara". */
  readonly firstName = computed(() => this.auth.displayName().trim().split(/\s+/)[0]);

  /** The gremien of the user, as one line under the greeting. */
  readonly gremienLine = computed(() =>
    this.auth
      .gremien()
      .map((g) => g.name)
      .join(' · '),
  );

  // ---------------------------------------------------------------- tabs

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
    const tasks = this.tasks();
    const mine = this.mine();
    const votes = this.votes();
    return [
      {
        id: 'tasks',
        label: this.i18n.translate(short ? 'dashboard.tab.tasksShort' : 'dashboard.tasks.title'),
        count: tasks ? tasks.length : null,
      },
      {
        id: 'mine',
        label: this.i18n.translate(short ? 'dashboard.tab.mineShort' : 'dashboard.applications.title'),
        count: mine ? mine.total : null,
      },
      {
        id: 'votes',
        label: this.i18n.translate('dashboard.tab.votes'),
        // The open votes only: the ended ones need nobody.
        count: votes ? votes.items.filter((v) => v.status === 'open').length : null,
      },
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
  readonly tabLoading = computed(() => this.source() === undefined);
  /** `true` when the request of the open tab failed. */
  readonly tabError = computed(() => this.source() === null);

  private readonly source = computed<Loaded<unknown>>(() => {
    switch (this.tab()) {
      case 'mine':
        return this.mine();
      case 'votes':
        return this.votes();
      default:
        return this.tasks();
    }
  });

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

  readonly voteRows = computed<VoteRow[]>(() =>
    (this.votes()?.items ?? []).slice(0, this.rowCap()).map((v) => this.voteRow(v)),
  );

  /** The rows of the open tab are empty (and loaded). */
  readonly tabEmpty = computed(() => {
    if (this.tabLoading() || this.tabError()) return false;
    switch (this.tab()) {
      case 'mine':
        return this.mineRows().length === 0;
      case 'votes':
        return this.voteRows().length === 0;
      default:
        return this.taskRows().length === 0;
    }
  });

  /** No own application yet: the empty tab gets the card "Antrag stellen" beside it. */
  readonly newUser = computed(() => this.mine()?.total === 0);

  /** "Alle … öffnen" of the open tab, or null when the target is closed to the user. */
  readonly allLink = computed<{ key: TranslationKey; link: string; query: Record<string, string> | null } | null>(
    () => {
      switch (this.tab()) {
        case 'mine':
          return { key: 'dashboard.all.mine', link: '/applications', query: { mine: 'true' } };
        case 'votes':
          return this.navVisible('voting')
            ? { key: 'dashboard.all.votes', link: '/voting', query: null }
            : null;
        default:
          return { key: 'dashboard.all.tasks', link: '/tasks', query: null };
      }
    },
  );

  /** The columns of "Offene Aufgaben" and "Meine Anträge". */
  readonly workColumns = computed<ColumnDef[]>(() => [
    { key: 'title', label: this.i18n.translate('dashboard.col.application'), card: 'title' },
    { key: 'type', label: this.i18n.translate('dashboard.col.type'), width: '9rem' },
    { key: 'status', label: this.i18n.translate('dashboard.col.status'), width: '9rem' },
    {
      key: 'since',
      label: this.i18n.translate(this.tab() === 'mine' ? 'dashboard.col.since' : 'dashboard.col.waiting'),
      width: '6.5rem',
    },
    { key: 'amount', label: this.i18n.translate('dashboard.col.amount'), align: 'end', width: '7rem' },
    { key: 'go', label: '', align: 'end', width: '3.25rem' },
  ]);

  /** The columns of "Abstimmungen". */
  readonly voteColumns = computed<ColumnDef[]>(() => [
    { key: 'title', label: this.i18n.translate('dashboard.col.question'), card: 'title' },
    { key: 'where', label: this.i18n.translate('dashboard.col.where'), width: '12rem' },
    { key: 'status', label: this.i18n.translate('dashboard.col.status'), width: '8rem' },
    { key: 'ballot', label: this.i18n.translate('dashboard.col.ballot'), width: '9rem' },
    { key: 'go', label: '', align: 'end', width: '3.25rem' },
  ]);

  readonly rowKey = (row: unknown): unknown => (row as { id: Uuid }).id;

  /** A row of the table opens its detail page. */
  openRow(row: unknown): void {
    void this.router.navigate((row as WorkRow | VoteRow).link as string[]);
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
      type,
      statusLabel: item.state?.label ?? '',
      statusKind: flowColorKind(item.state?.color),
      since,
      sinceTitle: this.longMoment(at),
      amount: this.money(item.amount, item.currency),
    };
  }

  private voteRow(v: VoteListItem): VoteRow {
    const status =
      v.status === 'closed' && v.result
        ? closedStatus(v.kind, v.result)
        : v.status === 'draft'
          ? { kind: 'neutral' as const, key: 'voting.list.status.draft' as const }
          : meetingVoteStatus(v.status);
    let where = v.gremiumName;
    if (v.meetingTitle) {
      where =
        v.agendaPosition === null
          ? v.meetingTitle
          : this.i18n.translate('dashboard.votes.where', {
              meeting: v.meetingTitle,
              n: v.agendaPosition,
            });
    }
    return {
      id: v.id,
      link: ['/voting', v.id],
      title: v.question?.trim() || this.i18n.translate('meetings.vote.untitled'),
      where,
      statusKey: status.key,
      statusKind: status.kind,
      ballot: this.ballotOf(v.myBallot.cast, v.status === 'open' && v.canCast),
    };
  }

  private ballotOf(cast: boolean, canCast: boolean): 'cast' | 'pending' | null {
    if (cast) return 'cast';
    return canCast ? 'pending' : null;
  }

  // ---------------------------------------------------------------- today

  /** "Di, 29.09.2026". */
  readonly todayLabel = computed(() =>
    new Date(Date.now())
      .toLocaleDateString(this.i18n.formatLocale(), {
        weekday: 'short',
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
      .replace(/\.,/, ','),
  );

  readonly meetingsLoading = computed(() => this.timeline() === undefined);
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

  /** "5" or "8+" when the timeline holds more. */
  readonly plannedCount = computed(() => {
    const n = this.planned().length;
    return this.timeline()?.nextCursor ? `${n}+` : String(n);
  });

  readonly upcoming = computed<UpcomingRow[]>(() => {
    const cap = this.phone() ? PHONE_MEETINGS : this.extraWide() ? MEETINGS_XL : MEETINGS;
    return this.planned()
      .slice(0, cap)
      .map((m) => ({ meeting: m, note: this.delegationNote(m.id), when: this.plannedLabel(m) }));
  });

  /** No live and no planned meeting (after the load): the sheet says so. */
  readonly noMeetings = computed(
    () => !this.meetingsLoading() && this.live().length === 0 && this.planned().length === 0,
  );

  private liveCard(m: Meeting): LiveCard {
    const since = m.startedAt ? this.clock(m.startedAt) : shortTime(m.startTime);
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
    const day = this.weekday(m.date);
    return [day, shortTime(m.startTime)].filter((s) => !!s).join(', ');
  }

  // ---------------------------------------------------------------- budget

  /**
   * The budget figures of the cost-centre roots the server shows the user, for the fiscal
   * year that holds today (else the active one, else the first one the server lists).
   */
  private budgetSummaries(): Observable<BudgetSummary[]> {
    return this.budgetApi.tree().pipe(
      switchMap((tree) => {
        const roots = tree.filter((n) => !n.hiddenInBudget).slice(0, BUDGET_ROOTS);
        if (!roots.length) return of([] as (BudgetSummary | null)[]);
        return forkJoin(
          roots.map((root) =>
            this.budgetApi.listFiscalYears(root.id).pipe(
              map((fys) => this.summary(root, fys, roots.length > 1)),
              catchError(() => of(null)),
            ),
          ),
        );
      }),
      map((rows) => rows.filter((r): r is BudgetSummary => r !== null)),
      catchError(() => of([] as BudgetSummary[])),
    );
  }

  private summary(root: BudgetTreeNode, fys: FiscalYear[], named: boolean): BudgetSummary | null {
    const today = this.today();
    const fy =
      fys.find((f) => f.startDate <= today && today <= f.endDate) ??
      fys.find((f) => f.active) ??
      fys[0];
    const view: BudgetAllocationView | undefined = fy
      ? root.byFiscalYear.find((v) => v.fiscalYearId === fy.id)
      : undefined;
    if (!fy || !view) return null;
    const allocated = Number(view.allocated) || 0;
    const committed = (Number(view.bound) || 0) + (Number(view.expended) || 0);
    return {
      id: root.id,
      fyId: fy.id,
      title: named
        ? this.i18n.translate('dashboard.today.budgetNamed', { name: root.name, year: fy.display })
        : this.i18n.translate('dashboard.today.budget', { year: fy.display }),
      available: this.money(view.available, root.currency) ?? '',
      used: allocated > 0 ? Math.round((committed / allocated) * 100) : 0,
      allocated,
      committed,
    };
  }

  // ---------------------------------------------------------------- format

  private navVisible(key: string): boolean {
    return this.nav.visible().some((i) => i.key === key);
  }

  /** The amount in its currency, or null without an amount. */
  private money(value: string | null | undefined, currency: string | null | undefined): string | null {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    if (Number.isNaN(n)) return value;
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: currency || 'EUR',
    }).format(n);
  }

  /** How long a task waits, in calendar days: "heute", "1 Tag", "5 Tage". */
  private waited(at: IsoDateTime): string {
    const then = new Date(at);
    if (Number.isNaN(then.getTime())) return '—';
    const day = (d: Date): number => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    // Round, not floor: a day with a DST change has 23 or 25 hours.
    const days = Math.max(0, Math.round((day(new Date(Date.now())) - day(then)) / DAY_MS));
    if (days === 0) return this.i18n.translate('dashboard.waiting.today');
    if (days === 1) return this.i18n.translate('dashboard.waiting.one');
    return this.i18n.translate('dashboard.waiting.other', { n: days });
  }

  /** "28.08." in the current year, "28.08.2025" before. */
  private shortDay(at: IsoDateTime): string {
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return '—';
    const sameYear = d.getFullYear() === new Date(Date.now()).getFullYear();
    return d.toLocaleDateString(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      ...(sameYear ? {} : { year: 'numeric' }),
    });
  }

  /** The full date and time, for a tooltip. */
  private longMoment(at: IsoDateTime): string | null {
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleString(this.i18n.formatLocale(), { dateStyle: 'medium', timeStyle: 'short' });
  }

  /** The short weekday of a `YYYY-MM-DD` date in the local calendar, without a dot. */
  private weekday(date: string | null): string {
    const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(date ?? '');
    if (!match) return '';
    const d = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return d
      .toLocaleDateString(this.i18n.formatLocale(), { weekday: 'short' })
      .replace(/\.$/, '');
  }

  /** The local time of an instant as HH:MM. */
  private clock(at: IsoDateTime): string {
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString(this.i18n.formatLocale(), { hour: '2-digit', minute: '2-digit' });
  }

  /** Today as `YYYY-MM-DD` in the local calendar. */
  private today(): string {
    const d = new Date(Date.now());
    const pad = (n: number): string => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  /** A request as a signal: `undefined` while it runs, `null` when it failed. */
  private load<T>(source: Observable<T>) {
    return toSignal(source.pipe(catchError(() => of(null))), {
      initialValue: undefined,
    }) as () => Loaded<T>;
  }

  // ---------------------------------------------------------------- phone

  openAccount(): void {
    this.accountOpen.set(true);
  }

  closeAccount(): void {
    this.accountOpen.set(false);
  }
}
