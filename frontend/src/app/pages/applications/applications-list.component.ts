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
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';

/**
 * Application list with filter and search (`state/gremium/type/topf/q`) and offset paging.
 * The filter and page state lives in the route query params. A filtered list is therefore
 * shareable as a link, for example from the budget area, and the browser back button works.
 * Visible controls exist for search, type and status. `gremium` and `topf` come from the
 * URL only. Pickers follow once the gremium and pot list endpoints exist.
 */
@Component({
  selector: 'app-applications-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PageHeaderComponent, FormsModule, TranslatePipe, ButtonComponent, IconComponent, SelectComponent, CurrencyInputComponent, DatepickerComponent, FilterBarComponent, FilterFieldComponent, FilterRangeComponent, CostCentreTreeComponent, ApplicationsTableComponent],
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

  /** Initial load after a filter or sort change. It hides the whole list. */
  readonly loading = signal(true);
  /** Load of more pages while scrolling. It is incremental and the list stays visible. */
  readonly loadingMore = signal(false);
  readonly error = signal(false);
  /** Accumulated applications across all loaded pages so far (infinite scroll). */
  readonly items = signal<ApplicationListItem[]>([]);
  readonly total = signal(0);
  private nextOffset = 0;
  /** Fetch sequence number. The fetch handler drops late responses from old filters. */
  private fetchSeq = 0;
  /** `gremium` and `topf` have no visible controls. They mirror the URL. */
  private gremium = '';
  private topf = '';
  readonly types = signal<ApplicationType[]>([]);

  /** Visible filter controls. They mirror the query params. */
  readonly q = signal('');
  /** Debounce timer of the header search (about 400 ms, like /expenses). */
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  readonly typeId = signal('');
  readonly state = signal('');
  /**
   * Which rows to show. Archived applications leave the working list by default; this is
   * how someone goes looking for one.
   *
   * Tri-state, because "only the archived ones" and "both" are different questions.
   */
  readonly archived = signal<'false' | 'true' | 'all'>('false');
  readonly archivedOptions = computed<SelectOption[]>(() => [
    { value: 'false', label: this.i18n.translate('applications.list.filter.archivedHide') },
    { value: 'true', label: this.i18n.translate('applications.list.filter.archivedOnly') },
    { value: 'all', label: this.i18n.translate('applications.list.filter.archivedAll') },
  ]);

  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Cost center tree for the left tree picker, with the look of the budget tab. */
  readonly budgetTree = signal<BudgetTreeNode[]>([]);

  /** Remove cost centers hidden in the budget tab, and their subtree, from the
   *  filter tree. This mirrors `visibleTree` of the budget dashboard. */
  private pruneHidden(nodes: BudgetTreeNode[]): BudgetTreeNode[] {
    return nodes
      .filter((n) => !n.hiddenInBudget)
      .map((n) => ({ ...n, children: this.pruneHidden(n.children) }));
  }
  /** Mobile: the tree sits behind a collapsible toggle. Desktop always shows it. */
  readonly treeOpen = signal(false);
  readonly sortField = signal<'createdAt' | 'amount'>('createdAt');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

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
        // Anything other than the default is a filter the reader has set.
        this.archived() === 'false' ? '' : this.archived(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  /**
   * Status dropdown options collected from the real states of the loaded applications.
   * The option value is the state UUID and the label is the resolved state name. The
   * `state` filter sends the UUID as its value (contract: `current_state_id`). The map
   * keeps every state seen once, so the filter does not collapse to a single value.
   */
  private readonly seenStates = signal<Map<string, string>>(new Map());
  readonly stateOptions = computed<SelectOption[]>(() =>
    [...this.seenStates()].map(([value, label]) => ({ value, label })),
  );

  /** True while unloaded applications are left. It controls the sentinel and "load more". */
  readonly hasMore = computed(() => this.items().length < this.total());

  /** Sentinel at the list end. The next load starts when it becomes visible. */
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  /** Application-type filter options. The value is the type UUID, the label the type name. */
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
    // Cost centers hidden in the budget tab (`hiddenInBudget`) do not appear in
    // the left filter picker either.
    this.budgetApi.tree().subscribe({
      next: (tree) => this.budgetTree.set(this.pruneHidden(tree)),
      error: () => this.budgetTree.set([]),
    });

    // The filter and sort values live in the query params. Every change resets
    // the list and reloads page 0. The offset is not in the URL (infinite
    // scroll). The component counts it up internally.
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
      const arch = pm.get('archived');
      this.archived.set(arch === 'true' || arch === 'all' ? arch : 'false');
      this.reload();
    });

    // Lazy infinite scroll: an IntersectionObserver on the sentinel loads the next
    // page once the list end comes into view. The rootMargin acts as a prefetch.
    // The effect re-binds whenever the sentinel appears or disappears, and the
    // sentinel exists only while hasMore is true.
    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      // Without a DOM API (SSR or tests) there is no observer. The "load more"
      // button then stays as the fallback.
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

  /** Select a cost center in the left tree and filter the list. `''` means all. */
  selectBudgetNode(id: string): void {
    this.budgetId.set(id);
    this.navigate({ budget: id || null, offset: null });
  }

  typeName(typeId: Uuid): string {
    return this.typesById().get(typeId) ?? typeId;
  }

  /** Application title from the system title field, with the fallback "untitled". */
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

  /** Export the current list as Excel. The filters come from the query params. */
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

  /** Header live search. After about 400 ms of debounce it writes the `q` query
   *  param and reloads, like /expenses. The `q` value stays in the URL, so the
   *  filtered list is shareable as a link. */
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

  /** Write a sort event of the shared table into the query params. */
  onSort(sort: SortState): void {
    this.navigate({ sort: sort.field, order: sort.order, offset: null });
  }

  /** Append the next page. The visible sentinel or the "load more" button calls this. */
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

  /** Reset the list after a filter or sort change and reload page 0. */
  protected reload(): void {
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loadingMore.set(false);
    this.loading.set(true);
    this.error.set(false);
    this.fetch(true);
  }

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
    // Only sent when it is not the server's own default, so the URL and the request
    // stay clean for the case everyone is in.
    if (this.archived() !== 'false') query.archived = this.archived();
    query.sort = this.sortField();
    query.order = this.sortOrder();
    return query;
  }

  /**
   * Fetch a page.
   *
   * With `initial` the page replaces the list and a failure shows the full error.
   * Without it the page appends and a load-more error stays silent, so the already
   * loaded list stays usable.
   */
  private fetch(initial: boolean): void {
    // Sequence number against out-of-order responses. After a fast filter change
    // a late page of the old filter must not overwrite the current list.
    const seq = ++this.fetchSeq;
    this.api.listApplications(this.buildQuery(this.nextOffset)).subscribe({
      next: (page) => {
        if (seq !== this.fetchSeq) return;
        this.total.set(page.total);
        this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
        // Count up by the real result count. The last page holds fewer than limit.
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
