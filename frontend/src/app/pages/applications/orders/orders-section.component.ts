import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { map } from 'rxjs';
import { Router } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import {
  type Order,
  type OrderList,
  type OrderStatus,
  OrdersApiService,
} from '@core/api/orders.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { formatMoney } from '@shared/format-money';
import {
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  EmptyStateComponent,
  FieldGroupComponent,
  FieldRowComponent,
  IconComponent,
  ListItemComponent,
  MetaLineComponent,
  NoteComponent,
  RowMenuComponent,
  type RowMenuSection,
  SectionComponent,
  type StatusKind,
  StatusTextComponent,
  ToastService,
  liveSearch,
} from '@stupa-makers/ui-kit';
import {
  type PickRow,
  TodoPickDialogComponent,
} from '../../../features/todos/pick-dialog/todo-pick-dialog.component';
import { BUDGET_PERMISSIONS } from '../../../layout/nav.service';
import { BudgetTreeApi, type Invoice } from '../../budget/budget-tree.api';
import { OrderDialogComponent } from './order-dialog.component';
import {
  ORDER_KIND_LABEL,
  ORDER_STATUS_KIND,
  ORDER_STATUS_LABEL,
  type OrderAction,
  orderMarks,
  orderMenu,
  orderPositions,
  priceDifference,
  shownPrice,
} from './orders.util';

/** One row of the section, ready for the template. */
interface Row {
  readonly order: Order;
  /** After the status: the kind of an Auslage, the Händler, "Preis geplant" for a planned
   *  price or the signed difference of the real price to the planned one, then the marks
   *  of the invoice and of the bookings. */
  readonly sub: readonly string[];
  readonly status: string;
  readonly statusKind: StatusKind;
  /** The real price, else the planned one; empty in the applicant view. */
  readonly price: string;
  readonly menu: readonly RowMenuSection[];
}

/**
 * The section "Bestellungen" in the detail of an Antrag.
 *
 * It shows for a type with money, and for any Antrag that has a Bestellung. A row holds
 * the Bezeichnung, the Händler, the status and the price: the real price, else the
 * planned one with the word "geplant", and the signed difference when both differ. The
 * line below the rows gives the sum and the approved amount. A sum above the approved
 * amount shows a warning and blocks nothing. The heading has no count.
 *
 * A person with `order.manage` gets the ⋮ menu of a row and, on an approved Antrag, the
 * button for a new Bestellung. "Rechnung verknüpfen" picks an invoice in a dialog.
 * "Rechnung anlegen" and "Buchung anlegen" open the form of the invoices page and of the
 * bookings page with the values of the Bestellung. The cancel of a Bestellung with a
 * booking asks first and keeps the bookings. Before the list arrived, and for a type without money and
 * without a Bestellung, the host is hidden, so it takes no space and no gap. Only a person creates a Bestellung. The server decides
 * both rights (`canManage`, `canCreate`).
 */
@Component({
  selector: 'app-orders-section',
  host: { '[attr.hidden]': "shown() ? null : ''" },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    FieldGroupComponent,
    FieldRowComponent,
    IconComponent,
    ListItemComponent,
    MetaLineComponent,
    NoteComponent,
    OrderDialogComponent,
    RowMenuComponent,
    SectionComponent,
    StatusTextComponent,
    TodoPickDialogComponent,
  ],
  templateUrl: './orders-section.component.html',
})
export class OrdersSectionComponent {
  private readonly api = inject(OrdersApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly budget = inject(BudgetTreeApi);

  readonly applicationId = input.required<Uuid>();
  /** The type of the Antrag asks for money. */
  readonly hasBudget = input(false);
  /** The answers of the Antrag: the form of a Bestellung offers their positions. */
  readonly data = input<Readonly<Record<string, unknown>> | null>(null);
  readonly currency = input<string | null>(null);
  readonly headingId = input<string | null>(null);

  /** A Bestellung was created, changed or deleted: the timeline of the Antrag is stale. */
  readonly changed = output<void>();

  protected readonly list = signal<OrderList | null>(null);
  protected readonly dialogOpen = signal(false);
  /** The Bestellung in the dialog, or null for a new one. */
  protected readonly editing = signal<Order | null>(null);
  protected readonly deleting = signal<Order | null>(null);
  protected readonly busy = signal(false);
  /** The booked Bestellung whose cancel waits for the confirmation. */
  protected readonly cancelling = signal<Order | null>(null);
  /** The Bestellung that gets an invoice in the pick dialog. */
  protected readonly linking = signal<Order | null>(null);
  /** The invoices of the pick dialog; null while they load. */
  protected readonly invoiceRows = signal<readonly PickRow[] | null>(null);
  protected readonly invoicePick = signal<Uuid | null>(null);
  protected readonly invoiceSearch = liveSearch<readonly Invoice[]>({
    run: (q) => {
      this.invoiceRows.set(null);
      return this.budget
        .listInvoicesPaged({ ...(q ? { q } : {}), limit: 20 })
        .pipe(map((page) => page.items));
    },
    result: (rows) => this.showInvoices(rows),
    error: () => this.invoiceRows.set([]),
  });

  protected readonly cancelBody = computed(() => {
    const order = this.cancelling();
    return order
      ? this.i18n.translate('orders.cancel.body', {
          title: order.title,
          amount: this.money(order.bookedAmount),
        })
      : '';
  });

  protected readonly positions = computed(() => orderPositions(this.data()));
  protected readonly items = computed(() => this.list()?.items ?? []);
  protected readonly shown = computed(
    () => this.list() !== null && (this.hasBudget() || this.items().length > 0),
  );

  protected readonly rows = computed<readonly Row[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const canManage = this.list()?.canManage === true;
    const rights = {
      invoices: this.auth.canAny(...BUDGET_PERMISSIONS),
      book: this.auth.can('budget.book'),
    };
    return this.items().map((order) => {
      const price = shownPrice(order);
      const difference = formatMoney(priceDifference(order), this.i18n.formatLocale(), {
        currency: this.currency(),
        signed: true,
      });
      return {
        order,
        sub: [
          ...(order.kind === 'outlay' ? [t(ORDER_KIND_LABEL.outlay)] : []),
          ...(order.supplier ? [order.supplier] : []),
          ...(price.planned && price.amount !== null ? [t('orders.section.planned')] : []),
          ...(difference ? [difference] : []),
          ...orderMarks(order, this.i18n.formatLocale(), this.currency(), (key, params) =>
            this.i18n.translate(key, params),
          ),
        ],
        status: t(ORDER_STATUS_LABEL[order.status]),
        statusKind: ORDER_STATUS_KIND[order.status],
        price: this.money(price.amount),
        menu: canManage ? orderMenu(order, t, rights) : [],
      };
    });
  });

  /** The sum line: the sum and the approved amount; empty in the applicant view. */
  protected readonly sumLine = computed(() => {
    const list = this.list();
    if (!list || list.total === null || !list.items.length) return '';
    const total = this.money(list.total);
    const approved = this.money(list.approvedAmount);
    return approved
      ? this.i18n.translate('orders.section.sumOfApproved', { total, approved })
      : total;
  });

  protected readonly warning = computed(() => {
    const over = this.money(this.list()?.overBy);
    return over ? this.i18n.translate('orders.section.over', { amount: over }) : '';
  });

  constructor() {
    effect(() => {
      this.applicationId();
      this.list.set(null);
      this.load();
    });
  }

  /** Read the Bestellungen again. A failed read leaves the section as it is. */
  load(): void {
    const id = this.applicationId();
    this.api.list(id).subscribe({
      next: (list) => {
        if (id === this.applicationId()) this.list.set(list);
      },
      error: () => undefined,
    });
  }

  protected open(order: Order | null): void {
    this.editing.set(order);
    this.dialogOpen.set(true);
  }

  protected onMenu(order: Order, action: string): void {
    switch (action as OrderAction) {
      case 'edit':
        return this.open(order);
      case 'delete':
        return this.deleting.set(order);
      case 'invoiceLink':
        return this.openInvoicePick(order);
      case 'invoiceNew':
        return void this.router.navigate(['/invoices'], {
          queryParams: { new: 'invoice', order: order.id },
        });
      case 'booking':
        return void this.router.navigate(['/expenses'], {
          queryParams: { new: 'booking', order: order.id },
        });
      case 'cancelled':
        return Number(order.bookedAmount) > 0
          ? this.cancelling.set(order)
          : this.setStatus(order, 'cancelled');
      case 'ordered':
      case 'delivered':
        return this.setStatus(order, action as OrderStatus);
    }
  }

  /** The cancel of a booked Bestellung was confirmed. The bookings stay. */
  protected confirmCancel(): void {
    const order = this.cancelling();
    this.cancelling.set(null);
    if (order) this.setStatus(order, 'cancelled');
  }

  private openInvoicePick(order: Order): void {
    this.linking.set(order);
    this.invoicePick.set(order.invoiceId ?? null);
    this.invoiceSearch.sync('');
    this.invoiceSearch.refresh();
  }

  private showInvoices(rows: readonly Invoice[]): void {
    this.invoiceRows.set(
      rows.map((invoice) => ({
        id: invoice.id,
        title: invoice.number || this.i18n.translate('orders.invoice.unnumbered'),
        sub: [
          invoice.supplier ?? '',
          this.money(invoice.grossAmount),
          this.i18n.translate(
            invoice.status === 'paid' ? 'orders.mark.invoicePaid' : 'orders.mark.invoiceOpen',
          ),
        ]
          .filter(Boolean)
          .join(' · '),
      })),
    );
    if (!rows.some((invoice) => invoice.id === this.invoicePick())) {
      this.invoicePick.set(rows[0]?.id ?? null);
    }
  }

  /** The picked invoice becomes the invoice of the Bestellung. */
  protected linkInvoice(invoiceId: Uuid): void {
    const order = this.linking();
    if (!order || this.busy()) return;
    this.busy.set(true);
    this.api.setInvoice(order.id, invoiceId, order.version ?? 1).subscribe({
      next: () => {
        this.busy.set(false);
        this.linking.set(null);
        this.onChanged();
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.busy.set(false);
        this.linking.set(null);
        this.fail(err);
      },
    });
  }

  /** A change went through: read the list again and tell the page. */
  protected onChanged(): void {
    this.load();
    this.changed.emit();
  }

  protected confirmDelete(): void {
    const order = this.deleting();
    if (!order || this.busy()) return;
    this.busy.set(true);
    this.api.remove(order.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.deleting.set(null);
        this.onChanged();
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.busy.set(false);
        this.deleting.set(null);
        this.toast.show(
          this.i18n.translate(
            err.error?.code === 'order_has_bookings'
              ? 'orders.error.hasBookings'
              : 'orders.error.delete',
          ),
          'error',
        );
      },
    });
  }

  private setStatus(order: Order, status: OrderStatus): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.api.setStatus(order.id, status, order.version ?? 1).subscribe({
      next: () => {
        this.busy.set(false);
        this.onChanged();
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.busy.set(false);
        this.fail(err);
      },
    });
  }

  /** A write failed: say why, and read the list again after a change of another person. */
  private fail(err: { error?: { code?: string } | null }): void {
    const stale = err.error?.code === 'order_version_conflict';
    this.toast.show(
      this.i18n.translate(stale ? 'orders.error.version' : 'orders.error.save'),
      'error',
    );
    if (stale) this.load();
  }

  private money(value: unknown): string {
    return formatMoney(value, this.i18n.formatLocale(), { currency: this.currency() });
  }
}
