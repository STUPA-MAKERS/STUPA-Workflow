import { computed, inject, signal, type WritableSignal } from '@angular/core';
import type { SelectOption } from '@stupa-makers/ui-kit';
import { downloadBlob } from '@shared/download.util';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
  type Expense,
  type ExpenseKind,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';

export type ExpenseSortField = 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate';

/**
 * Bookings list: server-side filters, sort and offset paging, plus the cost-center
 * tree behind the filters. This is a plain state module. Construct it in an
 * injection context, for example a component field initializer.
 */
export class ExpensesListState {
  private readonly api = inject(BudgetTreeApi);

  private readonly PAGE = 20;
  private nextOffset = 0;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  readonly budgetTree = signal<BudgetTreeNode[]>([]);
  readonly items = signal<Expense[]>([]);
  readonly total = signal(0);
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly hasMore = computed(() => this.items().length < this.total());
  /** Shared in-flight flag for every mutating dialog (create/edit/delete/sub/transfer). */
  readonly saving = signal(false);
  /** A refresh after a mutation is in flight. The list stays visible and only `aria-busy`
   *  changes. */
  readonly refreshing = signal(false);

  readonly kind = signal<'' | ExpenseKind>('');
  readonly q = signal('');
  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Exact-booking filter for a deep link. Only the URL sets it,
   *  and no control shows it. It still counts as an active filter, so the reset button
   *  clears it. */
  readonly expenseId = signal('');
  readonly sortField = signal<ExpenseSortField>('paymentDate');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  readonly activeFilterCount = computed(
    () =>
      [
        this.kind(),
        this.expenseId(),
        this.amountMin().trim(),
        this.amountMax().trim(),
        this.createdFrom(),
        this.createdTo(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  readonly costCentreOptions = computed<SelectOption[]>(() =>
    flattenBudgetOptions(this.budgetTree()),
  );

  readonly exporting = signal(false);

  constructor() {
    this.api.tree().subscribe({
      next: (tree) => this.budgetTree.set(tree),
      error: () => this.budgetTree.set([]),
    });
    // Do not reload here. The component adopts the URL filters first, then fires
    // exactly one reload. A second, unfiltered request can resolve late and overwrite
    // the filtered list.
  }

  setKind(k: '' | ExpenseKind): void {
    this.kind.set(k);
    this.reload();
  }

  selectBudget(id: string): void {
    this.budgetId.set(id);
    this.reload();
  }

  onSearch(value: string): void {
    this.q.set(value);
    this.debouncedReload();
  }

  onAmountFilter(which: 'min' | 'max', value: string): void {
    (which === 'min' ? this.amountMin : this.amountMax).set(value);
    this.debouncedReload();
  }

  onDateFilter(which: 'from' | 'to', value: string): void {
    (which === 'from' ? this.createdFrom : this.createdTo).set(value);
    this.debouncedReload();
  }

  /**
   * Every filter that reaches the request, and whether "Zurücksetzen" clears it.
   *
   * The reset and the request builder both read this list, so a filter reaches both or
   * neither. A filter wired into one alone is invisible: the control moves and the list
   * does not change. `filterSignals` is what the spec walks.
   *
   * `q` and `budgetId` are NOT cleared. Both are controls outside the filter panel — the
   * search box in the page header and the cost-centre tree beside the table — and the
   * reset button belongs to the panel. /applications clears both, because there the
   * search sits inside its panel.
   */
  readonly filterSignals: readonly { signal: WritableSignal<string>; clearedByReset: boolean }[] = [
    { signal: this.kind as WritableSignal<string>, clearedByReset: true },
    { signal: this.expenseId, clearedByReset: true },
    { signal: this.amountMin, clearedByReset: true },
    { signal: this.amountMax, clearedByReset: true },
    { signal: this.createdFrom, clearedByReset: true },
    { signal: this.createdTo, clearedByReset: true },
    { signal: this.q, clearedByReset: false },
    { signal: this.budgetId, clearedByReset: false },
  ];

  resetFilters(): void {
    for (const f of this.filterSignals) if (f.clearedByReset) f.signal.set('');
    this.reload();
  }

  onSort(field: ExpenseSortField): void {
    if (this.sortField() === field) {
      this.sortOrder.update((o) => (o === 'desc' ? 'asc' : 'desc'));
    } else {
      this.sortField.set(field);
      this.sortOrder.set('desc');
    }
    this.reload();
  }

  private debouncedReload(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reload(), 400);
  }

  reload(): void {
    // The filter state changes here, so every older in-flight response is stale.
    this.fetchEpoch++;
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loading.set(true);
    this.loadingMore.set(false);
    this.fetch(true);
  }

  loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  /** Active filters as the shared query part for {@link fetch} and {@link refresh}. */
  private filterParams() {
    return {
      id: this.expenseId() || undefined,
      budget: this.budgetId() || undefined,
      kind: this.kind() || undefined,
      q: this.q().trim() || undefined,
      amountMin: this.amountMin().trim() ? Number(this.amountMin()) : undefined,
      amountMax: this.amountMax().trim() ? Number(this.amountMax()) : undefined,
      createdFrom: this.createdFrom() || undefined,
      createdTo: this.createdTo() || undefined,
      sort: this.sortField(),
      order: this.sortOrder(),
    };
  }

  /** Monotone request generation. A response whose epoch does not match the current one
   *  belongs to an outdated filter state and must not touch the list. */
  private fetchEpoch = 0;

  /** Refetch the loaded window after a mutation. One request at offset 0 replaces the
   *  list. It never clears the list and never flips `loading`, so the table stays
   *  mounted and the scroll position and every infinite-scroll page survive. */
  refresh(): void {
    if (this.refreshing()) return;
    const epoch = this.fetchEpoch;
    const windowLimit = Math.max(this.PAGE, Math.ceil(this.items().length / this.PAGE) * this.PAGE);
    this.refreshing.set(true);
    this.api.listExpenses({ ...this.filterParams(), limit: windowLimit, offset: 0 }).subscribe({
      next: (page) => {
        this.refreshing.set(false);
        if (epoch !== this.fetchEpoch) return; // a reload ran meanwhile
        this.total.set(page.total);
        this.items.set(page.items);
        this.nextOffset = page.offset + page.items.length;
      },
      error: () => this.refreshing.set(false),
    });
  }

  private fetch(initial: boolean): void {
    const epoch = this.fetchEpoch;
    this.api
      .listExpenses({ ...this.filterParams(), limit: this.PAGE, offset: this.nextOffset })
      .subscribe({
        next: (page) => {
          if (epoch !== this.fetchEpoch) return; // fired for an older filter state
          this.total.set(page.total);
          this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.nextOffset = page.offset + page.items.length;
          this.loading.set(false);
          this.loadingMore.set(false);
        },
        error: () => {
          if (epoch !== this.fetchEpoch) return;
          this.loading.set(false);
          this.loadingMore.set(false);
        },
      });
  }

  onExport(): void {
    if (this.exporting()) return;
    this.exporting.set(true);
    this.api
      .exportExpensesXlsx({
        budget: this.budgetId() || undefined,
        kind: this.kind() || undefined,
        q: this.q().trim() || undefined,
        amountMin: this.amountMin().trim() || undefined,
        amountMax: this.amountMax().trim() || undefined,
        createdFrom: this.createdFrom() || undefined,
        createdTo: this.createdTo() || undefined,
      })
      .subscribe({
        next: (blob) => {
          downloadBlob(blob, 'buchungen.xlsx');
          this.exporting.set(false);
        },
        error: () => this.exporting.set(false),
      });
  }

  dispose(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
  }
}
