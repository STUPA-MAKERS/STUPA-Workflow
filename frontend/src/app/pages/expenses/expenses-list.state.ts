import { computed, inject, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import type { SelectOption } from '@stupa-makers/ui-kit';
import { downloadBlob } from '@shared/download.util';
import {
  type AccountOption,
  BudgetTreeApi,
  type BudgetTreeNode,
  type Expense,
  type ExpenseKind,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';

export type ExpenseSortField = 'createdAt' | 'amount' | 'invoiceDate' | 'paymentDate';

/**
 * Bookings list: server-side filters, sort and offset paging, plus the cost-center
 * tree and the account options behind the filters. This is a plain state module.
 * Construct it in an injection context, for example a component field initializer.
 */
export class ExpensesListState {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);

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
   *  changes (#expenses-ux). */
  readonly refreshing = signal(false);

  readonly kind = signal<'' | ExpenseKind>('');
  readonly q = signal('');
  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Account filter. An empty value means all accounts. */
  readonly accountId = signal('');
  /** Exact-booking filter for a deep link from the accounts page. Only the URL sets it,
   *  and no control shows it. It still counts as an active filter, so the reset button
   *  clears it. */
  readonly expenseId = signal('');
  readonly sortField = signal<ExpenseSortField>('paymentDate');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  readonly activeFilterCount = computed(
    () =>
      [
        this.kind(),
        this.accountId(),
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

  readonly accounts = signal<AccountOption[]>([]);
  readonly accountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );
  readonly accountFilterOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('expenses.filter.allAccounts') },
    ...this.accountOptions(),
  ]);

  readonly exporting = signal(false);

  constructor() {
    this.api.tree().subscribe({
      next: (tree) => this.budgetTree.set(tree),
      error: () => this.budgetTree.set([]),
    });
    // Bookers may read account options without account.manage. The server returns
    // active accounts only.
    this.api.listAccountOptions().subscribe({
      next: (accs) => this.accounts.set(accs),
      error: () => this.accounts.set([]),
    });
    // Do not reload here. The component adopts the URL filters first, then fires
    // exactly one reload. A second, unfiltered request can resolve late and overwrite
    // the filtered list (#expenses-ux2).
  }

  setKind(k: '' | ExpenseKind): void {
    this.kind.set(k);
    this.reload();
  }

  selectAccount(id: string): void {
    this.accountId.set(id);
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

  resetFilters(): void {
    this.kind.set('');
    this.accountId.set('');
    this.expenseId.set('');
    this.amountMin.set('');
    this.amountMax.set('');
    this.createdFrom.set('');
    this.createdTo.set('');
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
      account: this.accountId() || undefined,
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

  /** Monotone request generation. A response whose epoch no longer matches belongs to an
   *  outdated filter state. Such a response must not touch the list (#expenses-ux2). */
  private fetchEpoch = 0;

  /** Refetch the loaded window after a mutation. One request at offset 0 replaces the
   *  list. The method never clears the list and never flips `loading`. The table stays
   *  mounted, and the scroll position and all infinite-scroll pages survive
   *  (#expenses-ux). */
  refresh(): void {
    if (this.refreshing()) return;
    const epoch = this.fetchEpoch;
    const windowLimit = Math.max(this.PAGE, Math.ceil(this.items().length / this.PAGE) * this.PAGE);
    this.refreshing.set(true);
    this.api
      .listExpenses({ ...this.filterParams(), limit: windowLimit, offset: 0 })
      .subscribe({
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
