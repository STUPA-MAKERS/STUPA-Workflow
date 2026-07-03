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
 * Accounts (left list) + server-side filtered/sorted/paged statement lines.
 * Plain state module — construct in an injection context.
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

  /** Reload the account list (incl. balance) while keeping the selection. */
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

  private fetch(initial: boolean): void {
    // 'linked'/'open' map to the linked flag (matched vs unmatched+suggested,
    // excludes ignored); 'ignored' filters the explicit state; '' = Alle, which
    // shows matched + open but hides set-aside (ignored) lines.
    const fs = this.filterState();
    const linked = fs === 'linked' ? true : fs === 'open' ? false : undefined;
    this.api
      .listStatementLines({
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
        limit: this.PAGE,
        offset: this.nextOffset,
      })
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
