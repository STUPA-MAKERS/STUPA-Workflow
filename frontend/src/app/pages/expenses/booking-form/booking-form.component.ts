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
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  IconComponent,
  InputComponent,
  SegmentedComponent,
  type SegmentedOption,
  SelectComponent,
} from '@stupa-makers/ui-kit';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { CostCentreTreeComponent } from '../../budget/cost-centre-tree.component';
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
  formatEur,
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
 * The booking form (boards Fin-Buchung-Neu, Fin-Buchung-Bearbeiten, Fin-Tel-Buchung-Neu):
 * add a booking or edit one. It replaces the detail sheet.
 *
 * New: "Was" (kind, description, amount, category), "Wohin" (the application search, the
 * cost centre as the tree of the applications page, the fiscal year), "Beleg" (the
 * invoice, which fills payee, invoice date and reference number; the payee, the
 * reference number and the two dates), the payment method as chips and the note.
 *
 * Edit: "Fest" shows the fixed values (kind, fiscal year, application, and the cost
 * centre of a bound booking or a sub-booking); a standalone booking can move to another
 * cost centre. A parent booking shows its amount as the sum of its sub-bookings, and the
 * sub-bookings with their actions.
 *
 * The state module holds the values and sends the requests; this component is the form.
 */
@Component({
  selector: 'app-booking-form',
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
    LocalizedDatePipe,
    RowMenuComponent,
    ScrollFadeDirective,
    SegmentedComponent,
    SelectComponent,
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

  /** The cost-centre tree of the field is open. */
  protected readonly treeOpen = signal(false);

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

  /** The application search lists its hits below the field while there are hits. */
  protected readonly suggestOpen = computed(() => this.state().appCandidates().length > 0);

  protected readonly editingRow = computed(() => this.state().editing());

  /** A parent booking: its amount is the sum of its sub-bookings and read-only. */
  protected readonly parentAmount = computed(() => {
    const e = this.editingRow();
    return e && (e.childCount ?? 0) > 0 ? formatEur(Number(e.amount), this.i18n.locale()) : null;
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

  protected readonly ccValue = computed(() => {
    const id = this.ccId();
    return id ? costCentreLabel(this.costCentres(), id, null) : null;
  });

  /** "Fachschaften › Maschinenbau": the cost centre of a fixed value. */
  protected readonly ccTrail = computed(() => {
    const e = this.editingRow();
    if (!e) return '';
    return (
      costCentreTrail(this.tree(), e.budgetId) ??
      costCentreLabel(this.costCentres(), e.budgetId, e.pathKey).name
    );
  });

  /** The picked invoice filled payee, invoice date and reference number. */
  protected readonly invoiceTaken = computed(() =>
    this.mode() === 'create' ? !!this.state().newInvoiceId() : false,
  );

  /** "Lastenrad Anzahlung · erfasst von Konrad Pfeiffer, 25.09.2026". */
  protected readonly subtitle = computed(() => {
    if (this.mode() === 'create') return this.i18n.translate('expenses.form.required');
    const e = this.editingRow();
    if (!e) return '';
    const date = new Date(e.createdAt).toLocaleDateString(this.i18n.formatLocale(), {
      dateStyle: 'medium',
    } as Intl.DateTimeFormatOptions);
    return e.actorName
      ? this.i18n.translate('expenses.form.editedBy', {
          description: e.description,
          name: e.actorName,
          date,
        })
      : `${e.description} · ${date}`;
  });

  protected readonly subMenu = computed<RowMenuSection[]>(() => [
    { items: [{ id: 'edit', label: this.i18n.translate('action.edit'), icon: 'edit' }] },
    {
      items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }],
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
    this.treeOpen.set(false);
  }

  protected setMethod(value: string): void {
    if (this.mode() === 'create') this.state().newPaymentMethod.set(value);
    else this.state().editPaymentMethod.set(value);
  }

  protected method(): string {
    return this.mode() === 'create' ? this.state().newPaymentMethod() : this.state().editPaymentMethod();
  }

  protected onSubMenu(item: RowMenuItem, s: Expense): void {
    if (item.id === 'edit') this.editSub.emit(s);
    else if (item.id === 'delete') this.removeSub.emit(s);
  }

  protected signed(e: Expense): string {
    return signedEur(e.kind, e.amount, this.i18n.locale());
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
