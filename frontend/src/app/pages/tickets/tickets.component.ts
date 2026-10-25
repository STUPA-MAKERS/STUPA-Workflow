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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, type ParamMap, Router, RouterOutlet } from '@angular/router';
import type { Observable } from 'rxjs';
import { filter, map } from 'rxjs/operators';
import { AuthService } from '@core/auth/auth.service';
import { TodosApiService } from '@core/api/todos.service';
import { prefetchDetails } from '@core/cache/detail-prefetch';
import type { PersonRef, Uuid } from '@core/api/models';
import {
  TICKET_KINDS,
  TicketsApiService,
  type MyTicketItem,
  type TicketKind,
  type TicketListItem,
  type TicketPage,
  type TicketQuery,
  type TicketStatus,
} from '@core/api/tickets.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import {
  AvatarComponent,
  ButtonComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  type IconName,
  ListDetailLayoutComponent,
  ListItemComponent,
  liveSearch,
  NoteComponent,
  ScrollFadeDirective,
  SearchPillComponent,
  SkeletonComponent,
  StickyBarComponent,
} from '@stupa-makers/ui-kit';
import { PageFrameService } from '../../layout/page-frame.service';
import { RailStatusService } from '../../layout/rail-status.service';
import { TicketsPageService } from './tickets-page.service';
import { KIND_ICON, KIND_LABEL, STATUS_LABEL, reporterRowName, ticketAge } from './tickets.util';
import { RowChevronComponent } from '@shared/ui/row-chevron/row-chevron.component';
import { PullRefreshDirective } from '@shared/ui/pull-refresh/pull-refresh.directive';

/** The state chip. `open` (the default) shows new and in progress, the closed ones folded. */
export type TicketStatusFilter = 'open' | TicketStatus | 'all';

const STATUS_FILTERS: readonly TicketStatusFilter[] = ['open', 'new', 'in_progress', 'done', 'rejected', 'all'];

/** Rows per request; "Weitere laden" asks for the next page. */
export const TICKET_PAGE = 100;

/** One row as the template shows it. */
export interface TicketRow {
  item: TicketListItem;
  icon: IconName;
  kindLabel: string;
  /** The sub line after the number, which the row sets in mono. */
  sub: string;
  assignee: PersonRef | null;
}

/** One group of the list: a state, or "Erledigt oder abgelehnt". */
export interface TicketGroup {
  key: string;
  label: string;
  count: number;
  rows: TicketRow[];
}

/**
 * "Tickets" (permission `ticket.manage`): the list of the tickets beside
 * the detail of the open one, in the geometry of the applications page.
 *
 * The chips filter by state (default "Offen": new and in progress), kind and assignee;
 * the search runs while the user types. All filters live in the query params, and a row
 * keeps them. In the default view the closed tickets stay folded under "Erledigt oder
 * abgelehnt" with their number; "n abgeschlossene Tickets zeigen" loads them.
 *
 * Without `ticket.manage` the page lists the own tickets of the reporter
 * (`/tickets/mine`): the same groups and filters, without the assignee chip and the
 * assignee of a row.
 */
@Component({
  selector: 'app-tickets',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PullRefreshDirective,
    RowChevronComponent,
    NoteComponent,
    RouterOutlet,
    TranslatePipe,
    AvatarComponent,
    ButtonComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    IconComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    PageHeaderComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    SkeletonComponent,
    StickyBarComponent,
  ],
  providers: [TicketsPageService],
  host: { '[class.pane-page]': 'split()' },
  templateUrl: './tickets.component.html',
  styleUrl: './tickets.component.scss',
})
export class TicketsComponent implements OnDestroy {
  private readonly api = inject(TicketsApiService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly page = inject(TicketsPageService);
  private readonly frame = inject(PageFrameService);
  private readonly rail = inject(RailStatusService);
  /** The team view; else the own tickets of the reporter. */
  private readonly auth = inject(AuthService);
  readonly manager = this.auth.can('ticket.manage');

  /** The clock of the row ages; a spec sets it. */
  now: () => Date = () => new Date();

  private readonly layout = viewChild(ListDetailLayoutComponent);
  readonly split = computed(() => this.layout()?.collapsed() === false);
  readonly selectedId = signal<Uuid | null>(null);

  /** The search text of the filters, from the query params. */
  readonly q = signal('');
  readonly statusFilter = signal<TicketStatusFilter>('open');
  readonly kindFilter = signal<TicketKind | ''>('');
  readonly assigneeFilter = signal('');
  readonly search = liveSearch({
    run: (query) => {
      this.navigate({ q: query || null });
    },
  });
  readonly activeFilterCount = computed(
    () =>
      (this.q() ? 1 : 0) +
      (this.statusFilter() !== 'open' ? 1 : 0) +
      (this.kindFilter() ? 1 : 0) +
      (this.assigneeFilter() ? 1 : 0),
  );

  readonly items = signal<TicketListItem[]>([]);
  readonly total = signal(0);
  readonly loading = signal(true);
  readonly error = signal(false);
  readonly loadingMore = signal(false);
  /** The closed tickets of the default view: their number, and the rows once shown. */
  readonly closedTotal = signal(0);
  readonly closedItems = signal<TicketListItem[] | null>(null);
  readonly closedLoading = signal(false);
  private seq = 0;

  readonly assignees = signal<PersonRef[]>([]);

  readonly searchPlaceholder = computed(() => {
    const n = this.total() + this.closedTotal();
    if (this.loading() && n === 0) return this.i18n.translate('tickets.list.searchLabel');
    return this.i18n.translate('tickets.list.search', { n });
  });

  readonly statusOptions = computed<FilterSelectOption[]>(() =>
    STATUS_FILTERS.map((s) => ({ value: s, label: this.i18n.translate(this.statusFilterLabel(s)) })),
  );
  readonly statusChipLabel = computed(() =>
    this.i18n.translate('tickets.list.filter.statusChip', {
      value: this.i18n.translate(this.statusFilterLabel(this.statusFilter())),
    }),
  );

  readonly kindOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('tickets.list.filter.all') },
    ...TICKET_KINDS.map((k) => ({ value: k, label: this.i18n.translate(KIND_LABEL[k]) })),
  ]);
  readonly kindChipLabel = computed(() => {
    const k = this.kindFilter();
    return k ? this.i18n.translate(KIND_LABEL[k]) : this.i18n.translate('tickets.list.filter.kind');
  });

  readonly assigneeOptions = computed<FilterSelectOption[]>(() => {
    const all = this.i18n.translate('tickets.list.filter.all');
    const none = this.i18n.translate('tickets.list.filter.none');
    return [
      { value: '', label: all, person: { name: all, icon: 'users' } },
      {
        value: 'me',
        label: this.i18n.translate('tickets.list.filter.me'),
        person: { name: this.auth.displayName(), principalId: 'me' },
      },
      { value: 'none', label: none, person: { name: none, icon: 'user' } },
      ...this.assignees()
        .filter((p): p is PersonRef & { principalId: string } => !!p.principalId)
        .map((p) => {
          const label = p.displayName ?? p.principalId;
          return { value: p.principalId, label, person: { name: label, principalId: p.principalId } };
        }),
    ];
  });
  readonly assigneeChipLabel = computed(() => {
    const v = this.assigneeFilter();
    if (!v) return this.i18n.translate('tickets.list.filter.assignee');
    return this.assigneeOptions().find((o) => o.value === v)?.label ?? this.i18n.translate('tickets.list.filter.assignee');
  });

  /** The groups of the list, in the order of the states. */
  readonly groups = computed<TicketGroup[]>(() => {
    const rows = this.items().map((i) => this.toRow(i));
    const byStatus = (s: TicketStatus): TicketRow[] => rows.filter((r) => r.item.status === s);
    const status = this.statusFilter();
    const groups: TicketGroup[] = [];
    const order: TicketStatus[] =
      status === 'open' ? ['new', 'in_progress'] : status === 'all' ? ['new', 'in_progress', 'done', 'rejected'] : [status];
    for (const s of order) {
      const list = byStatus(s);
      if (list.length) {
        groups.push({ key: s, label: this.i18n.translate(STATUS_LABEL[s]), count: list.length, rows: list });
      }
    }
    if (status === 'open' && this.closedTotal() > 0) {
      groups.push({
        key: 'closed',
        label: this.i18n.translate('tickets.list.closedGroup'),
        count: this.closedTotal(),
        rows: (this.closedItems() ?? []).map((i) => this.toRow(i)),
      });
    }
    return groups;
  });

  readonly hasRows = computed(() => this.items().length > 0 || this.closedTotal() > 0);
  readonly hasMore = computed(() => this.items().length < this.total());

  constructor() {
    prefetchDetails({
      items: computed(() => [...this.items(), ...(this.closedItems() ?? [])]),
      key: (t) => t.id,
      reads: (t) =>
        this.manager
          ? [this.api.get(t.id, { detail: true }), inject(TodosApiService).linked('ticket', t.id)]
          : [this.api.getMine(t.id, { detail: true })],
    });
    if (this.manager) {
      this.api.assignees().subscribe({
        next: (list) => this.assignees.set(list),
        error: () => this.assignees.set([]),
      });
    }

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.readFilters(pm);
      this.reload();
    });

    this.readSelection();
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.readSelection());

    this.page.changed$.pipe(takeUntilDestroyed()).subscribe(() => {
      this.reload(true);
      this.rail.refresh();
    });

    effect(() => this.page.split.set(this.split()));
    effect(() => this.frame.fill.set(this.split()));
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
  }

  setStatus(value: string): void {
    this.navigate({ status: value === 'open' ? null : value || null });
  }

  setKind(value: string): void {
    this.navigate({ kind: value || null });
  }

  setAssignee(value: string): void {
    this.navigate({ assignee: value || null });
  }

  reset(): void {
    this.search.sync('');
    this.navigate({ q: null, status: null, kind: null, assignee: null });
  }

  /** "Zur Liste" (one pane at a time): close the detail and keep the filters. */
  closeDetail(): void {
    void this.router.navigate(['/tickets'], { queryParamsHandling: 'preserve' });
  }

  private statusFilterLabel(s: TicketStatusFilter): TranslationKey {
    if (s === 'open') return 'tickets.list.filter.open';
    if (s === 'all') return 'tickets.list.filter.all';
    return STATUS_LABEL[s];
  }

  private readFilters(pm: ParamMap): void {
    this.q.set((pm.get('q') ?? '').trim());
    this.search.sync(this.q());
    const status = pm.get('status') ?? 'open';
    this.statusFilter.set(STATUS_FILTERS.includes(status as TicketStatusFilter) ? (status as TicketStatusFilter) : 'open');
    const kind = pm.get('kind') ?? '';
    this.kindFilter.set(TICKET_KINDS.includes(kind as TicketKind) ? (kind as TicketKind) : '');
    this.assigneeFilter.set(pm.get('assignee') ?? '');
  }

  private navigate(queryParams: Record<string, string | null>): void {
    void this.router.navigate([], {
      relativeTo: this.route.firstChild!,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  private readSelection(): void {
    this.selectedId.set(this.route.snapshot.firstChild?.paramMap.get('id') ?? null);
  }

  /** One page: every ticket for the team, the own ones for the reporter. */
  private fetch(query: TicketQuery): Observable<TicketPage> {
    if (this.manager) return this.api.list(query);
    return this.api.mine(query).pipe(map((page) => ({ ...page, items: page.items.map(asListItem) })));
  }

  /** The request of the filters, without the states. */
  private baseQuery(): TicketQuery {
    return {
      kind: this.kindFilter() ? [this.kindFilter() as TicketKind] : [],
      assignee: this.assigneeFilter() || null,
      q: this.q() || null,
    };
  }

  private statusQuery(): TicketStatus[] {
    const s = this.statusFilter();
    if (s === 'open') return ['new', 'in_progress'];
    if (s === 'all') return [];
    return [s];
  }

  /** Pull to refresh: page 0 loads again, with the closed tickets that show. */
  protected refreshList(): void {
    this.reload(true);
  }

  /** Load page 0 again after a failed load. */
  retry(): void {
    this.error.set(false);
    this.loading.set(true);
    this.reload();
  }

  /**
   * Load page 0 after a filter change. The rows stay until the new ones arrive.
   * `keepClosed`: a change of the detail; the shown closed tickets load again too.
   */
  private reload(keepClosed = false): void {
    const seq = ++this.seq;
    const showClosed = keepClosed && this.closedItems() !== null;
    if (!keepClosed) this.closedItems.set(null);
    this.fetch({ ...this.baseQuery(), status: this.statusQuery(), limit: TICKET_PAGE, offset: 0 }).subscribe({
      next: (page) => {
        if (seq !== this.seq) return;
        this.items.set(page.items);
        this.total.set(page.total);
        this.error.set(false);
        this.loading.set(false);
      },
      error: () => {
        if (seq !== this.seq) return;
        if (!keepClosed) {
          this.items.set([]);
          this.error.set(true);
        }
        this.loading.set(false);
      },
    });
    if (this.statusFilter() !== 'open') {
      this.closedTotal.set(0);
      return;
    }
    this.fetch({ ...this.baseQuery(), status: ['done', 'rejected'], limit: showClosed ? TICKET_PAGE : 1, offset: 0 })
      .subscribe({
        next: (page) => {
          if (seq !== this.seq) return;
          this.closedTotal.set(page.total);
          if (showClosed) this.closedItems.set(page.items);
        },
        error: () => {
          if (seq === this.seq) this.closedTotal.set(0);
        },
      });
  }

  /** "n abgeschlossene Tickets zeigen". */
  showClosed(): void {
    if (this.closedLoading()) return;
    const seq = this.seq;
    this.closedLoading.set(true);
    this.fetch({ ...this.baseQuery(), status: ['done', 'rejected'], limit: TICKET_PAGE, offset: 0 })
      .subscribe({
        next: (page) => {
          this.closedLoading.set(false);
          if (seq !== this.seq) return;
          this.closedItems.set(page.items);
          this.closedTotal.set(page.total);
        },
        error: () => this.closedLoading.set(false),
      });
  }

  /** "Weitere Tickets laden": the next page of the main request. */
  loadMore(): void {
    if (this.loadingMore()) return;
    const seq = this.seq;
    this.loadingMore.set(true);
    this.fetch({ ...this.baseQuery(), status: this.statusQuery(), limit: TICKET_PAGE, offset: this.items().length })
      .subscribe({
        next: (page) => {
          this.loadingMore.set(false);
          if (seq !== this.seq) return;
          this.items.update((list) => [...list, ...page.items]);
          this.total.set(page.total);
        },
        error: () => this.loadingMore.set(false),
      });
  }

  private toRow(item: TicketListItem): TicketRow {
    const t = (key: TranslationKey, params?: Record<string, string | number>): string =>
      this.i18n.translate(key, params);
    const age = ticketAge(item.createdAt, this.now(), this.i18n.formatLocale(), t);
    const reporter = this.manager ? reporterRowName(item.reporter, t) : null;
    return {
      item,
      icon: KIND_ICON[item.kind],
      kindLabel: t(KIND_LABEL[item.kind]),
      sub: [reporter, age].filter(Boolean).join(' · '),
      assignee: item.assignee,
    };
  }
}

/** An own ticket as a list row of the team list: no reporter, no assignee. */
function asListItem(item: MyTicketItem): TicketListItem {
  return {
    ...item,
    reporter: { principalId: null, displayName: null, email: null, anonymized: false },
    assignee: null,
  };
}
