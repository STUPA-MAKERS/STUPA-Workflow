import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  IconComponent,
  InputComponent,
} from '@stupa-makers/ui-kit';
import { formatMoney } from '@shared/format-money';
import { PaneFormHeadComponent } from '@shared/ui/pane-form/pane-form-head.component';
import { PaneFormFootComponent } from '@shared/ui/pane-form/pane-form-foot.component';
import { SelectFieldComponent } from '@shared/ui/select/select.component';
import { CostCentreSelectComponent } from '../../budget/cost-centre-select/cost-centre-select.component';
import type { BudgetTreeNode } from '../../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreFigures,
  costCentreLabel,
  findBudgetNode,
} from '../../budget/expense-display.util';
import type { FinanceFormLayout } from '../booking-form/booking-form.component';
import type { ExpenseDialogsState } from '../expense-dialogs.state';
import type { ExpenseTransfersState } from '../expense-transfers.state';

/** A new transfer, or a correction of the one in `transfers.editing`. */
export type TransferFormMode = 'create' | 'edit';

/** "Frei danach" of one leg: the free amount now and after the transfer. */
interface LegFree {
  /** The free amount now, shown struck through while an amount is entered. */
  before: string | null;
  after: string;
}

/**
 * The transfer form (boards "Übertrag buchen", "Übertrag · Handy"): move an amount from
 * one cost centre to another in one fiscal year ("Übertrag"), or correct a transfer. It
 * replaces the detail sheet.
 *
 * New: "Von → nach" with the two legs as cards (each opens `app-cost-centre-select`) and
 * "Frei danach" on each (the free amount now struck through, the amount after the
 * transfer), "Richtung tauschen", then the amount and the description beside the fiscal
 * year. The main action names the amount ("500,00 € übertragen"). The dates and the note
 * follow in the edit.
 *
 * Edit: the two cost centres of a transfer are fixed on the server, so the legs show
 * locked and the form changes the amount, the text, the dates and the note.
 */
@Component({
  selector: 'app-transfer-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PaneFormHeadComponent,
    PaneFormFootComponent,
    ButtonComponent,
    CostCentreSelectComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    NgTemplateOutlet,
    SelectFieldComponent,
    TranslatePipe,
  ],
  templateUrl: './transfer-form.component.html',
  styleUrl: './transfer-form.component.scss',
})
export class TransferFormComponent {
  private readonly i18n = inject(I18nService);

  readonly dialogs = input.required<ExpenseDialogsState>();
  readonly transfers = input.required<ExpenseTransfersState>();
  readonly mode = input<TransferFormMode>('create');
  readonly tree = input<BudgetTreeNode[]>([]);
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  readonly saving = input(false);
  readonly layout = input<FinanceFormLayout>('pane');
  /** The label of the fiscal year of the edited transfer. */
  readonly fyLabel = input<string | null>(null);

  readonly remove = output<void>();

  /** The fixed pair of the transfer under correction. */
  protected readonly pair = computed(() => {
    const t = this.transfers().editing();
    if (!t) return null;
    return {
      from: costCentreLabel(this.costCentres(), t.fromBudgetId, t.fromPathKey),
      to: costCentreLabel(this.costCentres(), t.toBudgetId, t.toPathKey),
    };
  });

  /** The amount of the new transfer, 0 while none is entered. */
  private readonly amount = computed(() => {
    const n = Number(this.dialogs().tAmount());
    return Number.isFinite(n) && n > 0 ? n : 0;
  });

  /** "Frei danach" of the source (minus the amount) and the target (plus the amount). */
  protected readonly free = computed<{ from: LegFree | null; to: LegFree | null }>(() => {
    const d = this.dialogs();
    return {
      from: this.legFree(d.tFromId(), -1),
      to: this.legFree(d.tToId(), 1),
    };
  });

  /** The main action: "500,00 € übertragen", or "Übertragen" without an amount. */
  protected readonly submitLabel = computed(() => {
    const amount = this.amount();
    return amount > 0
      ? this.i18n.translate('expenses.transfers.submit', { amount: this.money(amount) })
      : this.i18n.translate('expenses.transferConfirm');
  });

  private legFree(id: string, sign: 1 | -1): LegFree | null {
    const fy = this.dialogs().tFiscalYearId();
    if (!id || !fy) return null;
    const f = costCentreFigures(findBudgetNode(this.tree(), id), fy);
    if (!f) return null;
    const amount = this.amount();
    return {
      before: amount > 0 ? this.money(f.available) : null,
      after: this.money(f.available + sign * amount),
    };
  }

  protected pick(which: 'from' | 'to', id: string): void {
    if (!id) return;
    if (which === 'from') this.dialogs().onTransferFrom(id);
    else this.dialogs().tToId.set(id);
  }

  money(value: number): string {
    return formatMoney(value, this.i18n.formatLocale());
  }

  close(): void {
    if (this.mode() === 'create') this.dialogs().transferOpen.set(false);
    else this.transfers().closeEdit();
  }

  submit(event: Event): void {
    if (this.mode() === 'create') this.dialogs().createTransfer(event);
    else this.transfers().saveEdit(event);
  }
}
