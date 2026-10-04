import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  IconComponent,
  type SortState,
} from '@stupa-makers/ui-kit';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui';
import type { Expense } from '../../budget/budget-tree.api';
import {
  type ColumnSet,
  type CostCentreLabel,
  costCentreLabel,
  formatEur,
} from '../../budget/expense-display.util';
import type { ExpenseSubBookingsState } from '../expense-sub-bookings.state';

/** The query of the Budget link of a cost-centre cell. */
export type BudgetLink = { budget: string | null; ks: string; fy: string };

/**
 * The bookings table of the bookings page (board Arbeit-Buchungen).
 *
 * Columns: payment date, invoice date, kind, description with the linked application
 * as a second line, payee/payer, the signed amount and the cost centre. A booking with
 * sub-bookings expands in place: each sub-booking is a row of the same columns, marked
 * "↳", and its cost centre reads "erbt", because it takes the cost centre of its parent.
 *
 * The table holds no state. The page owns the rows, the selection and the sort; the
 * sub-booking state module owns which parents are open and their children.
 */
@Component({
  selector: 'app-expenses-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CellDirective,
    DataTableComponent,
    IconComponent,
    LocalizedDatePipe,
    RouterLink,
    RowMenuComponent,
    TranslatePipe,
  ],
  templateUrl: './expenses-table.component.html',
  styleUrl: './expenses-table.component.scss',
})
export class ExpensesTableComponent {
  private readonly i18n = inject(I18nService);

  readonly rows = input.required<readonly Expense[]>();
  readonly loading = input(false);
  /** Which columns fit the viewport. */
  readonly columnSet = input<ColumnSet>('full');
  /** `budget.book`: selection, sub-bookings and the row actions. */
  readonly canManage = input(false);
  readonly selected = input<ReadonlySet<Uuid>>(new Set());
  readonly sort = input.required<SortState>();
  readonly sub = input.required<ExpenseSubBookingsState>();
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  /** The Budget query of a cost-centre cell. */
  readonly budgetLink = input.required<(e: Expense) => BudgetLink>();

  readonly selectedChange = output<Set<Uuid>>();
  readonly sortChange = output<SortState>();
  readonly edit = output<Expense>();
  readonly remove = output<Expense>();
  readonly addSub = output<Expense>();
  readonly viewInvoice = output<Expense>();

  readonly columns = computed<ColumnDef[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const set = this.columnSet();
    const cols: ColumnDef[] = [
      {
        key: 'paymentDate',
        label: t('expenses.col.paymentDate'),
        width: '6.5rem',
        sortable: true,
        initialSort: 'desc',
      },
    ];
    if (set === 'full') {
      cols.push(
        {
          key: 'invoiceDate',
          label: t('expenses.col.invoiceDate'),
          width: '7rem',
          sortable: true,
          initialSort: 'desc',
          // Off the card: most bookings have none.
          card: 'hidden',
        },
        // Off the card: the amount already carries the sign.
        { key: 'kind', label: t('expenses.col.kind'), width: '4.5rem', card: 'hidden' },
      );
    }
    // The heading of a card: it says WHICH booking this is.
    cols.push({ key: 'description', label: t('expenses.col.description'), card: 'title' });
    // The tight set shows the payee as a line under the description instead.
    if (set !== 'tight') {
      cols.push({ key: 'correspondent', label: t('expenses.col.correspondent'), width: '8rem' });
    }
    cols.push(
      // The amount sits before the cost centre: it is the column a reader scans for, and
      // the pinned actions column covers what is left of it when the table scrolls.
      {
        key: 'amount',
        label: t('expenses.col.amount'),
        align: 'end',
        width: '6.5rem',
        sortable: true,
        initialSort: 'desc',
      },
      { key: 'costCentre', label: t('expenses.col.costCentre'), width: '8.5rem' },
    );
    if (this.canManage()) {
      // An explicit width: a self-sized pinned column grew and covered its neighbour.
      cols.push({ key: 'actions', label: t('table.actions'), align: 'end', width: '5rem', sticky: 'end' });
    }
    return cols;
  });

  /** Track by the booking id, so paging in more rows does not re-create the earlier ones. */
  readonly rowId = (row: unknown): unknown => (row as Expense).id;

  /** Expanded sub-bookings only. A closed parent contributes no rows. */
  readonly childrenOf = (row: unknown): readonly unknown[] => {
    const e = row as Expense;
    return this.sub().isSubExpanded(e.id) ? this.sub().subOf(e.id) : [];
  };

  readonly rowSelectLabel = (row: unknown): string => (row as Expense).description;

  /** The actions of a booking. A sub-booking has no sub-bookings of its own. */
  private readonly parentMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        { id: 'sub', label: this.i18n.translate('expenses.sub.add'), icon: 'add' },
        { id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' },
      ],
    },
    { items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }] },
  ]);
  private readonly childMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' }] },
    { items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }] },
  ]);

  menuFor(child: boolean): RowMenuSection[] {
    return child ? this.childMenu() : this.parentMenu();
  }

  onMenu(item: RowMenuItem, e: Expense): void {
    if (item.id === 'sub') this.addSub.emit(e);
    else if (item.id === 'edit') this.edit.emit(e);
    else if (item.id === 'delete') this.remove.emit(e);
  }

  onSelection(next: Set<unknown>): void {
    this.selectedChange.emit(next as Set<Uuid>);
  }

  onSort(next: SortState): void {
    this.sortChange.emit(next);
  }

  /** The amount with its sign: "−" for an expense, "+" for an income. */
  signed(e: Expense): string {
    const sign = e.kind === 'income' ? '+' : '−';
    return sign + formatEur(Number(e.amount), this.i18n.locale());
  }

  costCentre(e: Expense): CostCentreLabel {
    return costCentreLabel(this.costCentres(), e.budgetId, e.pathKey);
  }

  /** "2 Unterbuchungen ein-/ausklappen": the name of the expand button. */
  toggleLabel(e: Expense): string {
    return this.i18n.translate('expenses.sub.toggleCount', { count: String(e.childCount ?? 0) });
  }

  rowMenuLabel(e: Expense): string {
    return this.i18n.translate('expenses.rowMenu', { description: e.description });
  }
}
