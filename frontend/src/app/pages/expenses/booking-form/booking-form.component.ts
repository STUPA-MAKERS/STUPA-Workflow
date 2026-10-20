import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  AutocompleteComponent,
  ButtonComponent,
  ChipGroupComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  IconComponent,
  InputComponent,
  LockedFieldComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SegmentedComponent,
  type SegmentedOption,
  SelectFieldComponent,
  TextareaComponent,
  ScrollFadeDirective,
} from '@stupa-makers/ui-kit';
import { formatMoney } from '@shared/format-money';
import { PaneFormHeadComponent } from '@shared/ui/pane-form/pane-form-head.component';
import { PaneFormFootComponent } from '@shared/ui/pane-form/pane-form-foot.component';
import { BookingRowComponent } from '../../budget/booking-row/booking-row.component';
import { SumRowComponent } from '../../budget/booking-row/sum-row.component';
import { CostCentreSelectComponent } from '../../budget/cost-centre-select/cost-centre-select.component';
import type {
  BudgetTreeNode,
  Expense,
  ExpenseKind,
  PaymentMethod,
} from '../../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreLabel,
  costCentreTrail,
  signedEur,
} from '../../budget/expense-display.util';
import type { ExpenseDialogsState } from '../expense-dialogs.state';

/** Which booking the form writes: a new one, or the one in `state.editing`. */
export type BookingFormMode = 'create' | 'edit';

/**
 * Where the form shows: in the detail pane beside the list (`pane`), on the page one
 * pane at a time (`page`), or in the bottom sheet of a phone (`sheet`, which brings its own
 * head).
 */
export type FinanceFormLayout = 'pane' | 'page' | 'sheet';

/** The payment methods as chips, "Keine Angabe" first (board Fin-Buchung-Neu). */
const PAYMENT_METHODS: readonly ('' | PaymentMethod)[] = [
  '',
  'ueberweisung',
  'bar',
  'lastschrift',
  'karte',
  'paypal',
];

/**
 * The booking form (boards "Buchung hinzufügen", "Buchung · Kostenstelle wählen",
 * "Buchung · Handy"): add a booking or edit one. It replaces the detail sheet.
 *
 * Two equal columns. Start: the kind (Ausgabe | Einnahme), the amount, the description,
 * then "Zuordnung" with the cost centre (`app-cost-centre-select`: search, grouped by
 * top-level budget, the free amount of each), the fiscal year and the category, and the
 * application search (`app-autocomplete`). End: "Beleg" with the invoice, the payee, the
 * reference number and the two dates; "Zahlung" with the payment method
 * (`app-chip-group`) and the note (`app-textarea`).
 *
 * A picked invoice fills the payee, the invoice date and the reference number; while it
 * stays picked those fields are `app-locked-field filled` (the selection surface with a
 * lock). A linked application gives the cost centre and the fiscal year, so both show
 * filled and locked.
 *
 * Edit: the fiscal year, the application, and the cost centre of a bound booking or a
 * sub-booking are fixed (`app-locked-field`); a standalone booking can move to another cost
 * centre. A parent booking shows its amount as the sum of its sub-bookings, and the
 * sub-bookings with their actions.
 *
 * The state module holds the values and sends the requests; this component is the form.
 */
@Component({
  selector: 'app-booking-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ScrollFadeDirective,
    BookingRowComponent,
    SumRowComponent,
    PaneFormHeadComponent,
    PaneFormFootComponent,
    AutocompleteComponent,
    ButtonComponent,
    ChipGroupComponent,
    CostCentreSelectComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    LocalizedDatePipe,
    LockedFieldComponent,
    RowMenuComponent,
    SegmentedComponent,
    SelectFieldComponent,
    TextareaComponent,
    TranslatePipe,
  ],
  templateUrl: './booking-form.component.html',
  styleUrl: './booking-form.component.scss',
})
export class BookingFormComponent {
  private readonly i18n = inject(I18nService);

  readonly state = input.required<ExpenseDialogsState>();
  readonly mode = input<BookingFormMode>('create');
  readonly tree = input<BudgetTreeNode[]>([]);
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  readonly saving = input(false);
  readonly layout = input<FinanceFormLayout>('pane');
  /** The label of the fiscal year of the edited booking. */
  readonly fyLabel = input<string | null>(null);
  /** The sub-bookings of the edited booking. */
  readonly subRows = input<readonly Expense[]>([]);

  readonly remove = output<void>();
  readonly addSub = output<void>();
  readonly editSub = output<Expense>();
  readonly removeSub = output<Expense>();

  protected readonly kindOptions = computed<SegmentedOption[]>(() => [
    { value: 'expense', label: this.i18n.translate('expenses.kind.expense') },
    { value: 'income', label: this.i18n.translate('expenses.kind.income') },
  ]);

  protected readonly methods = computed(() =>
    PAYMENT_METHODS.map((value) => ({
      value,
      label: this.i18n.translate(
        value ? `expenses.paymentMethod.${value}` : 'expenses.field.paymentMethodPlaceholder',
      ),
    })),
  );

  /** The text of an application hit. */
  protected readonly appTitle = (a: { title: string }): string => a.title;

  /** The application search lists its hits below the field while there are hits. */
  protected readonly suggestOpen = computed(() => this.state().appCandidates().length > 0);

  protected readonly editingRow = computed(() => this.state().editing());

  /** A parent booking: its amount is the sum of its sub-bookings and read-only. */
  protected readonly parentAmount = computed(() => {
    const e = this.editingRow();
    return e && (e.childCount ?? 0) > 0 ? formatMoney(e.amount, this.i18n.formatLocale()) : null;
  });

  /** Only a standalone booking moves to another cost centre. A bound booking and a
   *  sub-booking take theirs from the application or the parent. */
  protected readonly editOwnsCostCentre = computed(() => {
    const e = this.editingRow();
    return !!e && !e.applicationId && !e.parentExpenseId;
  });

  /** The cost centre the form writes: the new booking, or the edited one. */
  protected readonly ccId = computed(() =>
    this.mode() === 'create' ? this.state().newBudgetId() : this.state().editBudgetId(),
  );

  /** The fiscal year the cost-centre list counts the free amounts in. */
  protected readonly ccYear = computed(() =>
    this.mode() === 'create'
      ? this.state().newFiscalYearId()
      : (this.editingRow()?.fiscalYearId ?? ''),
  );

  /** "Fachschaften › Maschinenbau": the cost centre of a fixed value. */
  protected readonly ccTrail = computed(() => {
    const e = this.editingRow();
    if (!e) return '';
    return (
      costCentreTrail(this.tree(), e.budgetId) ??
      costCentreLabel(this.costCentres(), e.budgetId, e.pathKey).name
    );
  });

  /**
   * The fields the picked invoice filled: locked while the invoice stays picked. Only a
   * new booking takes them; an edit keeps its own values.
   */
  protected readonly locks = computed(() => {
    const inv = this.mode() === 'create' ? this.state().newInvoice() : null;
    return {
      correspondent: !!inv?.supplier,
      referenceNumber: !!inv?.number,
      invoiceDate: !!inv?.issueDate,
    };
  });

  protected readonly subMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' }] },
    {
      items: [
        { id: 'delete', label: this.i18n.translate('action.delete'), icon: 'trash', danger: true },
      ],
    },
  ]);

  protected setKind(value: string | null): void {
    const kind = value as ExpenseKind;
    if (kind === 'income') this.state().setNewKindIncome();
    else this.state().newKind.set('expense');
  }

  protected pickCostCentre(id: string): void {
    if (!id) return;
    if (this.mode() === 'create') this.state().onPickBudget(id);
    else this.state().editBudgetId.set(id);
  }

  protected setMethod(value: string): void {
    if (this.mode() === 'create') this.state().newPaymentMethod.set(value);
    else this.state().editPaymentMethod.set(value);
  }

  protected method(): string {
    return this.mode() === 'create'
      ? this.state().newPaymentMethod()
      : this.state().editPaymentMethod();
  }

  protected onSubMenu(item: RowMenuItem, s: Expense): void {
    if (item.id === 'edit') this.editSub.emit(s);
    else if (item.id === 'delete') this.removeSub.emit(s);
  }

  protected signed(e: Expense): string {
    return signedEur(e.kind, e.amount, this.i18n.formatLocale());
  }

  close(): void {
    if (this.mode() === 'create') this.state().createOpen.set(false);
    else this.state().editing.set(null);
  }

  submit(event: Event): void {
    if (this.mode() === 'create') this.state().create(event);
    else this.state().saveEdit(event);
  }
}
