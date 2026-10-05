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
import { NgTemplateOutlet } from '@angular/common';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, type ParamMap, Router } from '@angular/router';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  InputComponent,
  MEDIA,
  SegmentedComponent,
  type SegmentedOption,
  SelectComponent,
  type SortState,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  NoteComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SearchPillComponent,
  SelectionBarComponent,
  SideSheetComponent,
  StatusTextComponent,
  invoiceStatus,
} from '@shared/ui';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
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
  BOOKINGS_COLUMNS_FULL_MEDIA,
  COLUMNS_TIGHT_MEDIA,
  columnSet,
  costCentreIndex,
  findTopBudgetNode,
  formatEur,
  problemDetail,
  sortIndicator,
} from '../budget/expense-display.util';
import { downloadBlob } from '@shared/download.util';
import { mediaQuerySignal } from '../../layout/media-query';
import { BookingDialogComponent } from './booking-dialog/booking-dialog.component';
import { ExpenseDialogsState } from './expense-dialogs.state';
import { ExpenseSubBookingsState } from './expense-sub-bookings.state';
import { ExpenseTransfersState } from './expense-transfers.state';
import { type BudgetLink, ExpensesTableComponent } from './expenses-table/expenses-table.component';
import { ExpensesListState, type ExpenseSortField } from './expenses-list.state';
import { SubBookingDialogComponent } from './sub-booking-dialog/sub-booking-dialog.component';
import { TransferDialogComponent } from './transfer-dialog/transfer-dialog.component';
import { TransfersTableComponent } from './transfers-table/transfers-table.component';

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
    BookingDialogComponent,
    ButtonComponent,
    CostCentreTreeComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    ExpensesTableComponent,
    FilterBarComponent,
    FilterFieldComponent,
    FilterRangeComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    LocalizedDatePipe,
    NgTemplateOutlet,
    NoteComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    SegmentedComponent,
    SelectComponent,
    SelectionBarComponent,
    SideSheetComponent,
    StatusTextComponent,
    SubBookingDialogComponent,
    TransferDialogComponent,
    TransfersTableComponent,
    TranslatePipe,
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

  // The state modules. The template hands them to the table and the dialogs, which read
  // and set their signals directly; the methods below are the facade the specs drive.
  protected readonly list = new ExpensesListState();
  protected readonly sub = new ExpenseSubBookingsState(this.list);
  protected readonly transfers = new ExpenseTransfersState(this.list);
  protected readonly dialogs = new ExpenseDialogsState(this.list, this.sub, this.transfers);

  /** >= 1200px: the cost-centre pane beside the table, and the page does not scroll. */
  readonly wide = mediaQuerySignal(MEDIA.wide);
  /** < 768px: one primary action in the title row, the rest in a menu. */
  readonly phone = mediaQuerySignal(MEDIA.phone);
  private readonly fullColumns = mediaQuerySignal(BOOKINGS_COLUMNS_FULL_MEDIA);
  private readonly tightColumns = mediaQuerySignal(COLUMNS_TIGHT_MEDIA);
  /** Which table columns fit the viewport. */
  readonly columnSet = computed(() =>
    columnSet({ phone: this.phone(), full: this.fullColumns(), tight: this.tightColumns() }),
  );

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

  // Batch and bulk actions. See.
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
   *  destructive bulk action. See. */
  /** Most rows one bulk delete may take. Selecting more stays allowed; deleting them does not. */
  readonly bulkDeleteMax = 5;
  readonly bulkDeleteOverMax = computed(() => this.selectedCount() > this.bulkDeleteMax);
  readonly bulkDeleteBlocked = computed(
    () => this.bulkDeleteOverMax() || (this.allSelected() && this.selectedCount() > 1),
  );
  readonly bulkReassignOpen = signal(false);
  readonly bulkBudgetId = signal('');
  readonly bulkCategory = signal('');
  /** The display label of every cost centre: name, path and swatch colour (O19). */
  readonly costCentres = computed(() => costCentreIndex(this.budgetTree()));

  /** The cost centre the list shows, for the chip of the narrower layouts. */
  readonly costCentreName = computed(() => {
    const id = this.budgetId();
    return (id && this.costCentres().get(id)?.name) || this.i18n.translate('expenses.filter.allCostCentres');
  });

  /** The colour swatch of the chosen cost centre, null for "all". */
  readonly costCentreColor = computed(() => {
    const id = this.budgetId();
    return (id && this.costCentres().get(id)?.color) || null;
  });

  /** Below the wide layout the cost-centre tree opens in the side sheet: from the start
   *  (narrow) or from the bottom (phone). */
  readonly pickerOpen = signal(false);

  readonly tabOptions = computed<SegmentedOption[]>(() => [
    { value: 'bookings', label: this.i18n.translate('expenses.tab.bookings') },
    { value: 'transfers', label: this.i18n.translate('expenses.tab.transfers') },
  ]);

  /** The table speaks `SortState`; the list state speaks a field plus an order. */
  readonly sortState = computed<SortState>(() => ({
    key: this.sortField(),
    direction: this.sortOrder() === 'asc' ? 'asc' : 'desc',
  }));

  /** The page actions that do not fit the title row of a phone. */
  readonly phoneMenu = computed<RowMenuSection[]>(() => {
    const items: RowMenuItem[] = [];
    if (this.canManage()) {
      items.push({ id: 'transfer', label: this.i18n.translate('expenses.transfer'), icon: 'repeat' });
    }
    if (this.canExport()) {
      items.push({ id: 'export', label: this.i18n.translate('expenses.export'), icon: 'download' });
    }
    return [{ items }];
  });

  onPhoneMenu(item: RowMenuItem): void {
    if (item.id === 'transfer') this.openTransfer();
    else if (item.id === 'export') this.onExport();
  }

  /** "7 ausgewählt", plus the delete cap once the selection is past it. */
  readonly selectionLabel = computed(() => {
    const count = this.i18n.translate('expenses.bulk.selectedCount', {
      count: String(this.selectedCount()),
    });
    if (!this.bulkDeleteOverMax()) return count;
    const cap = this.i18n.translate('expenses.bulk.deleteMax', { max: String(this.bulkDeleteMax) });
    return `${count} · ${cap}`;
  });

  /** Why the bulk delete is off, or null while it is on. */
  readonly bulkDeleteReason = computed(() => {
    if (this.bulkDeleteOverMax()) {
      return this.i18n.translate('expenses.bulk.deleteMaxBlocked', { max: String(this.bulkDeleteMax) });
    }
    if (this.bulkDeleteBlocked()) return this.i18n.translate('expenses.bulk.deleteAllBlocked');
    return null;
  });

  /** The Budget query of a cost-centre cell. */
  readonly budgetLink = (e: Expense): BudgetLink => this.ksLink(e);

  /** The status of the invoice in the detail dialog. */
  readonly invoiceStatus = invoiceStatus;

  onSortChange(next: SortState): void {
    this.onSort(next.key as ExpenseSortField);
  }

  onSelectionChange(next: Set<unknown>): void {
    this.selected.set(next as ReadonlySet<Uuid>);
  }

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

  // Transfers tab. The route also admits `budget.view`, but the server lists, edits
  // and deletes transfers only for `budget.book` (the create permission). So the tab
  // shows only when `canManage()` is true.
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

  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');
  /** The scroll box of the list. It scrolls on the wide layout only. */
  readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');

  constructor() {
    // Apply the URL filters first, then load data exactly once. The URL keeps the view
    // shareable, survives a browser reload, and is the target of cross-links from
    // Budget. The state module sends no request on its own. If the unfiltered
    // reload resolves last, it can overwrite the filtered one. See.
    this.applyQueryParams(this.route.snapshot.queryParamMap);
    this.list.reload();

    // The palette can send us here while we are already here: a hit on another booking
    // changes only the query string, and the router keeps this component alive. A
    // snapshot read alone would never run again, and the write-back effect below would
    // put the old filters straight back into the URL.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((qp) => {
      if (this.applyQueryParams(qp)) this.list.reload();
    });

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

    // Infinite scroll. The wide layout scrolls the list inside its own box, so the box is
    // the root there; the narrower layouts scroll the page.
    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const root = this.wide() ? (this.scroller()?.nativeElement ?? null) : null;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMore();
        },
        { root, rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  /** Read the id, budget, kind, and q filters from the URL. Return true if the
   *  URL carried at least one of them. `id` is a deep link to one exact booking.
   *  It has no dedicated control, but it counts as an active filter and resets
   *  with the others. */
  private applyQueryParams(qp: ParamMap): boolean {
    const raw = qp.get('kind');
    const kind: '' | ExpenseKind = raw === 'expense' || raw === 'income' ? raw : '';
    const next = {
      expenseId: qp.get('id') ?? '',
      budgetId: qp.get('budget') ?? '',
      q: qp.get('q') ?? '',
    };
    let changed = false;
    // Absence clears. Every one of these four is written back into the URL by the effect
    // in the constructor, so a parameter that is gone was taken away, not merely omitted.
    if (next.expenseId !== this.expenseId()) {
      this.expenseId.set(next.expenseId);
      changed = true;
    }
    if (next.budgetId !== this.budgetId()) {
      this.budgetId.set(next.budgetId);
      changed = true;
    }
    if (kind !== this.kind()) {
      this.kind.set(kind);
      changed = true;
    }
    if (next.q !== this.q()) {
      this.q.set(next.q);
      changed = true;
    }
    return changed;
  }

  ngOnDestroy(): void {
    this.list.dispose();
  }

  money(amount: string): string {
    return formatEur(Number(amount), this.i18n.locale());
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
    this.pickerOpen.set(false);
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

  /** Switch the view. The transfers load lazily on the first visit and then
   *  again on every visit, because a booking change can remove a leg. */
  setTab(tab: ExpensesTab): void {
    if (tab === 'transfers' && !this.canManage()) return;
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
   *  this cost center. See. */
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
    // The disabled button is an affordance, not a control: check the cap here too.
    if (!ids.length || this.bulkDeleteBlocked()) return;
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
