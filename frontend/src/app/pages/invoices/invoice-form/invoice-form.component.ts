import {
  ChangeDetectionStrategy,
  Component,
  type Signal,
  type WritableSignal,
  computed,
  inject,
  input,
  output,
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
  SegmentedComponent,
  type SegmentedOption,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import type { Invoice, InvoiceStatus } from '../../budget/budget-tree.api';
import type { FinanceFormLayout } from '../../expenses/booking-form/booking-form.component';

/** What the import found: `parsed` (ZUGFeRD read), `manual` (no ZUGFeRD), or nothing. */
export type InvoiceImportNotice = 'parsed' | 'manual' | null;

/**
 * A new invoice needs a number, a supplier and a positive gross amount. The server
 * accepts an invoice without number or supplier, but the create form does not: a manual
 * entry without them cannot be found again. The edit of a stored invoice uses its own
 * rule (see `canSubmitEdit` on the host).
 */
export function invoiceFieldsValid(number: string, supplier: string, gross: string): boolean {
  return number.trim() !== '' && supplier.trim() !== '' && Number(gross) > 0;
}

/**
 * What the form reads and writes on the invoices page. The page keeps the values and the
 * requests, so its specs drive one place.
 */
export interface InvoiceFormHost {
  readonly saving: Signal<boolean>;
  readonly attaching: Signal<boolean>;
  readonly statusOptions: Signal<SelectOption[]>;

  readonly createOpen: WritableSignal<boolean>;
  readonly newNumber: WritableSignal<string>;
  readonly newSupplier: WritableSignal<string>;
  readonly newIssueDate: WritableSignal<string>;
  readonly newDueDate: WritableSignal<string>;
  readonly newNet: WritableSignal<string>;
  readonly newTax: WritableSignal<string>;
  readonly newGross: WritableSignal<string>;
  readonly newStatus: WritableSignal<InvoiceStatus>;
  readonly newNote: WritableSignal<string>;
  readonly importToken: Signal<string>;
  readonly importFileName: Signal<string>;
  readonly importFileSize: Signal<number>;
  readonly importNotice: Signal<InvoiceImportNotice>;
  readonly importDuplicate: Signal<string | null>;
  readonly canSubmitCreate: Signal<boolean>;
  create(event: Event): void;
  clearAttachment(): void;
  onCreateFilePicked(event: Event): void;

  readonly editing: WritableSignal<Invoice | null>;
  readonly editNumber: WritableSignal<string>;
  readonly editSupplier: WritableSignal<string>;
  readonly editIssueDate: WritableSignal<string>;
  readonly editDueDate: WritableSignal<string>;
  readonly editNet: WritableSignal<string>;
  readonly editTax: WritableSignal<string>;
  readonly editGross: WritableSignal<string>;
  readonly editStatus: WritableSignal<InvoiceStatus>;
  readonly editNote: WritableSignal<string>;
  /** True when the stored invoice has a number, so the edit cannot clear it. */
  readonly editNumberRequired: Signal<boolean>;
  /** True when the stored invoice has a supplier, so the edit cannot clear it. */
  readonly editSupplierRequired: Signal<boolean>;
  readonly canSubmitEdit: Signal<boolean>;
  saveEdit(event: Event): void;
  openFile(i: Invoice): void;
}

/**
 * The invoice form (boards Fin-Rechnung-Import, Fin-Rechnung-Bearbeiten,
 * Fin-Tel-Rechnung-Import): a new invoice, the review of an imported one, or the edit of
 * one. It replaces the detail sheet.
 *
 * Beside the fields sits the receipt: the imported or attached PDF (with the button that
 * removes it), or the button that attaches one; in the edit, the stored receipt to open.
 * After an import the form says "Rechnung gelesen — bitte prüfen." or "Kein ZUGFeRD
 * erkannt" and, when an invoice with the same number exists, warns about it with
 * "Vorhandene öffnen" (N31). Number, supplier and gross are required for a new invoice.
 * The status is a segmented control "Offen | Bezahlt".
 */
@Component({
  selector: 'app-invoice-form',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    FormsModule,
    IconComponent,
    InputComponent,
    ScrollFadeDirective,
    SegmentedComponent,
    TranslatePipe,
  ],
  templateUrl: './invoice-form.component.html',
  styleUrl: './invoice-form.component.scss',
})
export class InvoiceFormComponent {
  private readonly i18n = inject(I18nService);

  readonly host = input.required<InvoiceFormHost>();
  readonly mode = input<'create' | 'edit'>('create');
  readonly layout = input<FinanceFormLayout>('pane');

  readonly remove = output<void>();
  /** "Vorhandene öffnen" at a duplicate. */
  readonly openDuplicate = output<void>();

  protected readonly title = computed(() => {
    if (this.mode() === 'edit') return 'invoices.edit' as const;
    return this.host().importNotice() === 'parsed' ? ('invoices.importReview' as const) : ('invoices.add' as const);
  });

  protected readonly subtitle = computed(() => {
    if (this.mode() === 'edit') {
      const i = this.host().editing();
      return i?.number ?? '';
    }
    return this.host().importNotice() === 'parsed'
      ? this.i18n.translate('invoices.form.fromFile')
      : this.i18n.translate('expenses.form.required');
  });

  protected readonly statusOptions = computed<SegmentedOption[]>(() =>
    this.host()
      .statusOptions()
      .map((o) => ({ value: String(o.value), label: o.label })),
  );

  /** "212 KB": the size of the imported file. */
  protected readonly fileSize = computed(() => {
    const bytes = this.host().importFileSize();
    if (!bytes) return '';
    const kb = Math.max(1, Math.round(bytes / 1024));
    return kb >= 1024
      ? `${(kb / 1024).toLocaleString(this.i18n.formatLocale(), { maximumFractionDigits: 1 })} MB`
      : `${kb} KB`;
  });

  protected setStatus(value: string | null): void {
    const status: InvoiceStatus = value === 'paid' ? 'paid' : 'open';
    if (this.mode() === 'create') this.host().newStatus.set(status);
    else this.host().editStatus.set(status);
  }

  close(): void {
    if (this.mode() === 'create') this.host().createOpen.set(false);
    else this.host().editing.set(null);
  }

  submit(event: Event): void {
    if (this.mode() === 'create') this.host().create(event);
    else this.host().saveEdit(event);
  }
}
