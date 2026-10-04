import {
  ChangeDetectionStrategy,
  Component,
  type Signal,
  type WritableSignal,
  computed,
  input,
} from '@angular/core';
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
import type { Invoice, InvoiceStatus } from '../../budget/budget-tree.api';

/** What the import found: `parsed` (ZUGFeRD read), `manual` (no ZUGFeRD), or nothing. */
export type InvoiceImportNotice = 'parsed' | 'manual' | null;

/**
 * What the dialog reads and writes on the invoices page. The page keeps the values and
 * the requests, so its specs drive one place.
 */
export interface InvoiceDialogHost {
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
  readonly editGrossValid: Signal<boolean>;
  saveEdit(event: Event): void;
}

/**
 * The invoice dialog (board Arbeit-Rechnung-Import): a new invoice, the review of an
 * imported one, or the edit of one.
 *
 * After an import it shows the file, "Rechnung gelesen — bitte prüfen." and, when an
 * invoice with the same number exists, the duplicate warning (N31). Gross is the only
 * required amount; number and supplier stay optional, as on the server.
 */
@Component({
  selector: 'app-invoice-import-dialog',
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
  templateUrl: './invoice-import-dialog.component.html',
  styleUrl: './invoice-import-dialog.component.scss',
})
export class InvoiceImportDialogComponent {
  readonly host = input.required<InvoiceDialogHost>();
  readonly mode = input<'create' | 'edit'>('create');

  protected readonly open = computed(() =>
    this.mode() === 'create' ? this.host().createOpen() : !!this.host().editing(),
  );

  protected readonly title = computed(() => {
    if (this.mode() === 'edit') return 'invoices.edit';
    return this.host().importNotice() === 'parsed' ? 'invoices.importReview' : 'invoices.add';
  });

  protected close(): void {
    if (this.mode() === 'create') this.host().createOpen.set(false);
    else this.host().editing.set(null);
  }

  protected submit(event: Event): void {
    if (this.mode() === 'create') this.host().create(event);
    else this.host().saveEdit(event);
  }
}
