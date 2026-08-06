import { computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService, type SelectOption } from '@stupa-makers/ui-kit';
import { downloadBlob } from '@shared/download.util';
import {
  BudgetTreeApi,
  type Expense,
  type ExpenseKind,
  type FiscalYear,
  type Invoice,
  type PaymentMethod,
} from '../budget/budget-tree.api';
import { findTopBudgetNode, formatEur, problemDetail } from '../budget/expense-display.util';
import type { ExpensesListState } from './expenses-list.state';
import type { ExpenseSubBookingsState } from './expense-sub-bookings.state';
import type { ExpenseTransfersState } from './expense-transfers.state';

/**
 * Booking dialogs: create (standalone or application-bound), edit, delete, transfer
 * between cost centers, and the linked-invoice cache with its detail dialog.
 */
export class ExpenseDialogsState {
  private readonly api = inject(BudgetTreeApi);
  private readonly apps = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly createOpen = signal(false);
  readonly newKind = signal<ExpenseKind>('expense');
  readonly newAmount = signal('');
  readonly newDescription = signal('');
  readonly newBudgetId = signal('');
  readonly newFiscalYearId = signal('');
  readonly newApplicationId = signal('');
  readonly appQuery = signal('');
  readonly appCandidates = signal<{ id: string; title: string }[]>([]);
  readonly fiscalYearOptions = signal<SelectOption[]>([]);
  readonly newInvoiceDate = signal('');
  readonly newPaymentDate = signal('');
  readonly newCorrespondent = signal('');
  readonly newReferenceNumber = signal('');
  readonly newPaymentMethod = signal('');
  readonly newCategory = signal('');
  readonly newNote = signal('');

  readonly paymentMethodOptions = computed<SelectOption[]>(() =>
    (['ueberweisung', 'bar', 'lastschrift', 'karte', 'paypal'] as const).map((v) => ({
      value: v,
      label: this.i18n.translate(`expenses.paymentMethod.${v}`),
    })),
  );

  readonly editing = signal<Expense | null>(null);
  readonly editAmount = signal('');
  readonly editDescription = signal('');
  readonly editBudgetId = signal('');
  readonly editInvoiceDate = signal('');
  readonly editPaymentDate = signal('');
  readonly editCorrespondent = signal('');
  readonly editReferenceNumber = signal('');
  readonly editPaymentMethod = signal('');
  readonly editCategory = signal('');
  readonly editNote = signal('');
  readonly confirmDelete = signal<Expense | null>(null);

  // Linked invoices. One invoice can back many bookings.
  readonly invoices = signal<Invoice[]>([]);
  readonly newInvoiceId = signal('');
  readonly editInvoiceId = signal('');
  readonly viewingInvoice = signal<Invoice | null>(null);
  /** Open invoices, newest issue date first. A booking marks its linked invoice paid
   *  on the server, so paid invoices drop out of the create dropdown. */
  private readonly openInvoices = computed<Invoice[]>(() =>
    this.invoices()
      .filter((i) => i.status === 'open')
      .sort((a, b) => (b.issueDate ?? '').localeCompare(a.issueDate ?? '')),
  );
  readonly invoiceOptions = computed<SelectOption[]>(() =>
    this.openInvoices().map((i) => ({ value: i.id, label: this.invoiceLabel(i) })),
  );
  /** Edit keeps the currently linked (possibly paid) invoice selectable. */
  readonly editInvoiceOptions = computed<SelectOption[]>(() => {
    const opts = this.openInvoices().map((i) => ({ value: i.id, label: this.invoiceLabel(i) }));
    const linkedId = this.editInvoiceId();
    if (linkedId && !opts.some((o) => o.value === linkedId)) {
      const inv = this.invoices().find((i) => i.id === linkedId);
      if (inv) opts.unshift({ value: inv.id, label: this.invoiceLabel(inv) });
    }
    return opts;
  });

  readonly transferOpen = signal(false);
  readonly tFromId = signal('');
  readonly tToId = signal('');
  readonly tFiscalYearId = signal('');
  readonly tAmount = signal('');
  readonly tDescription = signal('');
  readonly transferFyOptions = signal<SelectOption[]>([]);
  readonly canSubmitTransfer = computed(
    () =>
      !!this.tFromId() &&
      !!this.tToId() &&
      this.tFromId() !== this.tToId() &&
      !!this.tFiscalYearId() &&
      Number(this.tAmount()) > 0 &&
      !!this.tDescription().trim(),
  );

  readonly canSubmitCreate = computed(() => {
    if (!this.newDescription().trim() || !(Number(this.newAmount()) > 0)) return false;
    // A bound booking inherits the cost center and the fiscal year from the application.
    if (this.newApplicationId()) return true;
    // A standalone booking needs both. The server answers 422 without them.
    return !!this.newBudgetId() && !!this.newFiscalYearId();
  });

  constructor(
    private readonly list: ExpensesListState,
    private readonly sub: ExpenseSubBookingsState,
    private readonly transfers: ExpenseTransfersState,
  ) {
    this.loadInvoices();
  }

  private invoiceLabel(i: Invoice): string {
    return [i.number, i.supplier, formatEur(Number(i.grossAmount), this.i18n.locale())]
      .filter((p) => !!p)
      .join(' · ');
  }

  private failureText(err: unknown): string {
    return problemDetail(err) ?? this.i18n.translate('expenses.toast.failed');
  }

  /** A booking marks its linked invoice paid, so refresh the open-invoice dropdown. */
  private loadInvoices(): void {
    this.api.listInvoices().subscribe({
      next: (rows) => this.invoices.set(rows),
      error: () => this.invoices.set([]),
    });
  }

  openCreate(): void {
    this.newKind.set('expense');
    this.newAmount.set('');
    this.newDescription.set('');
    this.newBudgetId.set(this.list.budgetId() || '');
    this.newFiscalYearId.set('');
    this.newApplicationId.set('');
    this.newInvoiceId.set('');
    this.newInvoiceDate.set('');
    this.newPaymentDate.set('');
    this.newCorrespondent.set('');
    this.newReferenceNumber.set('');
    this.newPaymentMethod.set('');
    this.newCategory.set('');
    this.newNote.set('');
    this.appQuery.set('');
    this.appCandidates.set([]);
    this.fiscalYearOptions.set([]);
    if (this.list.budgetId()) this.loadFiscalYears(this.list.budgetId());
    this.createOpen.set(true);
  }

  setNewKindIncome(): void {
    this.newKind.set('income');
    // Income cannot be bound to an application.
    this.clearApp();
  }

  onAppSearch(value: string): void {
    this.appQuery.set(value);
    const q = value.trim();
    if (!q) {
      this.appCandidates.set([]);
      return;
    }
    this.apps.listApplications({ q, limit: 8 }).subscribe({
      next: (page) =>
        this.appCandidates.set(page.items.map((a) => ({ id: a.id, title: a.title || a.id }))),
      error: () => this.appCandidates.set([]),
    });
  }

  pickApp(a: { id: string; title: string }): void {
    this.newApplicationId.set(a.id);
    this.appQuery.set(a.title);
    this.appCandidates.set([]);
  }

  clearApp(): void {
    this.newApplicationId.set('');
    this.appQuery.set('');
    this.appCandidates.set([]);
  }

  onPickBudget(id: string): void {
    this.newBudgetId.set(id);
    this.newFiscalYearId.set('');
    this.fiscalYearOptions.set([]);
    if (id) this.loadFiscalYears(id);
  }

  private loadFiscalYears(budgetId: string): void {
    const top = findTopBudgetNode(this.list.budgetTree(), budgetId);
    if (!top) return;
    this.api.listFiscalYears(top.id).subscribe({
      next: (fys: FiscalYear[]) => {
        // Offer every fiscal year. An inactive one is allowed on purpose.
        this.fiscalYearOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        const active = fys.filter((f) => f.active);
        if (active.length === 1) this.newFiscalYearId.set(active[0].id);
      },
      error: () => this.fiscalYearOptions.set([]),
    });
  }

  onPickInvoice(id: string): void {
    this.newInvoiceId.set(id);
    const inv = this.invoices().find((i) => i.id === id);
    if (!inv) return;
    this.newAmount.set(inv.grossAmount ?? '');
    if (inv.supplier) this.newCorrespondent.set(inv.supplier);
    if (inv.number) this.newReferenceNumber.set(inv.number);
    if (inv.issueDate) this.newInvoiceDate.set(inv.issueDate);
  }

  onPickEditInvoice(id: string): void {
    this.editInvoiceId.set(id);
    const inv = this.invoices().find((i) => i.id === id);
    if (!inv) return;
    this.editAmount.set(inv.grossAmount ?? '');
    if (inv.supplier) this.editCorrespondent.set(inv.supplier);
    if (inv.number) this.editReferenceNumber.set(inv.number);
    if (inv.issueDate) this.editInvoiceDate.set(inv.issueDate);
  }

  create(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitCreate() || this.list.saving()) return;
    const linked = !!this.newApplicationId();
    this.list.saving.set(true);
    this.api
      .bookExpense({
        amount: this.newAmount(),
        description: this.newDescription().trim(),
        kind: this.newKind(),
        applicationId: linked ? this.newApplicationId() : null,
        budgetId: linked ? null : this.newBudgetId() || null,
        fiscalYearId: linked ? null : this.newFiscalYearId() || null,
        invoiceId: this.newInvoiceId() || null,
        invoiceDate: this.newInvoiceDate() || null,
        paymentDate: this.newPaymentDate() || null,
        correspondent: this.newCorrespondent().trim() || null,
        referenceNumber: this.newReferenceNumber().trim() || null,
        paymentMethod: (this.newPaymentMethod() as PaymentMethod) || null,
        category: this.newCategory().trim() || null,
        note: this.newNote().trim() || null,
      })
      .subscribe({
        next: () => {
          this.list.saving.set(false);
          this.createOpen.set(false);
          this.toast.success(this.i18n.translate('expenses.toast.created'));
          this.loadInvoices();
          this.list.refresh();
        },
        error: (err) => {
          this.list.saving.set(false);
          this.toast.error(this.failureText(err));
        },
      });
  }

  openInvoiceDialog(e: Expense): void {
    if (!e.invoiceId) return;
    const cached = this.invoices().find((i) => i.id === e.invoiceId);
    if (cached) {
      this.viewingInvoice.set(cached);
      return;
    }
    // A linked invoice is often paid or old and can sit outside the capped list cache.
    this.api.getInvoice(e.invoiceId).subscribe({
      next: (inv) => this.viewingInvoice.set(inv),
      error: (err) => this.toast.error(this.failureText(err)),
    });
  }

  /** MinIO is internal only, so the API streams the PDF as a blob. */
  openInvoiceFile(inv: Invoice): void {
    this.api.invoiceFileBlob(inv.id).subscribe({
      next: (blob) => downloadBlob(blob, inv.fileName || 'beleg.pdf'),
      error: (err) => this.toast.error(this.failureText(err)),
    });
  }

  openEdit(e: Expense): void {
    this.editing.set(e);
    this.editAmount.set(e.amount);
    this.editDescription.set(e.description);
    this.editBudgetId.set(e.budgetId);
    this.editInvoiceId.set(e.invoiceId ?? '');
    this.editInvoiceDate.set(e.invoiceDate ?? '');
    this.editPaymentDate.set(e.paymentDate ?? '');
    this.editCorrespondent.set(e.correspondent ?? '');
    this.editReferenceNumber.set(e.referenceNumber ?? '');
    this.editPaymentMethod.set(e.paymentMethod ?? '');
    this.editCategory.set(e.category ?? '');
    this.editNote.set(e.note ?? '');
  }

  saveEdit(event: Event): void {
    event.preventDefault();
    const e = this.editing();
    if (!e || this.list.saving()) return;
    this.list.saving.set(true);
    // Only a standalone booking can move to another cost center. A bound booking
    // inherits it from the application. Send the field only after a change.
    const budgetChanged =
      !e.applicationId && !!this.editBudgetId() && this.editBudgetId() !== e.budgetId;
    // The amount of a parent (childCount > 0) is the sum of its children and
    // read-only on the server. Send it only after a change.
    const amountChanged = this.editAmount() !== e.amount;
    this.api
      .updateExpense(e.id, {
        ...(amountChanged ? { amount: this.editAmount() } : {}),
        description: this.editDescription().trim(),
        ...(budgetChanged ? { budgetId: this.editBudgetId() } : {}),
        invoiceId: this.editInvoiceId() || null,
        invoiceDate: this.editInvoiceDate() || null,
        paymentDate: this.editPaymentDate() || null,
        correspondent: this.editCorrespondent().trim() || null,
        referenceNumber: this.editReferenceNumber().trim() || null,
        paymentMethod: (this.editPaymentMethod() as PaymentMethod) || null,
        category: this.editCategory().trim() || null,
        note: this.editNote().trim() || null,
      })
      .subscribe({
        next: (updated) => {
          this.list.saving.set(false);
          this.editing.set(null);
          if (e.parentExpenseId) {
            // A sub-booking changed, so refresh the parent panel and the parent amount.
            this.sub.loadSub(e.parentExpenseId);
            this.list.refresh();
          } else {
            // The single-item response does not carry childCount and parentExpenseId
            // reliably. Keep both values from the known row.
            const merged = {
              ...updated,
              childCount: e.childCount,
              parentExpenseId: e.parentExpenseId,
            };
            this.list.items.update((rows) => rows.map((x) => (x.id === merged.id ? merged : x)));
          }
          this.toast.success(this.i18n.translate('expenses.toast.saved'));
          this.loadInvoices();
        },
        error: () => {
          this.list.saving.set(false);
          this.toast.error(this.i18n.translate('expenses.toast.failed'));
        },
      });
  }

  askDelete(e: Expense): void {
    this.confirmDelete.set(e);
  }

  doDelete(): void {
    const e = this.confirmDelete();
    if (!e || this.list.saving()) return;
    this.list.saving.set(true);
    this.api.deleteExpense(e.id).subscribe({
      next: () => {
        this.list.saving.set(false);
        this.confirmDelete.set(null);
        if (e.parentExpenseId) {
          // A sub-booking is gone, so refresh the parent panel and the parent amount.
          this.sub.loadSub(e.parentExpenseId);
          this.list.refresh();
        } else {
          this.list.items.update((rows) => rows.filter((x) => x.id !== e.id));
          this.list.total.update((t) => Math.max(0, t - 1));
        }
        this.toast.success(this.i18n.translate('expenses.toast.deleted'));
      },
      error: () => {
        this.list.saving.set(false);
        this.toast.error(this.i18n.translate('expenses.toast.failed'));
      },
    });
  }

  openTransfer(): void {
    this.tFromId.set(this.list.budgetId() || '');
    this.tToId.set('');
    this.tFiscalYearId.set('');
    this.tAmount.set('');
    this.tDescription.set('');
    this.transferFyOptions.set([]);
    if (this.tFromId()) this.loadTransferFy(this.tFromId());
    this.transferOpen.set(true);
  }

  onTransferFrom(id: string): void {
    this.tFromId.set(id);
    this.tFiscalYearId.set('');
    this.transferFyOptions.set([]);
    if (id) this.loadTransferFy(id);
  }

  private loadTransferFy(budgetId: string): void {
    const top = findTopBudgetNode(this.list.budgetTree(), budgetId);
    if (!top) return;
    this.api.listFiscalYears(top.id).subscribe({
      next: (fys: FiscalYear[]) => {
        this.transferFyOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        const active = fys.filter((f) => f.active);
        if (active.length === 1) this.tFiscalYearId.set(active[0].id);
      },
      error: () => this.transferFyOptions.set([]),
    });
  }

  createTransfer(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitTransfer() || this.list.saving()) return;
    this.list.saving.set(true);
    this.api
      .createTransfer({
        fromBudgetId: this.tFromId(),
        toBudgetId: this.tToId(),
        fiscalYearId: this.tFiscalYearId(),
        amount: this.tAmount(),
        description: this.tDescription().trim(),
      })
      .subscribe({
        next: () => {
          this.list.saving.set(false);
          this.transferOpen.set(false);
          this.toast.success(this.i18n.translate('expenses.transferToast'));
          this.list.refresh();
          // The transfers tab holds the new row too. Refresh it if it already
          // loaded, so the two views never disagree.
          if (this.transfers.loaded()) this.transfers.reload();
        },
        error: (err) => {
          this.list.saving.set(false);
          this.toast.error(this.failureText(err));
        },
      });
  }
}
