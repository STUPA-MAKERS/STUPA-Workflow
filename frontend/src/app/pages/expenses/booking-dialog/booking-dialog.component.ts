import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SegmentedComponent,
  type SegmentedOption,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { NoteComponent } from '@shared/ui';
import type { ExpenseKind } from '../../budget/budget-tree.api';
import { formatEur } from '../../budget/expense-display.util';
import type { ExpenseDialogsState } from '../expense-dialogs.state';

/** Which booking the dialog writes: a new one, or the one in `state.editing`. */
export type BookingDialogMode = 'create' | 'edit';

/**
 * The booking dialog (board Arbeit-Buchung-Dialog): add a booking or edit one.
 *
 * It shows every field a booking has (N30): kind, description, amount, the link to an
 * application, cost centre and fiscal year, invoice, payee/payer, the two dates, the
 * reference number, the payment method, the category and the note. A booking bound to an
 * application takes the cost centre and the fiscal year from it, so the dialog then hides
 * both. The state module holds the values and sends the request; this component is the
 * form only.
 */
@Component({
  selector: 'app-booking-dialog',
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
    SegmentedComponent,
    SelectComponent,
    TranslatePipe,
  ],
  templateUrl: './booking-dialog.component.html',
  styleUrl: './booking-dialog.component.scss',
})
export class BookingDialogComponent {
  private readonly i18n = inject(I18nService);

  readonly state = input.required<ExpenseDialogsState>();
  readonly mode = input<BookingDialogMode>('create');
  readonly costCentreOptions = input<SelectOption[]>([]);
  readonly saving = input(false);

  protected readonly open = computed(() =>
    this.mode() === 'create' ? this.state().createOpen() : !!this.state().editing(),
  );

  protected readonly kindOptions = computed<SegmentedOption[]>(() => [
    { value: 'expense', label: this.i18n.translate('expenses.kind.expense') },
    { value: 'income', label: this.i18n.translate('expenses.kind.income') },
  ]);

  /** The application search lists its hits below the field while there are hits. */
  protected readonly suggestOpen = computed(() => this.state().appCandidates().length > 0);

  /** A parent booking: its amount is the sum of its sub-bookings and read-only. */
  protected readonly parentAmount = computed(() => {
    const e = this.state().editing();
    return e && (e.childCount ?? 0) > 0 ? formatEur(Number(e.amount), this.i18n.locale()) : null;
  });

  /** Only a standalone booking moves to another cost centre. A bound booking and a
   *  sub-booking take theirs from the application or the parent. */
  protected readonly editOwnsCostCentre = computed(() => {
    const e = this.state().editing();
    return !!e && !e.applicationId && !e.parentExpenseId;
  });

  protected setKind(value: string | null): void {
    const kind = value as ExpenseKind;
    if (kind === 'income') this.state().setNewKindIncome();
    else this.state().newKind.set('expense');
  }

  protected close(): void {
    if (this.mode() === 'create') this.state().createOpen.set(false);
    else this.state().editing.set(null);
  }

  protected submit(event: Event): void {
    if (this.mode() === 'create') this.state().create(event);
    else this.state().saveEdit(event);
  }
}
