import { computed, inject, signal } from '@angular/core';
import type { Uuid } from '@core/api/models';
import type { SelectOption } from '@stupa-makers/ui-kit';
import {
  type AccountOption,
  BudgetTreeApi,
  type ExpenseKind,
  type StatementLine,
} from '../budget/budget-tree.api';

export type StatementSortField = 'date' | 'amount';

/**
 * This class holds accounts in the left list plus the statement lines. The server
 * filters, sorts, and pages the lines. This is a plain state module. Construct it in
 * an injection context.
 */
export class KontenLinesState {
  private readonly api = inject(BudgetTreeApi);

  private readonly PAGE = 30;
  private nextOffset = 0;
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  readonly accounts = signal<AccountOption[]>([]);
  readonly accountId = signal<string>('');
  readonly selectedAccount = computed<AccountOption | null>(
    () => this.accounts().find((a) => a.id === this.accountId()) ?? null,
  );
  readonly accountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({ value: a.id, label: a.name })),
  );

  readonly lines = signal<StatementLine[]>([]);
  readonly loadingLines = signal(false);
  /** True while a refresh after a mutation runs. The list stays visible. The view only
   *  sets `aria-busy`. See #expenses-ux. */
  readonly refreshing = signal(false);
  readonly loadingMore = signal(false);
  readonly total = signal(0);
  readonly hasMore = computed(() => this.lines().length < this.total());

  readonly filterState = signal<'' | 'open' | 'linked' | 'ignored'>('');
  readonly kind = signal<'' | ExpenseKind>('');
  readonly searchQ = signal('');
  readonly dateFrom = signal('');
  readonly dateTo = signal('');
  readonly sortField = signal<StatementSortField>('date');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');
  readonly activeFilterCount = computed(
    () =>
      (this.filterState() ? 1 : 0) +
      (this.kind() ? 1 : 0) +
      (this.dateFrom() || this.dateTo() ? 1 : 0),
  );

  constructor() {
    this.refreshAccounts();
  }

  /** Reload the account list with the balance and keep the selection. */
  refreshAccounts(): void {
    this.api.listAccountOptions().subscribe({
      next: (accs) => {
        this.accounts.set(accs);
        if (!this.accountId() && accs.length) this.accountId.set(accs[0].id);
      },
      error: () => this.accounts.set([]),
    });
  }

  reloadLines(): void {
    if (!this.accountId()) return;
    this.nextOffset = 0;
    this.lines.set([]);
    this.total.set(0);
    this.loadingLines.set(true);
    this.fetch(true);
  }

  loadMore(): void {
    if (this.loadingMore() || this.loadingLines() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  /** The active filters build the shared query part for {@link fetch} and {@link refresh}.
   *  `linked` maps to `linked: true`, for matched lines. `open` maps to `linked: false`,
   *  for unmatched lines. Both exclude ignored lines. `ignored` filters on the explicit
   *  ignored state. An empty value means all. It shows matched and open lines, but it
   *  hides ignored (set-aside) lines. */
  private lineQuery() {
    const fs = this.filterState();
    const linked = fs === 'linked' ? true : fs === 'open' ? false : undefined;
    return {
      account: this.accountId() as Uuid,
      state: fs === 'ignored' ? 'ignored' : undefined,
      linked,
      includeIgnored: fs === '' ? false : undefined,
      kind: this.kind() || undefined,
      q: this.searchQ().trim() || undefined,
      dateFrom: this.dateFrom() || undefined,
      dateTo: this.dateTo() || undefined,
      sort: this.sortField(),
      order: this.sortOrder(),
    };
  }

  /** After a mutation, refetch the loaded window with one request at offset 0. Replace
   *  the list in one step. It does not clear the list and does not flip
   *  `loadingLines`. So the table stays mounted, and the scroll position survives.
   *  See #expenses-ux. */
  refresh(): void {
    if (!this.accountId() || this.refreshing()) return;
    const windowLimit = Math.max(this.PAGE, Math.ceil(this.lines().length / this.PAGE) * this.PAGE);
    this.refreshing.set(true);
    this.api
      .listStatementLines({ ...this.lineQuery(), limit: windowLimit, offset: 0 })
      .subscribe({
        next: (page) => {
          this.total.set(page.total);
          this.lines.set(page.items);
          this.nextOffset = page.offset + page.items.length;
          this.refreshing.set(false);
        },
        error: () => this.refreshing.set(false),
      });
  }

  private fetch(initial: boolean): void {
    this.api
      .listStatementLines({ ...this.lineQuery(), limit: this.PAGE, offset: this.nextOffset })
      .subscribe({
        next: (page) => {
          this.total.set(page.total);
          this.lines.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.nextOffset = page.offset + page.items.length;
          this.loadingLines.set(false);
          this.loadingMore.set(false);
        },
        error: () => {
          if (initial) this.lines.set([]);
          this.loadingLines.set(false);
          this.loadingMore.set(false);
        },
      });
  }

  setState(s: '' | 'open' | 'linked' | 'ignored'): void {
    this.filterState.set(s);
    this.reloadLines();
  }

  setKind(k: '' | ExpenseKind): void {
    this.kind.set(k);
    this.reloadLines();
  }

  onDateFilter(which: 'from' | 'to', value: string): void {
    (which === 'from' ? this.dateFrom : this.dateTo).set(value || '');
    this.reloadLines();
  }

  resetFilters(): void {
    this.filterState.set('');
    this.kind.set('');
    this.dateFrom.set('');
    this.dateTo.set('');
    this.reloadLines();
  }

  onSearch(v: string): void {
    this.searchQ.set(v);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reloadLines(), 400);
  }

  onSort(field: StatementSortField): void {
    if (this.sortField() === field) this.sortOrder.update((o) => (o === 'desc' ? 'asc' : 'desc'));
    else {
      this.sortField.set(field);
      this.sortOrder.set('desc');
    }
    this.reloadLines();
  }

  dispose(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
  }
}
