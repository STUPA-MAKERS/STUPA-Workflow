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
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CheckboxComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  SelectComponent,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import {
  BudgetTreeApi,
  type BudgetTransfer,
  type Expense,
  type ExpenseKind,
  type ExpenseUpdate,
  type Invoice,
} from '../budget/budget-tree.api';
import type { Uuid } from '@core/api/models';
import {
  ariaSortDir,
  findTopBudgetNode,
  formatEur,
  problemDetail,
  sortIndicator,
} from '../budget/expense-display.util';
import { SimplifyPathPipe } from '@shared/budget-path';
import { downloadBlob } from '@shared/download.util';
import { HScrollSyncDirective } from '@shared/h-scroll-sync.directive';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { PressSelectDirective } from '@shared/press-select.directive';
import { ExpenseDialogsState } from './expense-dialogs.state';
import { ExpenseSubBookingsState } from './expense-sub-bookings.state';
import { ExpenseTransfersState } from './expense-transfers.state';
import { ExpensesListState, type ExpenseSortField } from './expenses-list.state';

/** The two views of the page. Bookings are the default. */
export type ExpensesTab = 'bookings' | 'transfers';

/**
 * Bookings tab. It shows, creates, and manages expense and income bookings.
 *
 * A booking is either standalone or bound to an application. A standalone booking needs
 * a cost center and a fiscal year. A bound booking inherits both. This class is a thin
 * facade over the state modules below. Its public surface also drives the specs.
 */
@Component({
  selector: 'app-expenses',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    FormsModule,
    LocalizedDatePipe,
    TranslatePipe,
    SimplifyPathPipe,
    BadgeComponent,
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    FilterBarComponent,
    FilterFieldComponent,
    FilterRangeComponent,
    IconComponent,
    SelectComponent,
    CheckboxComponent,
    CostCentreTreeComponent,
    HScrollSyncDirective,
    PressSelectDirective,
    RouterLink,
  ],
  templateUrl: './expenses.component.html',
  styleUrl: './expenses.component.scss',
})
export class ExpensesComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  // The state modules share this root toast instance. Specs spy on it here.
  private readonly toast = inject(ToastService);
  private readonly api = inject(BudgetTreeApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly list = new ExpensesListState();
  private readonly sub = new ExpenseSubBookingsState(this.list);
  private readonly transfers = new ExpenseTransfersState(this.list);
  private readonly dialogs = new ExpenseDialogsState(this.list, this.sub, this.transfers);

  readonly canManage = computed(() => this.auth.can('budget.book'));
  readonly canExport = computed(() => this.auth.can('budget.export'));

  readonly budgetTree = this.list.budgetTree;
  readonly items = this.list.items;
  readonly total = this.list.total;
  readonly loading = this.list.loading;
  readonly loadingMore = this.list.loadingMore;
  readonly hasMore = this.list.hasMore;
  readonly saving = this.list.saving;
  readonly kind = this.list.kind;
  readonly q = this.list.q;
  readonly amountMin = this.list.amountMin;
  readonly amountMax = this.list.amountMax;
  readonly createdFrom = this.list.createdFrom;
  readonly createdTo = this.list.createdTo;
  readonly budgetId = this.list.budgetId;
  readonly expenseId = this.list.expenseId;
  readonly sortField = this.list.sortField;
  readonly sortOrder = this.list.sortOrder;
  readonly activeFilterCount = this.list.activeFilterCount;
  readonly costCentreOptions = this.list.costCentreOptions;
  readonly exporting = this.list.exporting;
  readonly refreshing = this.list.refreshing;

  // Batch and bulk actions. See #expenses-ux.
  readonly selected = signal<ReadonlySet<Uuid>>(new Set());
  readonly bulkBusy = signal(false);
  readonly selectedCount = computed(() => this.selected().size);
  readonly allSelected = computed(() => {
    const list = this.items();
    return list.length > 0 && list.every((e) => this.selected().has(e.id));
  });
  /** The bulk confirm dialog signal is null when closed. Otherwise it holds the
   *  pending action, delete or export. */
  readonly bulkConfirm = signal<null | 'delete' | 'export'>(null);
  /** Select-all must not enable mass deletion. The user must pick each row for the
   *  destructive bulk action. See #expenses-ux2. */
  readonly bulkDeleteBlocked = computed(() => this.allSelected() && this.selectedCount() > 1);
  readonly bulkReassignOpen = signal(false);
  readonly bulkBudgetId = signal('');
  readonly bulkCategory = signal('');
  readonly canSubmitReassign = computed(
    () => !!this.bulkBudgetId() || !!this.bulkCategory().trim(),
  );

  readonly createOpen = this.dialogs.createOpen;
  readonly newKind = this.dialogs.newKind;
  readonly newAmount = this.dialogs.newAmount;
  readonly newDescription = this.dialogs.newDescription;
  readonly newBudgetId = this.dialogs.newBudgetId;
  readonly newFiscalYearId = this.dialogs.newFiscalYearId;
  readonly newApplicationId = this.dialogs.newApplicationId;
  readonly appQuery = this.dialogs.appQuery;
  readonly appCandidates = this.dialogs.appCandidates;
  readonly fiscalYearOptions = this.dialogs.fiscalYearOptions;
  readonly newInvoiceDate = this.dialogs.newInvoiceDate;
  readonly newPaymentDate = this.dialogs.newPaymentDate;
  readonly newCorrespondent = this.dialogs.newCorrespondent;
  readonly newReferenceNumber = this.dialogs.newReferenceNumber;
  readonly newPaymentMethod = this.dialogs.newPaymentMethod;
  readonly newCategory = this.dialogs.newCategory;
  readonly newNote = this.dialogs.newNote;
  readonly paymentMethodOptions = this.dialogs.paymentMethodOptions;
  readonly editing = this.dialogs.editing;
  readonly editAmount = this.dialogs.editAmount;
  readonly editDescription = this.dialogs.editDescription;
  readonly editBudgetId = this.dialogs.editBudgetId;
  readonly editInvoiceDate = this.dialogs.editInvoiceDate;
  readonly editPaymentDate = this.dialogs.editPaymentDate;
  readonly editCorrespondent = this.dialogs.editCorrespondent;
  readonly editReferenceNumber = this.dialogs.editReferenceNumber;
  readonly editPaymentMethod = this.dialogs.editPaymentMethod;
  readonly editCategory = this.dialogs.editCategory;
  readonly editNote = this.dialogs.editNote;
  readonly confirmDelete = this.dialogs.confirmDelete;
  readonly invoices = this.dialogs.invoices;
  readonly newInvoiceId = this.dialogs.newInvoiceId;
  readonly editInvoiceId = this.dialogs.editInvoiceId;
  readonly viewingInvoice = this.dialogs.viewingInvoice;
  readonly invoiceOptions = this.dialogs.invoiceOptions;
  readonly editInvoiceOptions = this.dialogs.editInvoiceOptions;
  readonly transferOpen = this.dialogs.transferOpen;
  readonly tFromId = this.dialogs.tFromId;
  readonly tToId = this.dialogs.tToId;
  readonly tFiscalYearId = this.dialogs.tFiscalYearId;
  readonly tAmount = this.dialogs.tAmount;
  readonly tDescription = this.dialogs.tDescription;
  readonly transferFyOptions = this.dialogs.transferFyOptions;
  readonly canSubmitTransfer = this.dialogs.canSubmitTransfer;
  readonly canSubmitCreate = this.dialogs.canSubmitCreate;

  readonly tab = signal<ExpensesTab>('bookings');
  readonly transferItems = this.transfers.items;
  readonly transferTotal = this.transfers.total;
  readonly transferLoading = this.transfers.loading;
  readonly transferLoadingMore = this.transfers.loadingMore;
  readonly transferHasMore = this.transfers.hasMore;
  readonly transferSaving = this.transfers.saving;
  readonly editingTransfer = this.transfers.editing;
  readonly tEditAmount = this.transfers.editAmount;
  readonly tEditDescription = this.transfers.editDescription;
  readonly tEditNote = this.transfers.editNote;
  readonly tEditInvoiceDate = this.transfers.editInvoiceDate;
  readonly tEditPaymentDate = this.transfers.editPaymentDate;
  readonly confirmDeleteTransfer = this.transfers.confirmDelete;
  readonly canSubmitTransferEdit = this.transfers.canSubmitEdit;

  readonly subParent = this.sub.subParent;
  readonly subAmount = this.sub.subAmount;
  readonly subDescription = this.sub.subDescription;
  readonly subPaymentDate = this.sub.subPaymentDate;
  readonly subCorrespondent = this.sub.subCorrespondent;

  /** On mobile, the tree sits behind a collapsible toggle. On desktop it stays visible. */
  readonly treeOpen = signal(false);
  readonly DESC_LIMIT = 90;
  readonly expandedDesc = signal<ReadonlySet<string>>(new Set());
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  constructor() {
    // Apply the URL filters first, then load data exactly once. The URL keeps the view
    // shareable, survives a browser reload, and is the target of cross-links from
    // Budget. The state module sends no request on its own. If the unfiltered
    // reload resolves last, it can overwrite the filtered one. See #expenses-ux2.
    this.applyQueryParams();
    this.list.reload();

    effect(() => {
      const queryParams = {
        id: this.expenseId() || null,
        budget: this.budgetId() || null,
        kind: this.kind() || null,
        q: this.q().trim() || null,
      };
      void this.router.navigate([], {
        relativeTo: this.route,
        queryParams,
        queryParamsHandling: 'merge',
        replaceUrl: true,
      });
    });

    // Remove selected ids for rows that no longer exist after a refresh, reload,
    // or delete.
    effect(() => {
      const ids = new Set(this.items().map((e) => e.id));
      this.selected.update((cur) =>
        [...cur].every((x) => ids.has(x)) ? cur : new Set([...cur].filter((x) => ids.has(x))),
      );
    });

    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
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

  /** Read the id, budget, kind, and q filters from the URL. Return true if the
   *  URL carried at least one of them. `id` is a deep link to one exact booking.
   *  It has no dedicated control, but it counts as an active filter and resets
   *  with the others. */
  private applyQueryParams(): boolean {
    const qp = this.route.snapshot.queryParamMap;
    const id = qp.get('id');
    const budget = qp.get('budget');
    const kind = qp.get('kind');
    const q = qp.get('q');
    if (id) this.expenseId.set(id);
    if (budget) this.budgetId.set(budget);
    if (kind === 'expense' || kind === 'income') this.kind.set(kind);
    if (q) this.q.set(q);
    return !!(id || budget || kind || q);
  }

  ngOnDestroy(): void {
    this.list.dispose();
  }

  money(amount: string): string {
    return formatEur(Number(amount), this.i18n.locale());
  }

  isDescLong(desc: string): boolean {
    return desc.length > this.DESC_LIMIT;
  }

  descExpanded(id: string): boolean {
    return this.expandedDesc().has(id);
  }

  toggleDesc(id: string): void {
    this.expandedDesc.update((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  sortInd(field: ExpenseSortField): string {
    return sortIndicator(this.sortField() === field, this.sortOrder());
  }

  ariaSort(field: ExpenseSortField): 'ascending' | 'descending' | 'none' {
    return ariaSortDir(this.sortField() === field, this.sortOrder());
  }

  setKind(k: '' | ExpenseKind): void {
    this.list.setKind(k);
  }

  selectBudget(id: string): void {
    this.list.selectBudget(id);
  }

  onSearch(value: string): void {
    this.list.onSearch(value);
  }

  onAmountFilter(which: 'min' | 'max', value: string): void {
    this.list.onAmountFilter(which, value);
  }

  onDateFilter(which: 'from' | 'to', value: string): void {
    this.list.onDateFilter(which, value);
  }

  resetFilters(): void {
    this.list.resetFilters();
  }

  onSort(field: ExpenseSortField): void {
    this.list.onSort(field);
  }

  loadMore(): void {
    this.list.loadMore();
  }

  onExport(): void {
    this.list.onExport();
  }

  isSubExpanded(id: string): boolean {
    return this.sub.isSubExpanded(id);
  }

  subOf(id: string): Expense[] {
    return this.sub.subOf(id);
  }

  isLoadingSub(id: string): boolean {
    return this.sub.isLoadingSub(id);
  }

  toggleSub(e: Expense): void {
    this.sub.toggleSub(e);
  }

  openCreateSub(parent: Expense): void {
    this.sub.openCreateSub(parent);
  }

  closeCreateSub(): void {
    this.sub.closeCreateSub();
  }

  canSubmitSub(): boolean {
    return this.sub.canSubmitSub();
  }

  createSub(event?: Event): void {
    this.sub.createSub(event);
  }

  openCreate(): void {
    this.dialogs.openCreate();
  }

  create(event: Event): void {
    this.dialogs.create(event);
  }

  setNewKindIncome(): void {
    this.dialogs.setNewKindIncome();
  }

  onAppSearch(value: string): void {
    this.dialogs.onAppSearch(value);
  }

  pickApp(a: { id: string; title: string }): void {
    this.dialogs.pickApp(a);
  }

  clearApp(): void {
    this.dialogs.clearApp();
  }

  onPickBudget(id: string): void {
    this.dialogs.onPickBudget(id);
  }

  onPickInvoice(id: string): void {
    this.dialogs.onPickInvoice(id);
  }

  onPickEditInvoice(id: string): void {
    this.dialogs.onPickEditInvoice(id);
  }

  openInvoiceDialog(e: Expense): void {
    this.dialogs.openInvoiceDialog(e);
  }

  openInvoiceFile(inv: Invoice): void {
    this.dialogs.openInvoiceFile(inv);
  }

  openEdit(e: Expense): void {
    this.dialogs.openEdit(e);
  }

  saveEdit(event: Event): void {
    this.dialogs.saveEdit(event);
  }

  askDelete(e: Expense): void {
    this.dialogs.askDelete(e);
  }

  doDelete(): void {
    this.dialogs.doDelete();
  }

  openTransfer(): void {
    this.dialogs.openTransfer();
  }

  onTransferFrom(id: string): void {
    this.dialogs.onTransferFrom(id);
  }

  createTransfer(event: Event): void {
    this.dialogs.createTransfer(event);
  }

  /** Switch the view; the transfers reload on every visit, because a leg can vanish. */
  setTab(tab: ExpensesTab): void {
    this.tab.set(tab);
    if (tab === 'transfers') this.transfers.reload();
  }

  loadMoreTransfers(): void {
    this.transfers.loadMore();
  }

  openTransferEdit(t: BudgetTransfer): void {
    this.transfers.openEdit(t);
  }

  closeTransferEdit(): void {
    this.transfers.closeEdit();
  }

  saveTransferEdit(event: Event): void {
    this.transfers.saveEdit(event);
  }

  askDeleteTransfer(t: BudgetTransfer): void {
    this.transfers.askDelete(t);
  }

  closeDeleteTransfer(): void {
    this.transfers.closeDelete();
  }

  doDeleteTransfer(): void {
    this.transfers.doDelete();
  }

  /** Deep-link target for the cost-center cell. It opens the Budget tab drilled into
   *  this cost center. See #expenses-ux. */
  ksLink(e: Expense): { budget: string | null; ks: string; fy: string } {
    const top = findTopBudgetNode(this.budgetTree(), e.budgetId);
    return { budget: top?.id ?? null, ks: e.budgetId, fy: e.fiscalYearId };
  }

  isSelected(id: Uuid): boolean {
    return this.selected().has(id);
  }
  toggleSelect(id: Uuid, checked: boolean): void {
    this.selected.update((cur) => {
      const next = new Set(cur);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }
  toggleSelectAll(checked: boolean): void {
    this.selected.set(checked ? new Set(this.items().map((e) => e.id)) : new Set());
  }

  askBulk(kind: 'delete' | 'export'): void {
    if (!this.selectedCount()) return;
    if (kind === 'delete' && this.bulkDeleteBlocked()) return;
    this.bulkConfirm.set(kind);
  }
  runBulk(): void {
    if (this.bulkBusy()) return;
    if (this.bulkConfirm() === 'delete') this.runBulkDelete();
    else if (this.bulkConfirm() === 'export') this.runBulkExport();
  }

  private runBulkDelete(): void {
    const ids = [...this.selected()];
    if (!ids.length) return;
    this.bulkBusy.set(true);
    let done = 0;
    from(ids)
      .pipe(concatMap((id) => this.api.deleteExpense(id)))
      .subscribe({
        next: () => {
          done++;
        },
        error: () => this.afterBulk('delete', done, true),
        complete: () => this.afterBulk('delete', done, false),
      });
  }

  /** Export only the selected bookings. The server filters the export by `ids`. */
  private runBulkExport(): void {
    const ids = [...this.selected()];
    if (!ids.length) return;
    this.bulkBusy.set(true);
    this.api.exportExpensesXlsx({ ids }).subscribe({
      next: (blob) => {
        downloadBlob(blob, 'buchungen-auswahl.xlsx');
        this.bulkBusy.set(false);
        this.bulkConfirm.set(null);
      },
      error: (err) => {
        this.bulkBusy.set(false);
        this.bulkConfirm.set(null);
        this.toast.error(problemDetail(err) ?? this.i18n.translate('expenses.toast.failed'));
      },
    });
  }

  openBulkReassign(): void {
    if (!this.selectedCount()) return;
    this.bulkBudgetId.set('');
    this.bulkCategory.set('');
    this.bulkReassignOpen.set(true);
  }
  runBulkReassign(): void {
    const ids = [...this.selected()];
    if (!ids.length || this.bulkBusy() || !this.canSubmitReassign()) return;
    const byId = new Map(this.items().map((e) => [e.id, e]));
    const budgetId = this.bulkBudgetId();
    const category = this.bulkCategory().trim();
    this.bulkBusy.set(true);
    let done = 0;
    from(ids)
      .pipe(
        concatMap((id) => {
          const e = byId.get(id);
          const patch: ExpenseUpdate = {};
          if (category) patch.category = category;
          // Set the cost center only for a standalone booking. A bound booking and a
          // sub-booking inherit it.
          if (budgetId && e && !e.applicationId && !e.parentExpenseId) {
            patch.budgetId = budgetId as Uuid;
          }
          return this.api.updateExpense(id, patch);
        }),
      )
      .subscribe({
        next: () => {
          done++;
        },
        error: () => this.afterBulk('reassign', done, true),
        complete: () => this.afterBulk('reassign', done, false),
      });
  }

  private afterBulk(kind: 'delete' | 'reassign', count: number, failed: boolean): void {
    this.bulkBusy.set(false);
    this.bulkConfirm.set(null);
    this.bulkReassignOpen.set(false);
    this.list.refresh(); // Get server truth, e.g. transfer legs. Prune effect fixes the selection.
    if (failed) {
      const key = kind === 'delete' ? 'expenses.bulk.deleteError' : 'expenses.bulk.reassignError';
      this.toast.error(this.i18n.translate(key));
    } else {
      const key = kind === 'delete' ? 'expenses.bulk.deleteDone' : 'expenses.bulk.reassignDone';
      this.toast.success(this.i18n.translate(key, { count: String(count) }));
    }
  }
}
