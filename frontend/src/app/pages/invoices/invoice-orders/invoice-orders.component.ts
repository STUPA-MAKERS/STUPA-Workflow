import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import type { Uuid } from '@core/api/models';
import { type InvoiceOrders, OrdersApiService } from '@core/api/orders.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { formatMoney } from '@shared/format-money';
import {
  FieldGroupComponent,
  FieldRowComponent,
  IconComponent,
  ListItemComponent,
  SectionComponent,
} from '@stupa-makers/ui-kit';

/** One Bestellung of the invoice, ready for the template. */
interface Row {
  readonly key: string;
  readonly title: string;
  /** The title of the Antrag; empty for a row without access. */
  readonly sub: string;
  /** The real price, or "Ohne tatsächlichen Preis"; empty for a row without access. */
  readonly price: string;
  /** The Antrag of the Bestellung; null for a row without access. */
  readonly link: readonly string[] | null;
}

/**
 * The Bestellungen that name an invoice, in the detail of the invoice.
 *
 * Each row has the number, the Bezeichnung, the Antrag and the real price of a
 * Bestellung, and opens its Antrag. A Bestellung of an Antrag that the reader does not
 * read shows as "Bestellung (kein Zugriff)" without a value. The line below the rows
 * gives the sum of the real prices beside the gross amount of the invoice: on an invoice
 * for several purchases it tells how much of the gross amount the Bestellungen cover.
 *
 * Without a Bestellung the host is hidden, so it takes no space.
 */
@Component({
  selector: 'app-invoice-orders',
  host: { '[attr.hidden]': "rows().length ? null : ''" },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    FieldGroupComponent,
    FieldRowComponent,
    IconComponent,
    ListItemComponent,
    SectionComponent,
  ],
  templateUrl: './invoice-orders.component.html',
})
export class InvoiceOrdersComponent {
  private readonly api = inject(OrdersApiService);
  private readonly i18n = inject(I18nService);

  readonly invoiceId = input.required<Uuid>();
  /** The gross amount of the invoice, as a decimal string. */
  readonly gross = input<string | null>(null);

  private readonly list = signal<InvoiceOrders | null>(null);

  protected readonly rows = computed<readonly Row[]>(() =>
    (this.list()?.items ?? []).map((item, index) =>
      item.accessible && item.id && item.applicationId
        ? {
            key: item.id,
            title: [item.number, item.title].filter(Boolean).join(' · '),
            sub: [
              item.applicationTitle,
              item.actualAmount ? null : this.i18n.translate('orders.ofInvoice.noPrice'),
            ]
              .filter(Boolean)
              .join(' · '),
            price: this.money(item.actualAmount),
            link: ['/applications', item.applicationId],
          }
        : {
            key: `hidden-${index}`,
            title: this.i18n.translate('orders.ofInvoice.noAccess'),
            sub: '',
            price: '',
            link: null,
          },
    ),
  );

  /** "72,50 € von 150,00 €": the sum of the real prices beside the gross amount. */
  protected readonly sumLine = computed(() => {
    const total = this.money(this.list()?.total ?? null);
    const gross = this.money(this.gross());
    return gross ? this.i18n.translate('orders.ofInvoice.sumOfGross', { total, gross }) : total;
  });

  constructor() {
    effect(() => {
      const id = this.invoiceId();
      this.list.set(null);
      this.api.ofInvoice(id).subscribe({
        next: (list) => {
          if (id === this.invoiceId()) this.list.set(list);
        },
        error: () => undefined,
      });
    });
  }

  private money(value: string | null): string {
    return formatMoney(value, this.i18n.formatLocale());
  }
}
