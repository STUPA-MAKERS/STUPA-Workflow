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
import { filter } from 'rxjs/operators';
import type { PersonRef, Uuid } from '@core/api/models';
import {
  TICKET_KINDS,
  TicketsApiService,
  type TicketKind,
  type TicketListItem,
  type TicketQuery,
  type TicketStatus,
} from '@core/api/tickets.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { liveSearch } from '@shared/live-search';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { AvatarComponent } from '@shared/ui/avatar/avatar.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { ListDetailLayoutComponent } from '@shared/ui/list-detail/list-detail-layout.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
import { ButtonComponent, IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { PageFrameService } from '../../layout/page-frame.service';
import { RailStatusService } from '../../layout/rail-status.service';
import { TicketsPageService } from './tickets-page.service';
import { KIND_ICON, KIND_LABEL, STATUS_LABEL, reporterName, ticketAge } from './tickets.util';

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
 * "Tickets" (permission `ticket.manage`, frames 18, 29): the list of the tickets beside
 * the detail of the open one, in the geometry of the applications page.
 *
 * The chips filter by state (default "Offen": new and in progress), kind and assignee;
 * the search runs while the user types. All filters live in the query params, and a row
 * keeps them. In the default view the closed tickets stay folded under "Erledigt oder
 * abgelehnt" with their number; "n abgeschlossene Tickets zeigen" loads them.
 */
@Component({
  selector: 'app-tickets',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
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

  /** The clock of the row ages; a spec sets it. */
  now: () => Date = () => new Date();

  private readonly layout = viewChild(ListDetailLayoutComponent);
  readonly split = computed(() => this.layout()?.collapsed() === false);
  readonly selectedId = signal<Uuid | null>(null);

  // Filters, from the query params.
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

  readonly searchPlaceholder = computed(() =>
    this.i18n.translate('tickets.list.search', { n: this.total() + this.closedTotal() }),
  );

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

  readonly assigneeOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('tickets.list.filter.all') },
    { value: 'me', label: this.i18n.translate('tickets.list.filter.me') },
    { value: 'none', label: this.i18n.translate('tickets.list.filter.none') },
    ...this.assignees()
      .filter((p): p is PersonRef & { principalId: string } => !!p.principalId)
      .map((p) => ({ value: p.principalId, label: p.displayName ?? p.principalId })),
  ]);
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
    this.api.assignees().subscribe({
      next: (list) => this.assignees.set(list),
      error: () => this.assignees.set([]),
    });

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

    // The detail changed a ticket: the list and the rail count follow.
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

  // --- filters ------------------------------------------------------------

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
      // The child route keeps the open ticket; the routes always have one.
      relativeTo: this.route.firstChild!,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  private readSelection(): void {
    this.selectedId.set(this.route.snapshot.firstChild?.paramMap.get('id') ?? null);
  }

  // --- loading ------------------------------------------------------------

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

  /**
   * Load page 0 after a filter change. The rows stay until the new ones arrive.
   * `keepClosed`: a change of the detail; the shown closed tickets load again too.
   */
  private reload(keepClosed = false): void {
    const seq = ++this.seq;
    const showClosed = keepClosed && this.closedItems() !== null;
    if (!keepClosed) this.closedItems.set(null);
    this.api.list({ ...this.baseQuery(), status: this.statusQuery(), limit: TICKET_PAGE, offset: 0 }).subscribe({
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
    this.api
      .list({ ...this.baseQuery(), status: ['done', 'rejected'], limit: showClosed ? TICKET_PAGE : 1, offset: 0 })
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
    this.api
      .list({ ...this.baseQuery(), status: ['done', 'rejected'], limit: TICKET_PAGE, offset: 0 })
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
    this.api
      .list({
        ...this.baseQuery(),
        status: this.statusQuery(),
        limit: TICKET_PAGE,
        offset: this.items().length,
      })
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
    return {
      item,
      icon: KIND_ICON[item.kind],
      kindLabel: t(KIND_LABEL[item.kind]),
      sub: [item.number, reporterName(item.reporter, t), age].filter(Boolean).join(' · '),
      assignee: item.assignee,
    };
  }
}
