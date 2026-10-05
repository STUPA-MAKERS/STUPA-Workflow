import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CellDirective, type ColumnDef, DataTableComponent } from '@stupa-makers/ui-kit';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui';
import type { BudgetTransfer } from '../../budget/budget-tree.api';
import {
  type ColumnSet,
  type CostCentreLabel,
  costCentreLabel,
  formatEur,
} from '../../budget/expense-display.util';

/**
 * The transfers view of the bookings page: one row per transfer.
 *
 * A transfer is two bookings, and the bookings table shows it as its two legs. Only this
 * view shows it as ONE row with an identity, which is what an edit and a delete need. The
 * two cost centres of a transfer are fixed on the server, so the edit changes the amount,
 * the text and the dates only.
 */
@Component({
  selector: 'app-transfers-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CellDirective, DataTableComponent, LocalizedDatePipe, RowMenuComponent, TranslatePipe],
  templateUrl: './transfers-table.component.html',
  styleUrl: './transfers-table.component.scss',
})
export class TransfersTableComponent {
  private readonly i18n = inject(I18nService);

  readonly rows = input.required<readonly BudgetTransfer[]>();
  readonly loading = input(false);
  /** Which columns fit the viewport. */
  readonly columnSet = input<ColumnSet>('full');
  /** `budget.book`: the row actions. */
  readonly canManage = input(false);
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());

  readonly edit = output<BudgetTransfer>();
  readonly remove = output<BudgetTransfer>();

  readonly columns = computed<ColumnDef[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const cols: ColumnDef[] = [
      { key: 'paymentDate', label: t('expenses.col.paymentDate'), width: '6.5rem' },
    ];
    if (this.columnSet() === 'full') {
      cols.push({ key: 'invoiceDate', label: t('expenses.col.invoiceDate'), width: '7rem', card: 'hidden' });
    }
    cols.push(
      { key: 'description', label: t('expenses.col.description'), card: 'title' },
      { key: 'from', label: t('expenses.transfers.from'), width: '8.5rem' },
      { key: 'to', label: t('expenses.transfers.to'), width: '8.5rem' },
      { key: 'amount', label: t('expenses.col.amount'), align: 'end', width: '6.5rem' },
    );
    if (this.canManage()) {
      cols.push({ key: 'actions', label: t('table.actions'), align: 'end', width: '4rem', sticky: 'end', card: 'actions' });
    }
    return cols;
  });

  readonly rowId = (row: unknown): unknown => (row as BudgetTransfer).transferId;

  readonly menu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' }] },
    { items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }] },
  ]);

  onMenu(item: RowMenuItem, t: BudgetTransfer): void {
    if (item.id === 'edit') this.edit.emit(t);
    else if (item.id === 'delete') this.remove.emit(t);
  }

  money(amount: string): string {
    return formatEur(Number(amount), this.i18n.locale());
  }

  costCentre(id: string, pathKey: string | null): CostCentreLabel {
    return costCentreLabel(this.costCentres(), id, pathKey);
  }

  rowMenuLabel(t: BudgetTransfer): string {
    return this.i18n.translate('expenses.rowMenu', { description: t.description });
  }
}
