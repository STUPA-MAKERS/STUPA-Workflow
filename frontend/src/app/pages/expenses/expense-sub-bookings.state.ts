import { inject, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { Uuid } from '@core/api/models';
import { BudgetTreeApi, type Expense } from '../budget/budget-tree.api';
import { formatEur, problemCode } from '../budget/expense-display.util';
import type { ExpensesListState } from './expenses-list.state';

/**
 * Sub-bookings: expanded parents, the child cache, the CAMT.053/MT940 import and the
 * manual create dialog. The server keeps the amount of a parent equal to the sum of
 * its children, so the list reloads after every change to a child.
 */
export class ExpenseSubBookingsState {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly expandedSub = signal<ReadonlySet<string>>(new Set());
  readonly subRows = signal<ReadonlyMap<string, Expense[]>>(new Map());
  readonly loadingSub = signal<ReadonlySet<string>>(new Set());
  readonly subParent = signal<Expense | null>(null);
  readonly subAmount = signal('');
  readonly subDescription = signal('');
  readonly subPaymentDate = signal('');
  readonly subCorrespondent = signal('');

  constructor(private readonly list: ExpensesListState) {}

  isSubExpanded(id: string): boolean {
    return this.expandedSub().has(id);
  }

  subOf(id: string): Expense[] {
    return this.subRows().get(id) ?? [];
  }

  isLoadingSub(id: string): boolean {
    return this.loadingSub().has(id);
  }

  toggleSub(e: Expense): void {
    const open = new Set(this.expandedSub());
    if (open.has(e.id)) {
      open.delete(e.id);
      this.expandedSub.set(open);
      return;
    }
    open.add(e.id);
    this.expandedSub.set(open);
    if (!this.subRows().has(e.id)) this.loadSub(e.id);
  }

  loadSub(id: string): void {
    this.loadingSub.update((s) => new Set(s).add(id));
    this.api.listSubBookings(id as Uuid).subscribe({
      next: (rows) => {
        this.subRows.update((m) => new Map(m).set(id, rows));
        this.loadingSub.update((s) => {
          const n = new Set(s);
          n.delete(id);
          return n;
        });
      },
      error: () => {
        this.loadingSub.update((s) => {
          const n = new Set(s);
          n.delete(id);
          return n;
        });
        this.toast.error(this.i18n.translate('expenses.sub.loadError'));
      },
    });
  }

  // Global file import. The toolbar carries this action instead of each row
  // (#expenses-ux2).
  readonly importOpen = signal(false);
  readonly importQuery = signal('');
  readonly importCandidates = signal<Expense[]>([]);
  readonly importTarget = signal<Expense | null>(null);
  readonly importFile = signal<File | null>(null);
  readonly importBusy = signal(false);
  private importTimer: ReturnType<typeof setTimeout> | null = null;

  openImportDialog(): void {
    this.importOpen.set(true);
    this.importQuery.set('');
    this.importCandidates.set([]);
    this.importTarget.set(null);
    this.importFile.set(null);
  }

  closeImportDialog(): void {
    this.importOpen.set(false);
    if (this.importTimer) clearTimeout(this.importTimer);
  }

  importCandidateLabel(e: Expense): string {
    const parts = [e.description, formatEur(Math.abs(Number(e.amount)), this.i18n.locale())];
    if (e.pathKey) parts.push(e.pathKey);
    return parts.join(' · ');
  }

  onImportSearch(q: string): void {
    this.importQuery.set(q);
    this.importTarget.set(null);
    if (this.importTimer) clearTimeout(this.importTimer);
    this.importTimer = setTimeout(() => this.searchImportTargets(q.trim()), 300);
  }

  /** Target candidates. The list endpoint returns top-level bookings only, so every
   *  hit is a valid sub-booking parent. */
  private searchImportTargets(q: string): void {
    this.api.listExpenses({ q: q || undefined, limit: 10 }).subscribe({
      next: (page) => this.importCandidates.set(page.items),
      error: () => this.importCandidates.set([]),
    });
  }

  pickImportTarget(e: Expense): void {
    this.importTarget.set(e);
    this.importCandidates.set([]);
    this.importQuery.set(this.importCandidateLabel(e));
  }

  onImportFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.importFile.set(input.files?.[0] ?? null);
  }

  canSubmitImport(): boolean {
    return !!this.importTarget() && !!this.importFile() && !this.importBusy();
  }

  submitImport(event?: Event): void {
    event?.preventDefault();
    const target = this.importTarget();
    const file = this.importFile();
    if (!target || !file || this.importBusy()) return;
    this.importBusy.set(true);
    this.api.importSubBookings(target.id as Uuid, file).subscribe({
      next: (children) => {
        // The response holds the import batch only. Reload the full child list and
        // the booking list, because the parent amount changed.
        this.importBusy.set(false);
        this.importOpen.set(false);
        this.expandedSub.update((s) => new Set(s).add(target.id));
        this.loadSub(target.id);
        this.toast.success(
          this.i18n.translate('expenses.sub.imported', { count: String(children.length) }),
        );
        this.list.refresh();
      },
      error: (err) => {
        this.importBusy.set(false);
        this.toast.error(
          this.i18n.translate(
            problemCode(err) === 'bank_statement_unparseable'
              ? 'fints.errFile'
              : 'expenses.sub.importError',
          ),
        );
      },
    });
  }

  dispose(): void {
    if (this.importTimer) clearTimeout(this.importTimer);
  }

  openCreateSub(parent: Expense): void {
    this.subParent.set(parent);
    this.subAmount.set('');
    this.subDescription.set('');
    this.subPaymentDate.set('');
    this.subCorrespondent.set('');
  }

  closeCreateSub(): void {
    this.subParent.set(null);
  }

  canSubmitSub(): boolean {
    return !!this.subAmount().trim() && !!this.subDescription().trim();
  }

  createSub(event?: Event): void {
    event?.preventDefault();
    const parent = this.subParent();
    if (!parent || !this.canSubmitSub() || this.list.saving()) return;
    this.list.saving.set(true);
    this.api
      .createSubBooking(parent.id as Uuid, {
        amount: this.subAmount(),
        description: this.subDescription().trim(),
        paymentDate: this.subPaymentDate() || null,
        correspondent: this.subCorrespondent().trim() || null,
      })
      .subscribe({
        next: () => {
          this.list.saving.set(false);
          this.closeCreateSub();
          this.expandedSub.update((s) => new Set(s).add(parent.id));
          this.loadSub(parent.id);
          this.toast.success(this.i18n.translate('expenses.sub.added'));
          this.list.refresh();
        },
        error: () => {
          this.list.saving.set(false);
          this.toast.error(this.i18n.translate('expenses.toast.failed'));
        },
      });
  }
}
