import { inject, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { Uuid } from '@core/api/models';
import { BudgetTreeApi, type Expense } from '../budget/budget-tree.api';
import type { ExpensesListState } from './expenses-list.state';

/**
 * Sub-bookings: expanded parents, the child cache and the manual create dialog.
 * The server keeps the amount of a parent equal to the sum of its children, so
 * the list reloads after every change to a child.
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
