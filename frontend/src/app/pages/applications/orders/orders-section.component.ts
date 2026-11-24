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
import type { Uuid } from '@core/api/models';
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
  IconComponent,
  MetaLineComponent,
  NoteComponent,
  RowMenuComponent,
  type RowMenuSection,
  SectionComponent,
  type StatusKind,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { OrderDialogComponent } from './order-dialog.component';
import {
  ORDER_KIND_LABEL,
  ORDER_STATUS_KIND,
  ORDER_STATUS_LABEL,
  type OrderAction,
  orderMenu,
  orderPositions,
  priceDifference,
  shownPrice,
} from './orders.util';

/** One row of the section, ready for the template. */
interface Row {
  readonly order: Order;
  /** The Händler and, for an Auslage, the kind. */
  readonly sub: readonly string[];
  readonly status: string;
  readonly statusKind: StatusKind;
  /** The real price, else the planned one; empty in the applicant view. */
  readonly price: string;
  readonly planned: boolean;
  /** The real price minus the planned one with its sign; empty when they are equal. */
  readonly difference: string;
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
 * button for a new Bestellung. Only a person creates a Bestellung. The server decides
 * both rights (`canManage`, `canCreate`).
 */
@Component({
  selector: 'app-orders-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    IconComponent,
    MetaLineComponent,
    NoteComponent,
    OrderDialogComponent,
    RowMenuComponent,
    SectionComponent,
    StatusTextComponent,
  ],
  templateUrl: './orders-section.component.html',
  styleUrl: './orders-section.component.scss',
})
export class OrdersSectionComponent {
  private readonly api = inject(OrdersApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

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

  protected readonly positions = computed(() => orderPositions(this.data()));
  protected readonly items = computed(() => this.list()?.items ?? []);
  protected readonly shown = computed(
    () => this.list() !== null && (this.hasBudget() || this.items().length > 0),
  );

  protected readonly rows = computed<readonly Row[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const canManage = this.list()?.canManage === true;
    return this.items().map((order) => {
      const price = shownPrice(order);
      return {
        order,
        sub: [
          ...(order.supplier ? [order.supplier] : []),
          ...(order.kind === 'outlay' ? [t(ORDER_KIND_LABEL.outlay)] : []),
        ],
        status: t(ORDER_STATUS_LABEL[order.status]),
        statusKind: ORDER_STATUS_KIND[order.status],
        price: this.money(price.amount),
        planned: price.planned && price.amount !== null,
        difference: formatMoney(priceDifference(order), this.i18n.formatLocale(), {
          currency: this.currency(),
          signed: true,
        }),
        menu: canManage ? orderMenu(order, t) : [],
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
      : this.i18n.translate('orders.section.sum', { total });
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
      case 'ordered':
      case 'delivered':
      case 'cancelled':
        return this.setStatus(order, action as OrderStatus);
    }
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
      error: () => {
        this.busy.set(false);
        this.deleting.set(null);
        this.toast.show(this.i18n.translate('orders.error.delete'), 'error');
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
        const stale = err.error?.code === 'order_version_conflict';
        this.toast.show(
          this.i18n.translate(stale ? 'orders.error.version' : 'orders.error.save'),
          'error',
        );
        if (stale) this.load();
      },
    });
  }

  private money(value: unknown): string {
    return formatMoney(value, this.i18n.formatLocale(), { currency: this.currency() });
  }
}
