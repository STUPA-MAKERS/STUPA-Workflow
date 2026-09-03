import { computed, inject, signal } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { BudgetTreeApi, type BudgetTransfer, type TransferUpdate } from '../budget/budget-tree.api';
import { problemDetail } from '../budget/expense-display.util';
import type { ExpensesListState } from './expenses-list.state';

/**
 * Cost-centre transfers as a first-class list.
 *
 * A transfer is two bookings that belong together. The bookings tab shows the
 * two legs but cannot correct them as a pair, so this module lists the
 * transfers themselves and offers an edit and a delete per row.
 *
 * The two cost centres are immutable on the server. The edit dialog therefore
 * shows the pair read-only and patches only amount, description, note and the
 * two dates. It is a plain state module. Construct it in an injection context.
 */
export class ExpenseTransfersState {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  private readonly PAGE = 20;
  private nextOffset = 0;
  /** Monotone request generation. A late response of an older filter state is
   *  dropped, exactly as in the bookings list. */
  private fetchEpoch = 0;

  readonly items = signal<BudgetTransfer[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly loadingMore = signal(false);
  readonly saving = signal(false);
  readonly hasMore = computed(() => this.items().length < this.total());
  /** True once a load ran. Before that the tab shows nothing, not "empty". */
  readonly loaded = signal(false);

  readonly editing = signal<BudgetTransfer | null>(null);
  readonly editAmount = signal('');
  readonly editDescription = signal('');
  readonly editNote = signal('');
  readonly editInvoiceDate = signal('');
  readonly editPaymentDate = signal('');
  readonly confirmDelete = signal<BudgetTransfer | null>(null);

  readonly canSubmitEdit = computed(
    () => !!this.editDescription().trim() && Number(this.editAmount()) > 0,
  );

  constructor(private readonly list: ExpensesListState) {}

  private failureText(err: unknown): string {
    return problemDetail(err) ?? this.i18n.translate('expenses.toast.failed');
  }

  /** The cost-centre filter and the search of the bookings tab also narrow the
   *  transfers. `budget` matches the source or the target cost centre. */
  private filterParams() {
    return {
      budget: this.list.budgetId() || undefined,
      q: this.list.q().trim() || undefined,
      amountMin: this.list.amountMin().trim() || undefined,
      amountMax: this.list.amountMax().trim() || undefined,
      createdFrom: this.list.createdFrom() || undefined,
      createdTo: this.list.createdTo() || undefined,
    };
  }

  reload(): void {
    this.fetchEpoch++;
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loading.set(true);
    this.fetch(true);
  }

  loadMore(): void {
    if (this.loading() || this.loadingMore() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  private fetch(initial: boolean): void {
    const epoch = this.fetchEpoch;
    this.api
      .listTransfers({ ...this.filterParams(), limit: this.PAGE, offset: this.nextOffset })
      .subscribe({
        next: (page) => {
          if (epoch !== this.fetchEpoch) return;
          this.total.set(page.total);
          this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.nextOffset = page.offset + page.items.length;
          this.loading.set(false);
          this.loadingMore.set(false);
          this.loaded.set(true);
        },
        error: (err) => {
          if (epoch !== this.fetchEpoch) return;
          this.loading.set(false);
          this.loadingMore.set(false);
          this.loaded.set(true);
          this.toast.error(this.failureText(err));
        },
      });
  }

  openEdit(t: BudgetTransfer): void {
    this.editing.set(t);
    this.editAmount.set(t.amount);
    this.editDescription.set(t.description);
    this.editNote.set(t.note ?? '');
    this.editInvoiceDate.set(t.invoiceDate ?? '');
    this.editPaymentDate.set(t.paymentDate ?? '');
  }

  closeEdit(): void {
    this.editing.set(null);
  }

  /**
   * Save the corrected transfer.
   *
   * The body carries no cost centre. The pair is immutable, and a different
   * pair answers 409. The bookings list refreshes too, because both legs of the
   * transfer are rows there.
   */
  saveEdit(event: Event): void {
    event.preventDefault();
    const t = this.editing();
    if (!t || !this.canSubmitEdit() || this.saving()) return;
    const body: TransferUpdate = {
      amount: this.editAmount(),
      description: this.editDescription().trim(),
      note: this.editNote().trim() || null,
      invoiceDate: this.editInvoiceDate() || null,
      paymentDate: this.editPaymentDate() || null,
    };
    this.saving.set(true);
    this.api.updateTransfer(t.transferId, body).subscribe({
      next: (updated) => {
        this.saving.set(false);
        this.editing.set(null);
        this.items.update((rows) =>
          rows.map((x) => (x.transferId === updated.transferId ? updated : x)),
        );
        this.toast.success(this.i18n.translate('expenses.transfers.saved'));
        this.list.refresh();
      },
      error: (err: { status?: number }) => {
        this.saving.set(false);
        // 409 = the cost-centre pair changed under us. Name the reason instead
        // of a generic failure, and reload so the row shows the server truth.
        if (err.status === 409) {
          this.toast.error(this.i18n.translate('expenses.transfers.immutablePair'));
          this.reload();
          return;
        }
        this.toast.error(this.failureText(err));
      },
    });
  }

  askDelete(t: BudgetTransfer): void {
    this.confirmDelete.set(t);
  }

  closeDelete(): void {
    this.confirmDelete.set(null);
  }

  /** Delete the transfer with both of its bookings. */
  doDelete(): void {
    const t = this.confirmDelete();
    if (!t || this.saving()) return;
    this.saving.set(true);
    this.api.deleteTransfer(t.transferId).subscribe({
      next: () => {
        this.saving.set(false);
        this.confirmDelete.set(null);
        this.items.update((rows) => rows.filter((x) => x.transferId !== t.transferId));
        this.total.update((n) => Math.max(0, n - 1));
        this.toast.success(this.i18n.translate('expenses.transfers.deleted'));
        this.list.refresh();
      },
      error: (err) => {
        this.saving.set(false);
        this.confirmDelete.set(null);
        this.toast.error(this.failureText(err));
      },
    });
  }
}
