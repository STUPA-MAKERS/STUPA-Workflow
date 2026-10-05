import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
} from '@stupa-makers/ui-kit';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { CostCentreTreeComponent } from '../../budget/cost-centre-tree.component';
import type { BudgetTreeNode } from '../../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreFigures,
  costCentreLabel,
  findBudgetNode,
  formatEur,
} from '../../budget/expense-display.util';
import type { FinanceFormLayout } from '../booking-form/booking-form.component';
import type { ExpenseDialogsState } from '../expense-dialogs.state';
import type { ExpenseTransfersState } from '../expense-transfers.state';

/** A new transfer, or a correction of the one in `transfers.editing`. */
export type TransferFormMode = 'create' | 'edit';

/** One leg of the preview: the cost centre, its path, the amount and what is left. */
interface Leg {
  cc: CostCentreLabel;
  /** "verfügbar danach": the available amount after the transfer, null when unknown. */
  after: string | null;
}

/**
 * The transfer form (board Fin-Uebertrag-Neu): move an amount from one cost centre to
 * another in one fiscal year ("Übertrag"), or correct a transfer. It replaces the detail
 * sheet.
 *
 * New: from, to (each the tree of the applications page), fiscal year, amount and
 * description; beside them "So wird gebucht" with the two bookings and the available
 * amount after the transfer. The dates and the note follow in the edit.
 *
 * Edit: the two cost centres of a transfer are fixed on the server, so the form shows
 * them read-only and changes the amount, the text, the dates and the note.
 */
@Component({
  selector: 'app-transfer-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CostCentreTreeComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    ScrollFadeDirective,
    SelectComponent,
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

  /** The open tree: the source or the target field. */
  protected readonly picking = signal<'from' | 'to' | null>(null);

  protected label(id: string): CostCentreLabel | null {
    return id ? costCentreLabel(this.costCentres(), id, null) : null;
  }

  /** The fixed pair of the transfer under correction. */
  protected readonly pair = computed(() => {
    const t = this.transfers().editing();
    if (!t) return null;
    return {
      from: costCentreLabel(this.costCentres(), t.fromBudgetId, t.fromPathKey),
      to: costCentreLabel(this.costCentres(), t.toBudgetId, t.toPathKey),
    };
  });

  /** "So wird gebucht": both legs, once the pair is chosen. */
  protected readonly preview = computed<{ from: Leg; to: Leg; amount: string } | null>(() => {
    const d = this.dialogs();
    const fromId = d.tFromId();
    const toId = d.tToId();
    if (!fromId || !toId || fromId === toId) return null;
    const amount = Number(d.tAmount()) || 0;
    const fy = d.tFiscalYearId();
    const leg = (id: string, sign: 1 | -1): Leg => {
      const f = fy ? costCentreFigures(findBudgetNode(this.tree(), id), fy) : null;
      return {
        cc: costCentreLabel(this.costCentres(), id, null),
        after: f ? this.money(f.available + sign * amount) : null,
      };
    };
    return { from: leg(fromId, -1), to: leg(toId, 1), amount: this.money(amount) };
  });

  protected pick(which: 'from' | 'to', id: string): void {
    if (!id) return;
    if (which === 'from') this.dialogs().onTransferFrom(id);
    else this.dialogs().tToId.set(id);
    this.picking.set(null);
  }

  protected toggle(which: 'from' | 'to'): void {
    this.picking.set(this.picking() === which ? null : which);
  }

  money(value: number): string {
    return formatEur(value, this.i18n.locale());
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
