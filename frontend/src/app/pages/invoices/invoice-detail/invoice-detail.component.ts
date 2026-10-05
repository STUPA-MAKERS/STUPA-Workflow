import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import {
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SegBarComponent,
  StatusTextComponent,
  invoiceStatus,
} from '@shared/ui';
import type { Invoice, InvoiceBooking } from '../../budget/budget-tree.api';
import {
  type CostCentreLabel,
  costCentreLabel,
  daysUntil,
  formatEur,
  shortDate,
  signedEur,
  vatRate,
} from '../../budget/expense-display.util';
import { bookedOn } from '../invoice-figures';

/**
 * The detail of an invoice (boards Fin-Rechnungen, Fin-Schmal-Rechnung, Fin-Tel-Rechnung):
 * "Rechnung · <Nummer>", the supplier, "Status · fällig … · in n Tagen · Brutto", the
 * actions "Als bezahlt markieren" and "Buchung anlegen", then the receipt, the amounts
 * (net, VAT with its rate, gross), the data and the bookings with the booked share.
 *
 * The receipt shows as a file to open: the server sends the PDF as a download only, and
 * the page shows no PDF inside the app.
 */
@Component({
  selector: 'app-invoice-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    IconComponent,
    LocalizedDatePipe,
    RouterLink,
    RowMenuComponent,
    SegBarComponent,
    StatusTextComponent,
    TranslatePipe,
  ],
  templateUrl: './invoice-detail.component.html',
  styleUrl: './invoice-detail.component.scss',
})
export class InvoiceDetailComponent {
  private readonly i18n = inject(I18nService);

  readonly invoice = input.required<Invoice>();
  readonly costCentres = input<ReadonlyMap<string, CostCentreLabel>>(new Map());
  /** `budget.book`: edit, delete, mark paid, add a booking. */
  readonly canManage = input(false);
  readonly split = input(false);
  readonly phone = input(false);
  /** "Als bezahlt markieren" runs. */
  readonly markingPaid = input(false);

  readonly edit = output<void>();
  readonly remove = output<void>();
  readonly markPaid = output<void>();
  readonly createBooking = output<void>();
  readonly openFile = output<void>();

  protected readonly status = computed(() => invoiceStatus(this.invoice().status));

  protected readonly title = computed(() => {
    const i = this.invoice();
    return i.supplier || i.number || this.i18n.translate('invoices.untitled');
  });

  protected readonly metaLine = computed(() => {
    const i = this.invoice();
    const kind = this.i18n.translate('invoices.detail.kind');
    return i.number ? `${kind} · ${i.number}` : kind;
  });

  /** "in 9 Tagen", "heute fällig" or "seit 3 Tagen überfällig", for an open invoice. */
  protected readonly due = computed(() => {
    const i = this.invoice();
    if (i.status !== 'open' || !i.dueDate) return null;
    const days = daysUntil(i.dueDate);
    if (days > 0) {
      return {
        text: this.i18n.translate(days === 1 ? 'invoices.due.tomorrow' : 'invoices.due.inDays', { days }),
        late: false,
      };
    }
    if (days === 0) return { text: this.i18n.translate('invoices.due.today'), late: true };
    return {
      text: this.i18n.translate(days === -1 ? 'invoices.due.overdueOne' : 'invoices.due.overdue', {
        days: -days,
      }),
      late: true,
    };
  });

  /** "USt. 19 %" when tax / net gives a common rate, else "USt.". */
  protected readonly taxLabel = computed(() => {
    const i = this.invoice();
    const rate = vatRate(i.netAmount, i.taxAmount);
    return rate === null
      ? this.i18n.translate('invoices.field.tax')
      : this.i18n.translate('invoices.taxRate', { rate });
  });

  protected readonly booked = computed(() => bookedOn(this.invoice()));

  protected readonly bookings = computed(() => this.invoice().linkedBookings ?? []);

  protected readonly createdAt = computed(() =>
    new Date(this.invoice().createdAt).toLocaleDateString(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }),
  );

  protected readonly menu = computed<RowMenuSection[]>(() => {
    const i = this.invoice();
    const items: RowMenuItem[] = [];
    if (this.phone() && i.hasFile) {
      items.push({ id: 'file', label: this.i18n.translate('invoices.openFile'), icon: 'download' });
    }
    const sections: RowMenuSection[] = items.length ? [{ items }] : [];
    if (this.canManage()) {
      sections.push({
        items: [{ id: 'delete', label: this.i18n.translate('action.delete'), icon: 'delete', danger: true }],
      });
    }
    return sections;
  });

  onMenu(item: RowMenuItem): void {
    if (item.id === 'file') this.openFile.emit();
    else if (item.id === 'delete') this.remove.emit();
  }

  money(value: string | number): string {
    return formatEur(Number(value), this.i18n.locale());
  }

  cc(b: InvoiceBooking): CostCentreLabel {
    const known = costCentreLabel(this.costCentres(), b.budgetId, b.pathKey || null);
    return this.costCentres().has(b.budgetId) ? known : { ...known, name: b.budgetName || known.name };
  }

  signed(b: InvoiceBooking): string {
    return signedEur(b.kind, b.amount, this.i18n.locale());
  }

  day(iso: string | null): string {
    return shortDate(iso, this.i18n.locale());
  }

  /** The booking a row opens: a sub-booking opens its parent, which the list shows. */
  bookingTarget(b: InvoiceBooking): string {
    return b.parentExpenseId ?? b.id;
  }

  bookedLabel(booked: number, gross: number): string {
    return this.i18n.translate('invoices.bookedLabel', {
      booked: this.money(booked),
      gross: this.money(gross),
    });
  }
}
