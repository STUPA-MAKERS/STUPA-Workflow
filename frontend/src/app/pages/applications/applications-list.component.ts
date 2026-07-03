import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  ApplicationListItem,
  ApplicationListQuery,
  ApplicationType,
  Uuid,
} from '@core/api/models';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import {
  CurrencyInputComponent,
  DatepickerComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import {
  ApplicationsTableComponent,
  type ApplicationRow,
  type SortState,
} from './applications-table.component';
import { AuthService } from '@core/auth/auth.service';
import { downloadBlob } from '@shared/download.util';

/**
 * Application list: filter/search (`state/gremium/type/topf/q`) + offset paging.
 * Filter/page state lives in the route **query params** — so a filtered list is
 * shareable/linkable (e.g. from the budget area) and browser-back works. Visible
 * controls exist for search/type/status; `gremium`/`topf` are taken from the URL
 * (pickers to follow with the gremium/pot list endpoints).
 */
@Component({
  selector: 'app-applications-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, IconComponent, SelectComponent, CurrencyInputComponent, DatepickerComponent, FilterBarComponent, FilterFieldComponent, FilterRangeComponent, CostCentreTreeComponent, ApplicationsTableComponent],
  templateUrl: './applications-list.component.html',
  styleUrl: './applications-list.component.scss',
})
export class ApplicationsListComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);

  readonly canExport = computed(() => this.auth.can('application.export'));
  readonly exporting = signal(false);

  readonly limit = 20;

  /** Initial load (filter/sort change) — hides the whole list. */
  readonly loading = signal(true);
  /** Loading more pages while scrolling (incremental, list stays visible). */
  readonly loadingMore = signal(false);
  readonly error = signal(false);
  /** Accumulated applications across all loaded pages so far (infinite scroll). */
  readonly items = signal<ApplicationListItem[]>([]);
  readonly total = signal(0);
  /** Offset of the **next** page to load. */
  private nextOffset = 0;
  /** Fetch sequence number: late responses from old filters are discarded. */
  private fetchSeq = 0;
  /** `gremium`/`topf` have no visible controls — mirrored from the URL. */
  private gremium = '';
  private topf = '';
  readonly types = signal<ApplicationType[]>([]);

  /** Visible filter controls (mirrored from the query params). */
  readonly q = signal('');
  /** Debounce timer of the header search (~400 ms, like /expenses). */
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  readonly typeId = signal('');
  readonly state = signal('');

  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Cost-centre tree for the left tree picker (same look as the budget tab). */
  readonly budgetTree = signal<BudgetTreeNode[]>([]);

  /** Remove cost centres (+ subtree) hidden in the budget tab from the filter
   *  tree — mirrors the budget dashboard's `visibleTree`. */
  private pruneHidden(nodes: BudgetTreeNode[]): BudgetTreeNode[] {
    return nodes
      .filter((n) => !n.hiddenInBudget)
      .map((n) => ({ ...n, children: this.pruneHidden(n.children) }));
  }
  /** Mobile: tree behind a collapsible toggle (desktop always visible). */
  readonly treeOpen = signal(false);
  readonly sortField = signal<'createdAt' | 'amount'>('createdAt');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  /** Number of active filters (for the indicator). */
  readonly activeFilterCount = computed(
    () =>
      [
        this.q(),
        this.typeId(),
        this.state(),
        this.amountMin(),
        this.amountMax(),
        this.createdFrom(),
        this.createdTo(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  /**
   * Status dropdown options accumulated from the **real** states of the loaded
   * applications (value = state UUID, label = resolved state name). The sent
   * `state` filter value stays the UUID (contract: `current_state_id`). Once-seen
   * states are kept so the filter does not collapse to a single value.
   */
  private readonly seenStates = signal<Map<string, string>>(new Map());
  readonly stateOptions = computed<SelectOption[]>(() =>
    [...this.seenStates()].map(([value, label]) => ({ value, label })),
  );

  /** Any unloaded applications left? Controls the sentinel + "load more". */
  readonly hasMore = computed(() => this.items().length < this.total());

  /** Sentinel at the list end — becoming visible triggers the next load. */
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  /** Application-type options for the filter (value = type UUID, label = type name). */
  readonly typeOptions = computed<SelectOption[]>(() =>
    this.types().map((type) => ({ value: type.id, label: type.name })),
  );

  /** Application rows for the shared table. */
  readonly tableRows = computed<ApplicationRow[]>(() =>
    this.items().map((item) => ({
      id: item.id,
      title: this.titleOf(item),
      typeLabel: this.typeName(item.typeId),
      stateLabel: item.state?.label ?? null,
      stateColor: item.state?.color ?? null,
      amount: item.amount ?? null,
      currency: item.currency ?? null,
      createdAt: item.createdAt ?? null,
    })),
  );
  readonly sortState = computed<SortState>(() => ({
    field: this.sortField(),
    order: this.sortOrder(),
  }));

  constructor() {
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (types) => this.types.set(types),
      error: () => this.types.set([]),
    });
    // Cost-centre tree for the left filter picker (eager). Cost centres hidden
    // in the budget tab (`hiddenInBudget`) do not appear here either.
    this.budgetApi.tree().subscribe({
      next: (tree) => this.budgetTree.set(this.pruneHidden(tree)),
      error: () => this.budgetTree.set([]),
    });

    // Filter/sort live in the query params: every change resets the list and
    // reloads page 0. The offset is **no longer** in the URL (infinite scroll),
    // it is counted up internally.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.q.set(pm.get('q') ?? '');
      this.typeId.set(pm.get('type') ?? '');
      this.state.set(pm.get('state') ?? '');
      this.amountMin.set(pm.get('amountMin') ?? '');
      this.amountMax.set(pm.get('amountMax') ?? '');
      this.createdFrom.set(pm.get('createdFrom') ?? '');
      this.createdTo.set(pm.get('createdTo') ?? '');
      this.budgetId.set(pm.get('budget') ?? '');
      this.gremium = pm.get('gremium') ?? '';
      this.topf = pm.get('topf') ?? '';
      this.sortField.set(pm.get('sort') === 'amount' ? 'amount' : 'createdAt');
      this.sortOrder.set(pm.get('order') === 'asc' ? 'asc' : 'desc');
      this.reload();
    });

    // True lazy infinite scroll: an IntersectionObserver on the sentinel loads the
    // next page once the list end comes into view (rootMargin as prefetch). The
    // effect re-binds whenever the sentinel (only with hasMore) appears/disappears.
    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      // No observer without a DOM API (SSR/tests) — the "load more" button stays fallback.
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMore();
        },
        { rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  /** Select a cost centre in the left tree (``''`` = all); filters the list. */
  selectBudgetNode(id: string): void {
    this.budgetId.set(id);
    this.navigate({ budget: id || null, offset: null });
  }

  typeName(typeId: Uuid): string {
    return this.typesById().get(typeId) ?? typeId;
  }

  /** Application title (system title field) with fallback "untitled". */
  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** Merge the real states of the loaded applications into the dropdown options. */
  private collectStates(items: ApplicationListItem[]): void {
    const next = new Map(this.seenStates());
    let changed = false;
    for (const item of items) {
      if (item.state && !next.has(item.state.id)) {
        next.set(item.state.id, item.state.label);
        changed = true;
      }
    }
    if (changed) this.seenStates.set(next);
  }

  /** Export the current list (filters from the query params) as Excel. */
  onExport(): void {
    if (this.exporting()) return;
    this.exporting.set(true);
    const pm = this.route.snapshot.queryParamMap;
    const query: ApplicationListQuery = {};
    const str = (k: keyof ApplicationListQuery, p = k as string): void => {
      const v = pm.get(p);
      if (v) (query[k] as unknown) = v;
    };
    str('q'); str('type'); str('state'); str('gremium'); str('topf'); str('budget');
    str('createdFrom'); str('createdTo');
    const min = pm.get('amountMin'); if (min) query.amountMin = Number(min);
    const max = pm.get('amountMax'); if (max) query.amountMax = Number(max);
    const sort = pm.get('sort'); if (sort === 'amount' || sort === 'createdAt') query.sort = sort;
    const order = pm.get('order'); if (order === 'asc' || order === 'desc') query.order = order;
    this.api.exportApplicationsXlsx(query).subscribe({
      next: (blob) => {
        downloadBlob(blob, 'applications.xlsx');
        this.exporting.set(false);
      },
      error: () => this.exporting.set(false),
    });
  }

  /** Header live search: debounced ~400 ms → ``q`` query param → reload (mirrors
   *  /expenses). The ``q`` value lives on in the URL (shareable/linkable). */
  onSearch(value: string): void {
    this.q.set(value);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(
      () => this.navigate({ q: this.q().trim() || null, offset: null }),
      400,
    );
  }

  ngOnDestroy(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
  }

  applyFilters(): void {
    this.navigate({
      q: this.q() || null,
      type: this.typeId() || null,
      state: this.state() || null,
      amountMin: this.amountMin() ? Number(this.amountMin()) : null,
      amountMax: this.amountMax() ? Number(this.amountMax()) : null,
      createdFrom: this.createdFrom() || null,
      createdTo: this.createdTo() || null,
      budget: this.budgetId() || null,
      offset: null,
    });
  }

  reset(): void {
    this.q.set('');
    this.typeId.set('');
    this.state.set('');
    this.amountMin.set('');
    this.amountMax.set('');
    this.createdFrom.set('');
    this.createdTo.set('');
    this.budgetId.set('');
    this.navigate({
      q: null, type: null, state: null, gremium: null, topf: null, budget: null,
      amountMin: null, amountMax: null, createdFrom: null, createdTo: null, offset: null,
    });
  }

  /** Sort event from the shared table → into the query params. */
  onSort(sort: SortState): void {
    this.navigate({ sort: sort.field, order: sort.order, offset: null });
  }

  /** Append the next page (sentinel visible or "load more" button). */
  loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  private navigate(queryParams: Record<string, string | number | null>): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  /** Reset the list (filter/sort change) and reload page 0. */
  private reload(): void {
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loadingMore.set(false);
    this.loading.set(true);
    this.error.set(false);
    this.fetch(true);
  }

  /** Build the query from the current filter state for a given offset. */
  private buildQuery(offset: number): ApplicationListQuery {
    const query: ApplicationListQuery = { limit: this.limit, offset };
    if (this.q().trim()) query.q = this.q().trim();
    if (this.typeId()) query.type = this.typeId();
    if (this.state()) query.state = this.state();
    if (this.gremium) query.gremium = this.gremium;
    if (this.topf) query.topf = this.topf;
    if (this.budgetId()) query.budget = this.budgetId();
    if (this.amountMin().trim()) query.amountMin = Number(this.amountMin());
    if (this.amountMax().trim()) query.amountMax = Number(this.amountMax());
    if (this.createdFrom().trim()) query.createdFrom = this.createdFrom();
    if (this.createdTo().trim()) query.createdTo = this.createdTo();
    query.sort = this.sortField();
    query.order = this.sortOrder();
    return query;
  }

  /**
   * Fetch a page. ``initial`` replaces the list (and shows the full error on
   * failure), otherwise it appends (a load-more error stays silent — the
   * already-loaded list remains usable).
   */
  private fetch(initial: boolean): void {
    // Sequence number against out-of-order responses: on fast filter changes a
    // late page of the old filter must not overwrite the current list.
    const seq = ++this.fetchSeq;
    this.api.listApplications(this.buildQuery(this.nextOffset)).subscribe({
      next: (page) => {
        if (seq !== this.fetchSeq) return;
        this.total.set(page.total);
        this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
        // Count up by the actual result count (last page < limit).
        this.nextOffset = page.offset + page.items.length;
        this.collectStates(page.items);
        this.loading.set(false);
        this.loadingMore.set(false);
      },
      error: () => {
        if (seq !== this.fetchSeq) return;
        if (initial) this.error.set(true);
        this.loading.set(false);
        this.loadingMore.set(false);
      },
    });
  }
}
