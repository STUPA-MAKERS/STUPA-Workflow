import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  model,
  output,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  IconComponent,
  InputComponent,
  SheetBarComponent,
  SheetBarTitleDirective,
} from '@stupa-makers/ui-kit';
import { CostCentreSelectComponent } from '../../budget/cost-centre-select/cost-centre-select.component';
import type { BudgetTreeNode, Expense } from '../../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreLabel,
  signedEur,
} from '../../budget/expense-display.util';
import { BookingRowComponent } from '../../budget/booking-row/booking-row.component';
import { SumRowComponent } from '../../budget/booking-row/sum-row.component';
import { dayMonth } from '@shared/date-format';
import { formatMoney } from '@shared/format-money';

/**
 * The bulk actions of the selected bookings. Side by side
 * the panel replaces the detail sheet: "n Buchungen ausgewählt", "Umbuchen" (cost centre
 * and category, "unverändert lassen" when empty), the selected rows with their sum, the
 * export and the delete (at most five).
 *
 * `variant="reassign"` shows only "Umbuchen", for the sheet of the narrower layouts.
 */
@Component({
  selector: 'app-bulk-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SumRowComponent,
    BookingRowComponent,
    SheetBarComponent,
    SheetBarTitleDirective,
    ButtonComponent,
    CostCentreSelectComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    NgTemplateOutlet,
    TranslatePipe,
  ],
  templateUrl: './bulk-panel.component.html',
  styleUrl: './bulk-panel.component.scss',
})
export class BulkPanelComponent {
  private readonly i18n = inject(I18nService);

  readonly variant = input<'panel' | 'reassign'>('panel');
  readonly rows = input<readonly Expense[]>([]);
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  readonly tree = input<BudgetTreeNode[]>([]);
  readonly canExport = input(false);
  readonly busy = input(false);
  /** Why the delete is off, or null. */
  readonly deleteReason = input<string | null>(null);
  readonly deleteMax = input(5);
  /** The cost centre of "Umbuchen"; empty keeps it. */
  readonly budgetId = model('');
  /** The category of "Umbuchen"; empty keeps it. */
  readonly category = model('');

  readonly reassign = output<void>();
  readonly exported = output<void>();
  readonly remove = output<void>();
  readonly closed = output<void>();


  /** The sum of the selection, signed. */
  protected readonly sum = computed(() => {
    const total = this.rows().reduce(
      (acc, e) => acc + (e.kind === 'income' ? 1 : -1) * Number(e.amount),
      0,
    );
    return formatMoney(total, this.i18n.formatLocale(), { signed: true });
  });

  /** The cost centre all selected rows share, else null. */
  protected readonly commonCostCentre = computed(() => {
    const rows = this.rows();
    if (!rows.length) return null;
    const first = rows[0].budgetId;
    if (!rows.every((r) => r.budgetId === first)) return null;
    return costCentreLabel(this.costCentres(), first, rows[0].pathKey).name;
  });

  /** The rows bound to an application (or sub-bookings): they keep their cost centre. */
  protected readonly fixedRows = computed(() =>
    this.rows().filter((r) => !!r.applicationId || !!r.parentExpenseId),
  );

  protected readonly canReassign = computed(
    () => !!this.budgetId() || !!this.category().trim(),
  );

  protected pick(id: string): void {
    this.budgetId.set(id);
  }

  costCentre(e: Expense): CostCentreLabel {
    return costCentreLabel(this.costCentres(), e.budgetId, e.pathKey);
  }

  signed(e: Expense): string {
    return signedEur(e.kind, e.amount, this.i18n.formatLocale());
  }

  /** Only the date part counts, because a `createdAt` keeps the day the server wrote. */
  day(iso: string | null): string {
    return dayMonth(iso?.slice(0, 10), this.i18n.formatLocale());
  }

  /** "„A“ und „B“": the bound rows, by name, for the hint. */
  protected readonly fixedNames = computed(() =>
    this.fixedRows()
      .map((r) => `„${r.description}“`)
      .join(', '),
  );
}
