import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, type ParamMap, Router } from '@angular/router';
import { type Observable, from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { problemDetail } from '@core/api/problem';
import { ApiClient } from '@core/api/api-client.service';
import type { Application, Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CheckboxComponent,
  ConfirmDialogComponent,
  downloadBlob,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  InfiniteScrollDirective,
  ListDetailLayoutComponent,
  ListItemComponent,
  LongPressDirective,
  MEDIA,
  mediaQuery,
  RangeChipComponent,
  type RangeValue,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  type RowSwipeAction,
  ScrollFadeDirective,
  SearchPillComponent,
  SegmentedComponent,
  type SegmentedOption,
  SelectionBarComponent,
  SideSheetComponent,
  SkeletonComponent,
  StatusTextComponent,
  StickyBarComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  FabComponent,
  PageHeaderComponent,
} from '@shared/ui';
import { PageFrameService } from '../../layout/page-frame.service';
import { CostCentreSelectComponent } from '../budget/cost-centre-select/cost-centre-select.component';
import {
  BudgetTreeApi,
  type BudgetTransfer,
  type Expense,
  type ExpenseKind,
  type ExpenseUpdate,
  type Invoice,
} from '../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreIndex,
  costCentreLabel,
  findTopBudgetNode,
  signedEur,
} from '../budget/expense-display.util';
import { BookingDetailComponent } from './booking-detail/booking-detail.component';
import { BookingFormComponent } from './booking-form/booking-form.component';
import { BulkPanelComponent } from './bulk-panel/bulk-panel.component';
import { ExpenseDialogsState } from './expense-dialogs.state';
import { ExpenseSubBookingsState } from './expense-sub-bookings.state';
import { ExpenseTransfersState } from './expense-transfers.state';
import { ExpensesListState, type ExpenseSortField } from './expenses-list.state';
import { SubBookingDialogComponent } from './sub-booking-dialog/sub-booking-dialog.component';
import { TransferDetailComponent } from './transfer-detail/transfer-detail.component';
import { TransferFormComponent } from './transfer-form/transfer-form.component';
import { DetailNoneComponent } from '@shared/ui/detail-none/detail-none.component';
import { CostCentreLabelComponent } from '../budget/cost-centre-label/cost-centre-label.component';
import { dayMonth } from '@shared/date-format';
import { swipeFrom } from '@shared/row-swipe';
import { groupByMonth } from '@shared/group-by-month';
import { formatMoney } from '@shared/format-money';
import { TodosApiService } from '@core/api/todos.service';
import { prefetchDetails } from '@core/cache/detail-prefetch';
import { PullRefreshDirective } from '@shared/ui/pull-refresh/pull-refresh.directive';

/** The two views of the page. Bookings are the default. */
export type ExpensesTab = 'bookings' | 'transfers';

/** The form that replaces the detail: a booking or a transfer, new or under edit. */
export type ExpenseFormMode = 'create' | 'edit' | 'transfer-create' | 'transfer-edit';

/** The sort orders of the header menu, as `field:order`. */
const SORTS: readonly { field: ExpenseSortField; order: 'asc' | 'desc'; key: string }[] = [
  { field: 'paymentDate', order: 'desc', key: 'expenses.sort.paymentDesc' },
  { field: 'paymentDate', order: 'asc', key: 'expenses.sort.paymentAsc' },
  { field: 'invoiceDate', order: 'desc', key: 'expenses.sort.invoiceDesc' },
  { field: 'createdAt', order: 'desc', key: 'expenses.sort.createdDesc' },
  { field: 'amount', order: 'desc', key: 'expenses.sort.amountDesc' },
  { field: 'amount', order: 'asc', key: 'expenses.sort.amountAsc' },
];

/**
 * Bookings: a list of bookings
 * or transfers beside a detail sheet, like the applications page.
 *
 * The list: title with export, sort and a menu; the search and the chips (cost centre as
 * the tree sheet of the applications page, kind, period, amount); "Buchungen |
 * Überträge" and "n von m"; the rows by month. The detail: the open booking or transfer
 * (`?id=` and `?transfer=` in the URL, so the global search lands on a booking), the
 * form of a new or an edited booking or transfer, or, while rows are selected, the
 * panel of the bulk actions.
 *
 * A booking is standalone or bound to an application. A standalone booking needs a cost
 * centre and a fiscal year; a bound booking takes both from the application. This class
 * is a facade over the state modules; its public surface drives the specs.
 *
 * Side by side it is a pane page (`styles.scss`): the panes fill the free height and scroll
 * by themselves.
 */
@Component({
  selector: 'app-expenses',
  host: { '[class.pane-page]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PullRefreshDirective,
    InfiniteScrollDirective,
    CostCentreLabelComponent,
    DetailNoneComponent,
    ConfirmDialogComponent,
    PageHeaderComponent,
    BookingDetailComponent,
    BookingFormComponent,
    BulkPanelComponent,
    ButtonComponent,
    CheckboxComponent,
    CostCentreSelectComponent,
    EmptyStateComponent,
    FabComponent,
    FilterSelectComponent,
    FormsModule,
    IconComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    LongPressDirective,
    NgTemplateOutlet,
    RangeChipComponent,
    RowMenuComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    SegmentedComponent,
    SelectionBarComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    StickyBarComponent,
    SubBookingDialogComponent,
    TransferDetailComponent,
    TransferFormComponent,
    TranslatePipe,
  ],
  templateUrl: './expenses.component.html',
  styleUrl: './expenses.component.scss',
})
export class ExpensesComponent implements OnDestroy {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  /** The state modules share this root toast instance, so specs spy on it here. */
  private readonly toast = inject(ToastService);
  private readonly api = inject(BudgetTreeApi);
  private readonly apps = inject(ApiClient);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly frame = inject(PageFrameService);

  /**
   * The list state. The template hands the state modules to the forms, which read and set
   * their signals directly; the methods of this class are the facade the specs drive.
   */
  protected readonly list = new ExpensesListState();
  protected readonly sub = new ExpenseSubBookingsState(this.list);
  protected readonly transfers = new ExpenseTransfersState(this.list);
  protected readonly dialogs = new ExpenseDialogsState(this.list, this.sub, this.transfers);

  /** < 768px: one primary action in the title row, the rest in a menu; forms as a sheet. */
  readonly phone = mediaQuery(MEDIA.phone);
  /** The list-detail layout, for its split state. */
  private readonly layout = viewChild(ListDetailLayoutComponent);
  /** The list and the detail sit side by side. */
  readonly split = computed(() => this.layout()?.collapsed() === false);

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
  readonly sortField = this.list.sortField;
  readonly sortOrder = this.list.sortOrder;
  readonly activeFilterCount = this.list.activeFilterCount;
  readonly exporting = this.list.exporting;
  readonly refreshing = this.list.refreshing;
  readonly reloading = this.list.reloading;

  /** The display label of every cost centre: name, path and swatch colour. */
  readonly costCentres = computed(() => costCentreIndex(this.budgetTree()));

  /** The booking open in the detail (`?id=`). */
  readonly selectedId = signal('');
  /** The transfer open in the detail (`?transfer=`). */
  readonly selectedTransferId = signal('');
  /** The open booking when it is not among the loaded rows (a deep link, or a row that
   *  a refresh dropped from the filtered list). */
  private readonly fetchedExpense = signal<Expense | null>(null);
  /** The open booking as the list showed it last. When a refresh drops the row, the
   *  detail keeps this copy until the booking loads by its id. */
  private seenRow: Expense | null = null;
  /** The open booking was asked for and does not exist (or is out of reach). */
  readonly selectedMissing = signal(false);

  readonly selectedExpense = computed<Expense | null>(() => {
    const id = this.selectedId();
    if (!id) return null;
    const row = this.items().find((e) => e.id === id);
    if (row) return row;
    const fetched = this.fetchedExpense();
    return fetched?.id === id ? fetched : null;
  });

  readonly selectedTransfer = computed<BudgetTransfer | null>(() => {
    const id = this.selectedTransferId();
    if (!id) return null;
    return this.transferItems().find((t) => t.transferId === id) ?? null;
  });

  /** The invoice of the open booking, from the cache or loaded once. */
  readonly linkedInvoice = signal<Invoice | null>(null);
  /** The application of the open booking, when the reader may read it. */
  readonly linkedApplication = signal<Application | null>(null);
  /** The fiscal-year labels ("2026", "2025/26") by id, loaded per top cost centre. */
  readonly fyLabels = signal<ReadonlyMap<string, string>>(new Map());
  /** The ids of the closed fiscal years among the loaded ones. Their bookings are frozen. */
  readonly closedFys = signal<ReadonlySet<string>>(new Set());
  private readonly fyRequested = new Set<string>();

  /** The rows show check boxes. */
  readonly selecting = signal(false);
  readonly selected = signal<ReadonlySet<Uuid>>(new Set());
  readonly bulkBusy = signal(false);
  readonly selectedCount = computed(() => this.selected().size);
  readonly allSelected = computed(() => {
    const list = this.items();
    return list.length > 0 && list.every((e) => this.selected().has(e.id));
  });
  readonly selectedRows = computed(() => this.items().filter((e) => this.selected().has(e.id)));
  /** The bulk delete confirmation is open. */
  readonly bulkConfirm = signal<null | 'delete'>(null);
  /** Most rows one bulk delete may take. Selecting more stays allowed; deleting them does not. */
  readonly bulkDeleteMax = 5;
  readonly bulkDeleteOverMax = computed(() => this.selectedCount() > this.bulkDeleteMax);
  /** Select-all must not enable mass deletion: the user picks each row for the
   *  destructive bulk action. */
  readonly bulkDeleteBlocked = computed(
    () => this.bulkDeleteOverMax() || (this.allSelected() && this.selectedCount() > 1),
  );
  /** "Umbuchen" in a sheet: the layouts without the bulk panel. */
  readonly bulkReassignOpen = signal(false);
  readonly bulkBudgetId = signal('');
  readonly bulkCategory = signal('');
  readonly canSubmitReassign = computed(
    () => !!this.bulkBudgetId() || !!this.bulkCategory().trim(),
  );

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

  /** Phone: filters and pickers open from the bottom; wider: from the start edge. */
  readonly sheetSide = computed(() => (this.phone() ? 'bottom' : 'start'));

  readonly kindOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('expenses.filter.all') },
    { value: 'expense', label: this.i18n.translate('expenses.kind.expense') },
    { value: 'income', label: this.i18n.translate('expenses.kind.income') },
  ]);

  readonly kindChipLabel = computed(() => {
    const k = this.kind();
    return k
      ? this.i18n.translate(k === 'income' ? 'expenses.kind.income' : 'expenses.kind.expense')
      : this.i18n.translate('expenses.filter.kind');
  });

  readonly tabOptions = computed<SegmentedOption[]>(() => [
    { value: 'bookings', label: this.i18n.translate('expenses.tab.bookings') },
    { value: 'transfers', label: this.i18n.translate('expenses.tab.transfers') },
  ]);

  readonly sortSections = computed<RowMenuSection[]>(() => {
    const current = `${this.sortField()}:${this.sortOrder()}`;
    return [
      {
        label: this.i18n.translate('expenses.sort.title'),
        items: SORTS.map((s) => ({
          id: `${s.field}:${s.order}`,
          label: this.i18n.translate(s.key as Parameters<I18nService['translate']>[0]),
          checked: `${s.field}:${s.order}` === current,
        })),
      },
    ];
  });

  /** The page actions in the ⋮ menu of the header. On a phone the sort and the export
   *  join them. */
  readonly headerMenu = computed<RowMenuSection[]>(() => {
    const items: RowMenuItem[] = [];
    if (this.canManage()) {
      items.push({ id: 'transfer', label: this.i18n.translate('expenses.transferNew'), icon: 'repeat' });
      if (this.tab() === 'bookings') {
        items.push({ id: 'select', label: this.i18n.translate('expenses.bulk.start'), icon: 'check' });
      }
    }
    const sections: RowMenuSection[] = items.length ? [{ items }] : [];
    if (this.phone()) {
      if (this.tab() === 'bookings') sections.push(...this.sortSections());
      if (this.canExport()) {
        sections.push({
          items: [{ id: 'export', label: this.i18n.translate('expenses.export'), icon: 'download' }],
        });
      }
    }
    return sections;
  });

  onHeaderMenu(item: RowMenuItem): void {
    if (item.id === 'transfer') this.openTransfer();
    else if (item.id === 'select') this.startSelecting();
    else if (item.id === 'export') this.onExport();
    else if (item.id.includes(':')) {
      const [field, order] = item.id.split(':') as [ExpenseSortField, 'asc' | 'desc'];
      this.list.sortField.set(field);
      this.list.sortOrder.set(order);
      this.list.reload();
    }
  }

  readonly createOpen = this.dialogs.createOpen;
  readonly editing = this.dialogs.editing;
  readonly confirmDelete = this.dialogs.confirmDelete;
  readonly invoices = this.dialogs.invoices;
  readonly transferOpen = this.dialogs.transferOpen;
  readonly tFromId = this.dialogs.tFromId;
  readonly tToId = this.dialogs.tToId;
  readonly tFiscalYearId = this.dialogs.tFiscalYearId;
  readonly tAmount = this.dialogs.tAmount;
  readonly tDescription = this.dialogs.tDescription;
  readonly canSubmitTransfer = this.dialogs.canSubmitTransfer;
  readonly canSubmitCreate = this.dialogs.canSubmitCreate;

  /** The open form, or null. */
  readonly formMode = computed<ExpenseFormMode | null>(() => {
    if (this.createOpen()) return 'create';
    if (this.editing()) return 'edit';
    if (this.transferOpen()) return 'transfer-create';
    if (this.transfers.editing()) return 'transfer-edit';
    return null;
  });

  /** The heading of the form sheet of a phone. */
  readonly formTitle = computed(() => {
    switch (this.formMode()) {
      case 'create':
        return this.i18n.translate('expenses.add');
      case 'edit':
        return this.i18n.translate('expenses.edit');
      case 'transfer-create':
        return this.i18n.translate('expenses.transferNew');
      case 'transfer-edit':
        return this.i18n.translate('expenses.transfers.editTitle');
      default:
        return '';
    }
  });

  /**
   * The open tab. The transfers tab shows only when `canManage()` is true, because the
   * route also admits `budget.view`, but the server lists, edits and deletes transfers only
   * for `budget.book` (the create permission).
   */
  readonly tab = signal<ExpensesTab>('bookings');
  readonly transferItems = this.transfers.items;
  readonly transferTotal = this.transfers.total;
  readonly transferLoading = this.transfers.loading;
  readonly transferReloading = this.transfers.reloading;
  readonly transferLoadingMore = this.transfers.loadingMore;
  readonly transferHasMore = this.transfers.hasMore;
  readonly transferSaving = this.transfers.saving;
  readonly editingTransfer = this.transfers.editing;
  readonly confirmDeleteTransfer = this.transfers.confirmDelete;

  readonly subParent = this.sub.subParent;

  /** What the detail pane shows. */
  readonly detailView = computed<'form' | 'bulk' | 'transfer' | 'booking' | 'missing' | 'none'>(
    () => {
      if (this.formMode() && !this.phone()) return 'form';
      if (this.selecting() && this.selectedCount() > 0 && this.split()) return 'bulk';
      if (this.tab() === 'transfers') return this.selectedTransfer() ? 'transfer' : 'none';
      if (this.selectedExpense()) return 'booking';
      if (this.selectedId() && this.selectedMissing()) return 'missing';
      return 'none';
    },
  );

  /** One pane at a time the detail shows while a row or a form is open. */
  readonly detailOpen = computed(() => {
    if (this.formMode() && !this.phone()) return true;
    if (this.tab() === 'transfers') return !!this.selectedTransferId();
    return !!this.selectedId();
  });

  /** The list groups by month while it sorts by a date. */
  readonly groups = computed(() => {
    const field = this.sortField();
    const shown = this.items();
    const date = (e: Expense): string | null =>
      field === 'invoiceDate'
        ? e.invoiceDate
        : field === 'createdAt'
          ? e.createdAt
          : (e.paymentDate ?? e.createdAt);
    if (field === 'amount') {
      return shown.length ? [{ key: 'all', label: '', items: shown }] : [];
    }
    return groupByMonth(shown, date, this.i18n.formatLocale(), { utc: true });
  });

  readonly transferGroups = computed(() =>
    groupByMonth(this.transferItems(), (t) => t.paymentDate ?? t.createdAt, this.i18n.formatLocale(), {
      utc: true,
    }),
  );

  /**
   * The URL is applied first, then data loads exactly once, because a second, unfiltered request
   * could resolve last and overwrite the filtered list. The query param map is subscribed, because
   * the palette can send a hit here while the component is active. The filter write-back replaces
   * the create-link navigation instead of merging, because a merge would carry `new=booking` on and
   * open the form of a new booking again after its save. The rows are tracked too, because a
   * refresh can move the open booking out of the filter; it then loads by its id.
   */
  constructor() {
    prefetchDetails({
      items: this.items,
      key: (e) => e.id,
      reads: (e) => {
        const reads: Observable<unknown>[] = [inject(TodosApiService).linked('expense', e.id)];
        const invoiceId = e.invoiceId;
        if (invoiceId && !this.invoices().some((i) => i.id === invoiceId)) {
          reads.push(this.api.getInvoice(invoiceId, { detail: true }));
        }
        if (e.applicationId) reads.push(this.apps.getApplication(e.applicationId, { quiet: true, detail: true }));
        if ((e.childCount ?? 0) > 0) reads.push(this.api.listSubBookings(e.id, { detail: true }));
        return reads;
      },
      when: () => this.tab() === 'bookings',
    });
    this.applyQueryParams(this.route.snapshot.queryParamMap);
    this.list.reload();

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((qp) => {
      if (this.applyQueryParams(qp)) this.list.reload();
      this.adoptCreateLink(qp);
    });

    effect(() => {
      const queryParams = {
        budget: this.budgetId() || null,
        kind: this.kind() || null,
        q: this.q().trim() || null,
        view: this.tab() === 'transfers' ? 'transfers' : null,
        new: null,
        invoice: null,
      };
      untracked(() =>
        void this.router.navigate([], {
          relativeTo: this.route,
          queryParams,
          queryParamsHandling: 'merge',
          replaceUrl: true,
        }),
      );
    });

    this.dialogs.onCreated = (created) => this.openBooking(created.id);
    this.dialogs.onSaved = (saved) => {
      if (saved.id === this.selectedId() && !this.items().some((e) => e.id === saved.id)) {
        this.fetchedExpense.set(saved);
      }
    };
    this.dialogs.onDeleted = (gone) => {
      const edited = this.dialogs.editing();
      if (edited && (edited.id === gone.id || edited.parentExpenseId === gone.id)) {
        this.dialogs.closeForms();
      }
      if (!gone.parentExpenseId && gone.id === this.selectedId()) this.closeDetail();
    };
    this.transfers.onDeleted = (gone) => {
      this.transfers.closeEdit();
      if (gone.transferId === this.selectedTransferId()) this.closeDetail();
    };

    effect(() => {
      const ids = new Set(this.items().map((e) => e.id));
      this.selected.update((cur) =>
        [...cur].every((x) => ids.has(x)) ? cur : new Set([...cur].filter((x) => ids.has(x))),
      );
    });

    effect(() => {
      const id = this.selectedId();
      const loading = this.loading();
      const rows = this.items();
      untracked(() => this.ensureSelected(id, loading, rows));
    });
    effect(() => {
      const e = this.selectedExpense();
      untracked(() => this.loadLinked(e));
    });
    effect(() => {
      const id = this.selectedTransfer()?.fromBudgetId ?? this.selectedExpense()?.budgetId;
      const tree = this.budgetTree();
      untracked(() => {
        if (id) this.loadFyLabels(id, tree);
      });
    });
    effect(() => {
      const tree = this.budgetTree();
      untracked(() => {
        if (this.canManage()) for (const top of tree) this.loadFyLabels(top.id, tree);
      });
    });

    effect(() => this.frame.fill.set(this.split()));

  }

  /**
   * Read the filters, the view and the open row from the URL. Return true if a filter of
   * the list changed (the caller then reloads it).
   *
   * Absence clears: each of these is written back into the URL, so a parameter that is gone was
   * taken away, not merely omitted. A click on another row while a form is open replaces the form,
   * so the highlighted row and the detail always agree.
   */
  private applyQueryParams(qp: ParamMap): boolean {
    const raw = qp.get('kind');
    const kind: '' | ExpenseKind = raw === 'expense' || raw === 'income' ? raw : '';
    const budgetId = qp.get('budget') ?? '';
    const q = qp.get('q') ?? '';
    let changed = false;
    if (budgetId !== this.budgetId()) {
      this.budgetId.set(budgetId);
      changed = true;
    }
    if (kind !== this.kind()) {
      this.kind.set(kind);
      changed = true;
    }
    if (q !== this.q()) {
      this.q.set(q);
      changed = true;
    }
    const view: ExpensesTab =
      qp.get('view') === 'transfers' && this.canManage() ? 'transfers' : 'bookings';
    if (view !== this.tab()) {
      this.tab.set(view);
      if (view === 'transfers') this.transfers.reload();
    } else if (changed && view === 'transfers') {
      this.transfers.reload();
    }
    const id = qp.get('id') ?? '';
    if (id !== this.selectedId()) {
      if (id) this.dialogs.closeForms();
      this.selectedId.set(id);
      this.selectedMissing.set(false);
    }
    const transferId = qp.get('transfer') ?? '';
    if (transferId && transferId !== this.selectedTransferId()) this.dialogs.closeForms();
    this.selectedTransferId.set(transferId);
    return changed;
  }

  /**
   * `?new=booking&invoice=<id>` ("Buchung anlegen" on the invoices page) opens the form
   * of a new booking with that invoice. The page then takes the two parameters away, so
   * a reload does not open the form again.
   */
  private adoptCreateLink(qp: ParamMap): void {
    if (qp.get('new') !== 'booking') return;
    if (this.canManage()) {
      const invoiceId = qp.get('invoice');
      this.dialogs.openCreate(invoiceId ? { invoiceId } : {});
    }
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { new: null, invoice: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /**
   * Load the open booking when it is not among the loaded rows: a deep link, or a row
   * that a refresh dropped (an edit or a bulk "Umbuchen" moved it out of the filter).
   * A dropped row stays in the detail as the list showed it until the server answers.
   */
  private ensureSelected(id: string, loading: boolean, rows: readonly Expense[]): void {
    if (!id || loading) return;
    const row = rows.find((e) => e.id === id);
    if (row) {
      this.seenRow = row;
      return;
    }
    const dropped = this.seenRow?.id === id ? this.seenRow : null;
    this.seenRow = null;
    if (dropped) this.fetchedExpense.set(dropped);
    else if (this.fetchedExpense()?.id === id) return;
    this.api.listExpenses({ id: id as Uuid, limit: 1 }).subscribe({
      next: (page) => {
        if (this.selectedId() !== id) return;
        const hit = page.items[0] ?? null;
        this.fetchedExpense.set(hit);
        this.selectedMissing.set(!hit);
      },
      error: () => {
        if (this.selectedId() === id) this.selectedMissing.set(true);
      },
    });
  }

  /**
   * The linked records of the open booking. Each request runs once per booking.
   *
   * A budget reader may lack the right to read the application; the card then shows only the title
   * the booking carries.
   */
  private loadLinked(e: Expense | null): void {
    const invoiceId = e?.invoiceId ?? null;
    if (this.linkedInvoice()?.id !== invoiceId) this.linkedInvoice.set(null);
    if (invoiceId) {
      const cached = this.invoices().find((i) => i.id === invoiceId);
      if (cached) this.linkedInvoice.set(cached);
      else
        this.api.getInvoice(invoiceId, { detail: true }).subscribe({
          next: (inv) => {
            if (this.selectedExpense()?.invoiceId === inv.id) this.linkedInvoice.set(inv);
          },
          error: () => this.linkedInvoice.set(null),
        });
    }
    const appId = e?.applicationId ?? null;
    if (this.linkedApplication()?.id !== appId) this.linkedApplication.set(null);
    if (appId && this.linkedApplication()?.id !== appId) {
      this.apps.getApplication(appId, { quiet: true, detail: true }).subscribe({
        next: (app) => {
          if (this.selectedExpense()?.applicationId === app.id) this.linkedApplication.set(app);
        },
        error: () => this.linkedApplication.set(null),
      });
    }
    if (e && (e.childCount ?? 0) > 0 && !this.sub.subRows().has(e.id) && !this.sub.isLoadingSub(e.id)) {
      this.sub.loadSub(e.id, true);
    }
  }

  /** Load the fiscal years of the top cost centre of `budgetId` once, for their labels. */
  private loadFyLabels(budgetId: string, tree = this.budgetTree()): void {
    const top = findTopBudgetNode(tree, budgetId);
    if (!top || this.fyRequested.has(top.id)) return;
    this.fyRequested.add(top.id);
    this.api.listFiscalYears(top.id).subscribe({
      next: (fys) => {
        this.fyLabels.update((m) => {
          const next = new Map(m);
          for (const f of fys) next.set(f.id, f.display);
          return next;
        });
        this.closedFys.update((c) => {
          const next = new Set(c);
          for (const f of fys) {
            if (f.closedAt) next.add(f.id);
            else next.delete(f.id);
          }
          return next;
        });
      },
      error: () => this.fyRequested.delete(top.id),
    });
  }

  ngOnDestroy(): void {
    this.list.dispose();
    this.frame.fill.set(false);
  }

  money(amount: string): string {
    return formatMoney(amount, this.i18n.formatLocale());
  }

  signed(e: Expense): string {
    return signedEur(e.kind, e.amount, this.i18n.formatLocale());
  }

  /** Only the date part counts, because a `createdAt` keeps the day the server wrote. */
  day(iso: string | null): string {
    return dayMonth(iso?.slice(0, 10), this.i18n.formatLocale());
  }

  costCentre(id: string, pathKey: string | null): CostCentreLabel {
    return costCentreLabel(this.costCentres(), id, pathKey);
  }

  /** The label of a fiscal year ("2026"); a closed year says so. */
  fyLabel(id: string): string | null {
    const year = this.fyLabels().get(id);
    if (!year) return null;
    return this.closedFys().has(id) ? this.i18n.translate('budget.fy.closedLabel', { year }) : year;
  }

  /** Whether the reader may change a booking of this fiscal year: `budget.book`, and
   *  the year is not closed. */
  canChange(fyId: string): boolean {
    return this.canManage() && !this.closedFys().has(fyId);
  }

  /** Open a booking in the detail. The URL keeps it, so the back button closes it. */
  openBooking(id: string): void {
    this.dialogs.closeForms();
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { id, transfer: null },
      queryParamsHandling: 'merge',
    });
  }

  openTransferRow(id: string): void {
    this.dialogs.closeForms();
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { transfer: id, id: null },
      queryParamsHandling: 'merge',
    });
  }

  /** "Zur Liste": close the form, else the open row. The filters stay. */
  closeDetail(): void {
    if (this.formMode()) {
      this.dialogs.closeForms();
      return;
    }
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { id: null, transfer: null },
      queryParamsHandling: 'merge',
    });
  }

  setKind(k: string): void {
    this.list.setKind(k === 'expense' || k === 'income' ? k : '');
  }

  selectBudget(id: string): void {
    this.list.selectBudget(id);
    if (this.tab() === 'transfers') this.transfers.reload();
  }

  onSearch(value: string): void {
    this.list.onSearch(value);
    if (this.tab() === 'transfers') this.transfers.reload();
  }

  onAmountRange(v: RangeValue): void {
    this.list.setAmountRange(v.from, v.to);
    if (this.tab() === 'transfers') this.transfers.reload();
  }

  onDateRange(v: RangeValue): void {
    this.list.setDateRange(v.from, v.to);
    if (this.tab() === 'transfers') this.transfers.reload();
  }

  resetFilters(): void {
    this.list.resetFilters();
    if (this.tab() === 'transfers') this.transfers.reload();
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

  /** Switch the view. The transfers load on every visit, because a booking change can
   *  remove a leg. */
  setTab(tab: ExpensesTab): void {
    if (tab === 'transfers' && !this.canManage()) return;
    this.tab.set(tab);
    this.stopSelecting();
    if (tab === 'transfers') this.transfers.reload();
  }

  /** The shown list loads: a pull to refresh waits for it. */
  readonly listBusy = computed(() =>
    this.tab() === 'transfers'
      ? this.transferLoading() || this.transferReloading()
      : this.loading() || this.reloading() || this.refreshing(),
  );

  /** Pull to refresh: the bookings or the transfers load again, with the filters. */
  refreshList(): void {
    if (this.tab() === 'transfers') this.transfers.reload();
    else this.list.reload();
  }

  loadMoreTransfers(): void {
    this.transfers.loadMore();
  }

  openCreate(): void {
    this.dialogs.openCreate();
  }

  create(event: Event): void {
    this.dialogs.create(event);
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

  createTransfer(event: Event): void {
    this.dialogs.createTransfer(event);
  }

  openTransferEdit(t: BudgetTransfer): void {
    this.dialogs.closeForms();
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

  openCreateSub(parent: Expense): void {
    this.sub.openCreateSub(parent);
  }

  openInvoiceFile(inv: Invoice): void {
    this.dialogs.openInvoiceFile(inv);
  }

  /** The row menu of a booking. A booking of a closed fiscal year has no write action. */
  rowMenu(e: Expense): RowMenuSection[] {
    const main: RowMenuItem[] = [];
    const canChange = this.canChange(e.fiscalYearId);
    if (canChange) {
      main.push({ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' });
      main.push({ id: 'sub', label: this.i18n.translate('expenses.sub.add'), icon: 'plus' });
    }
    if (e.invoiceId) {
      main.push({
        id: 'invoice',
        label: this.i18n.translate('expenses.action.viewInvoice'),
        icon: 'receipt',
      });
    }
    const sections: RowMenuSection[] = main.length ? [{ items: main }] : [];
    if (canChange) {
      sections.push({
        items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'trash', danger: true }],
      });
    }
    return sections;
  }

  onRowMenu(item: RowMenuItem, e: Expense): void {
    if (item.id === 'edit') this.openEdit(e);
    else if (item.id === 'sub') this.openCreateSub(e);
    else if (item.id === 'invoice' && e.invoiceId) {
      void this.router.navigate(['/invoices'], { queryParams: { id: e.invoiceId } });
    } else if (item.id === 'delete') this.askDelete(e);
  }

  /** The swipe to the right of a phone: "Bearbeiten" of the row menu. */
  swipeRight(menu: readonly RowMenuSection[]): RowSwipeAction | null {
    return swipeFrom(menu, 'edit');
  }

  /** The swipe to the left: start the selection with this booking. */
  swipeLeft(): RowSwipeAction | null {
    if (!this.canManage() || this.tab() !== 'bookings') return null;
    return { id: 'select', label: this.i18n.translate('expenses.bulk.pick'), icon: 'check' };
  }

  /** A swipe of a phone carried out an item of the row menu. */
  onRowSwiped(action: RowSwipeAction, e: Expense): void {
    if (action.id === 'edit') this.openEdit(e);
    else if (action.id === 'select') this.selectWith(e);
  }

  /**
   * A long press or the swipe to the left: start the selection with this booking, or, in
   * the selection already, toggle it.
   */
  selectWith(e: Expense): void {
    if (!this.canManage()) return;
    if (!this.selecting()) {
      this.startSelecting();
      this.toggleSelect(e.id, true);
      return;
    }
    this.toggleSelect(e.id, !this.isSelected(e.id));
  }

  readonly transferMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' }] },
    {
      items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'trash', danger: true }],
    },
  ]);

  onTransferMenu(item: RowMenuItem, t: BudgetTransfer): void {
    if (item.id === 'edit') this.openTransferEdit(t);
    else if (item.id === 'delete') this.askDeleteTransfer(t);
  }

  rowMenuLabel(e: Expense): string {
    return this.i18n.translate('expenses.rowMenu', { description: e.description });
  }

  startSelecting(): void {
    if (!this.canManage()) return;
    this.selecting.set(true);
  }

  stopSelecting(): void {
    this.selecting.set(false);
    this.selected.set(new Set());
    this.bulkReassignOpen.set(false);
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

  askBulkDelete(): void {
    if (!this.selectedCount() || this.bulkDeleteBlocked()) return;
    this.bulkConfirm.set('delete');
  }

  /** The disabled button is an affordance, not a control, so the cap is checked here too. */
  runBulkDelete(): void {
    const ids = [...this.selected()];
    if (!ids.length || this.bulkBusy() || this.bulkDeleteBlocked()) return;
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
  runBulkExport(): void {
    const ids = [...this.selected()];
    if (!ids.length || this.bulkBusy()) return;
    this.bulkBusy.set(true);
    this.api.exportExpensesXlsx({ ids }).subscribe({
      next: (blob) => {
        downloadBlob(blob, 'buchungen-auswahl.xlsx');
        this.bulkBusy.set(false);
      },
      error: (err) => {
        this.bulkBusy.set(false);
        this.toast.error(problemDetail(err) || this.i18n.translate('expenses.toast.failed'));
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
    this.bulkBudgetId.set('');
    this.bulkCategory.set('');
    this.list.refresh();
    if (failed) {
      const key = kind === 'delete' ? 'expenses.bulk.deleteError' : 'expenses.bulk.reassignError';
      this.toast.error(this.i18n.translate(key));
    } else {
      const key = kind === 'delete' ? 'expenses.bulk.deleteDone' : 'expenses.bulk.reassignDone';
      this.toast.success(this.i18n.translate(key, { count: String(count) }));
    }
  }

  /** A row in selection mode: a click toggles it. */
  onRowActivate(e: Expense): void {
    if (this.selecting()) this.toggleSelect(e.id, !this.isSelected(e.id));
  }
}
