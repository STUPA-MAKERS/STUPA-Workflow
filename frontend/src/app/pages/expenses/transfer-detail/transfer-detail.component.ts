import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui';
import type { BudgetTransfer } from '../../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreLabel,
  formatEur,
} from '../../budget/expense-display.util';

/**
 * The detail of a transfer (board Fin-Uebertraege): "Übertrag · HHJ 2025", the
 * description, "von → nach · Betrag", the two bookings of the transfer (an expense on the
 * source and an income on the target), who booked it, the data, and the note that the
 * pair of cost centres is fixed.
 */
@Component({
  selector: 'app-transfer-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent, LocalizedDatePipe, RowMenuComponent, TranslatePipe],
  templateUrl: './transfer-detail.component.html',
  styleUrl: './transfer-detail.component.scss',
})
export class TransferDetailComponent {
  private readonly i18n = inject(I18nService);

  readonly transfer = input.required<BudgetTransfer>();
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  readonly fyLabel = input<string | null>(null);
  readonly canManage = input(false);
  readonly split = input(false);
  readonly phone = input(false);

  readonly edit = output<void>();
  readonly remove = output<void>();

  protected readonly from = computed(() => {
    const t = this.transfer();
    return costCentreLabel(this.costCentres(), t.fromBudgetId, t.fromPathKey);
  });
  protected readonly to = computed(() => {
    const t = this.transfer();
    return costCentreLabel(this.costCentres(), t.toBudgetId, t.toPathKey);
  });

  protected readonly metaLine = computed(() => {
    const kind = this.i18n.translate('expenses.transfers.kind');
    const fy = this.fyLabel();
    return fy ? `${kind} · ${this.i18n.translate('expenses.detail.fy', { fy })}` : kind;
  });

  protected readonly amount = computed(() => formatEur(Number(this.transfer().amount), this.i18n.locale()));

  protected readonly createdAt = computed(() =>
    new Date(this.transfer().createdAt).toLocaleString(this.i18n.formatLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }),
  );

  protected readonly menu = computed<RowMenuSection[]>(() => {
    if (!this.canManage()) return [];
    return [
      {
        items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }],
      },
    ];
  });

  onMenu(item: RowMenuItem): void {
    if (item.id === 'delete') this.remove.emit();
  }
}
