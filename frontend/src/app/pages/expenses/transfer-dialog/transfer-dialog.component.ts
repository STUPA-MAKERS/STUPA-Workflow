import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { NoteComponent } from '@shared/ui';
import { type CostCentreLabel, costCentreLabel } from '../../budget/expense-display.util';
import type { ExpenseDialogsState } from '../expense-dialogs.state';
import type { ExpenseTransfersState } from '../expense-transfers.state';

/** A new transfer, or a correction of the one in `transfers.editing`. */
export type TransferDialogMode = 'create' | 'edit';

/**
 * The transfer dialog: move an amount from one cost centre to another in one fiscal year
 * ("Übertrag"), or correct a transfer.
 *
 * The two cost centres of a transfer are fixed on the server. The correction shows them
 * read-only and changes the amount, the text, the dates and the note.
 */
@Component({
  selector: 'app-transfer-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    NoteComponent,
    SelectComponent,
    TranslatePipe,
  ],
  templateUrl: './transfer-dialog.component.html',
  styleUrl: './transfer-dialog.component.scss',
})
export class TransferDialogComponent {
  readonly dialogs = input.required<ExpenseDialogsState>();
  readonly transfers = input.required<ExpenseTransfersState>();
  readonly mode = input<TransferDialogMode>('create');
  readonly costCentreOptions = input<SelectOption[]>([]);
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  readonly saving = input(false);

  protected readonly open = computed(() =>
    this.mode() === 'create' ? this.dialogs().transferOpen() : this.transfers().editing() !== null,
  );

  /** The fixed pair of the transfer under correction, as "from → to". */
  protected readonly pair = computed(() => {
    const t = this.transfers().editing();
    if (!t) return null;
    const from = costCentreLabel(this.costCentres(), t.fromBudgetId, t.fromPathKey);
    const to = costCentreLabel(this.costCentres(), t.toBudgetId, t.toPathKey);
    return { from, to };
  });

  protected close(): void {
    if (this.mode() === 'create') this.dialogs().transferOpen.set(false);
    else this.transfers().closeEdit();
  }

  protected submit(event: Event): void {
    if (this.mode() === 'create') this.dialogs().createTransfer(event);
    else this.transfers().saveEdit(event);
  }
}
