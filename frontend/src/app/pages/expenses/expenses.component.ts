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
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
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
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import type { Expense, ExpenseKind, Invoice } from '../budget/budget-tree.api';
import { ariaSortDir, formatEur, sortIndicator } from '../budget/expense-display.util';
import { SimplifyPathPipe } from '@shared/budget-path';
import { ExpenseDialogsState } from './expense-dialogs.state';
import { ExpenseSubBookingsState } from './expense-sub-bookings.state';
import { ExpensesListState, type ExpenseSortField } from './expenses-list.state';

/**
 * Bookings tab: view/create/manage actual expense/income bookings. A booking is
 * either standalone (cost centre + fiscal year picked) or bound to an
 * application (inherits both). Thin facade over the state modules below; its
 * public surface also drives the specs.
 */
@Component({
  selector: 'app-expenses',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
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
    CostCentreTreeComponent,
  ],
  templateUrl: './expenses.component.html',
  styleUrl: './expenses.component.scss',
})
export class ExpensesComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  // Referenced via the same root instance by the state modules; specs spy here.
  private readonly toast = inject(ToastService);

  private readonly list = new ExpensesListState();
  private readonly sub = new ExpenseSubBookingsState(this.list);
  private readonly dialogs = new ExpenseDialogsState(this.list, this.sub);

  readonly canManage = computed(() => this.auth.can('budget.book'));
  readonly canExport = computed(() => this.auth.can('budget.export'));

  // --- list state (ExpensesListState) ---------------------------------------
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
  readonly accountId = this.list.accountId;
  readonly sortField = this.list.sortField;
  readonly sortOrder = this.list.sortOrder;
  readonly activeFilterCount = this.list.activeFilterCount;
  readonly costCentreOptions = this.list.costCentreOptions;
  readonly accounts = this.list.accounts;
  readonly accountOptions = this.list.accountOptions;
  readonly accountFilterOptions = this.list.accountFilterOptions;
  readonly exporting = this.list.exporting;

  // --- dialog state (ExpenseDialogsState) ------------------------------------
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

  // --- sub-booking state (ExpenseSubBookingsState) ----------------------------
  readonly subParent = this.sub.subParent;
  readonly subAmount = this.sub.subAmount;
  readonly subDescription = this.sub.subDescription;
  readonly subPaymentDate = this.sub.subPaymentDate;
  readonly subCorrespondent = this.sub.subCorrespondent;

  // --- local UI state -----------------------------------------------------------
  /** Mobile only: tree behind a collapsible toggle (always visible on desktop). */
  readonly treeOpen = signal(false);
  readonly DESC_LIMIT = 90;
  readonly expandedDesc = signal<ReadonlySet<string>>(new Set());
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  constructor() {
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

  ngOnDestroy(): void {
    this.list.dispose();
  }

  // --- display helpers -------------------------------------------------------------
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

  // --- list delegates ------------------------------------------------------------
  setKind(k: '' | ExpenseKind): void {
    this.list.setKind(k);
  }

  selectAccount(id: string): void {
    this.list.selectAccount(id);
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

  // --- sub-booking delegates ---------------------------------------------------------
  isSubExpanded(id: string): boolean {
    return this.sub.isSubExpanded(id);
  }

  subOf(id: string): Expense[] {
    return this.sub.subOf(id);
  }

  isLoadingSub(id: string): boolean {
    return this.sub.isLoadingSub(id);
  }

  isSubImporting(id: string): boolean {
    return this.sub.isSubImporting(id);
  }

  toggleSub(e: Expense): void {
    this.sub.toggleSub(e);
  }

  onSubFile(e: Expense, event: Event): void {
    this.sub.onSubFile(e, event);
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

  // --- dialog delegates -----------------------------------------------------------
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
}
