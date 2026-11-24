import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Application, Transition, Uuid } from '@core/api/models';
import {
  type Order,
  type OrderBooking,
  type OrderList,
  type OrderStatus,
  OrdersApiService,
} from '@core/api/orders.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { formatMoney } from '@shared/format-money';
import { positionValue } from '@shared/forms/positions';
import {
  type Action,
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  DialogBodyDirective,
  DialogComponent,
  FieldGroupComponent,
  FieldPairComponent,
  FieldRowComponent,
  type LoadState,
  NoteComponent,
  type ScreenHead,
  SectionComponent,
  ToastService,
  liveSearch,
} from '@stupa-makers/ui-kit';
import {
  DetailScreenComponent,
  ScreenBodyDirective,
  ScreenCommentsDirective,
} from '@stupa-makers/ui-kit/screens';
import {
  type LinkedLead,
  TodoLinkedListComponent,
} from '../../features/todos/linked-list/todo-linked-list.component';
import {
  type PickRow,
  TodoPickDialogComponent,
} from '../../features/todos/pick-dialog/todo-pick-dialog.component';
import { pageItemTitle } from '../../layout/page-title.service';
import { BUDGET_PERMISSIONS } from '../../layout/nav.service';
import { BudgetTreeApi, type Invoice } from '../budget/budget-tree.api';
import { ChatComponent } from '@shared/ui';
import { OrderCommentsDirective } from './order-comments.directive';
import { OrderFilesComponent } from './order-files.component';
import { OrdersRefresh } from './orders-refresh';
import {
  ORDER_KIND_LABEL,
  ORDER_STATUS_KIND,
  ORDER_STATUS_LABEL,
  type OrderAction,
  type OrderFact,
  factRows,
  orderFacts,
  orderMarks,
  orderPositions,
  priceDifference,
} from './orders.util';

/** The status that follows in the work of a purchase, or null at its end. */
export function nextStatus(status: OrderStatus): 'ordered' | 'delivered' | null {
  switch (status) {
    case 'planned':
      return 'ordered';
    case 'ordered':
      return 'delivered';
    case 'delivered':
    case 'cancelled':
      return null;
  }
}

const STEP_LABEL: Readonly<Record<'ordered' | 'delivered', TranslationKey>> = {
  ordered: 'orders.menu.ordered',
  delivered: 'orders.menu.delivered',
};

/** The facts that the head or a section of the detail shows already. */
const HEAD_FACTS: readonly TranslationKey[] = [
  'orders.field.number',
  'orders.field.status',
  'orders.field.positions',
];

/**
 * The detail of one Bestellung in the pane of the page "Bestellungen".
 *
 * The head holds the Bezeichnung, the number, the status and the marks of the invoice and
 * of the bookings. Below it, for a person with `order.manage`, the next status is the
 * main button and every other action is in the ⋮ menu. The body shows the fields with the
 * planned price, the real price and their signed difference, the positions of the Antrag
 * that the Bestellung covers, the sum of the Bestellungen of the Antrag against its
 * approved amount (a sum above it warns and blocks nothing), the files, the list
 * "Verknüpft" with the Antrag, the invoice and the bookings as built-in rows, and the
 * comments of the Antrag.
 *
 * After a change to "Bestellt" or "Geliefert" the detail offers each transition of the
 * Antrag that the flow marks for this status and that the person can fire. The person
 * fires it or closes the offer; nothing fires by itself.
 */
@Component({
  selector: 'app-order-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    ConfirmDialogComponent,
    DetailScreenComponent,
    DialogBodyDirective,
    DialogComponent,
    FieldGroupComponent,
    FieldPairComponent,
    FieldRowComponent,
    NoteComponent,
    OrderCommentsDirective,
    ChatComponent,
    OrderFilesComponent,
    ScreenBodyDirective,
    ScreenCommentsDirective,
    SectionComponent,
    TodoLinkedListComponent,
    TodoPickDialogComponent,
  ],
  templateUrl: './order-detail.component.html',
})
export class OrderDetailComponent {
  private readonly api = inject(OrdersApiService);
  private readonly client = inject(ApiClient);
  private readonly budget = inject(BudgetTreeApi);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly refresh = inject(OrdersRefresh);

  protected readonly order = signal<Order | null>(null);
  private readonly failed = signal(false);
  private readonly application = signal<Application | null>(null);
  private readonly list = signal<OrderList | null>(null);
  private readonly bookings = signal<readonly OrderBooking[]>([]);
  protected readonly busy = signal(false);
  protected readonly deleting = signal(false);
  protected readonly cancelling = signal(false);
  protected readonly linking = signal(false);
  protected readonly invoiceRows = signal<readonly PickRow[] | null>(null);
  protected readonly invoicePick = signal<Uuid | null>(null);
  /** The transitions of the Antrag that the last status change offers. */
  protected readonly offered = signal<readonly Transition[]>([]);
  private id = '';

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

  protected readonly canManage = computed(
    () => this.list()?.canManage ?? this.auth.can('order.manage'),
  );
  private readonly currency = computed(() => this.application()?.currency ?? null);

  protected readonly state = computed<LoadState<Order>>(() => {
    const order = this.order();
    if (order) return { state: 'ready', data: order };
    return this.failed()
      ? {
          state: 'error',
          message: this.i18n.translate('orders.error.load'),
          retry: () => this.load(),
        }
      : { state: 'loading' };
  });

  protected readonly head = computed<ScreenHead>(() => {
    const order = this.order();
    if (!order) return { title: this.i18n.translate('orders.kind.order'), back: null };
    const marks = orderMarks(order, this.i18n.formatLocale(), this.currency(), (key, params) =>
      this.i18n.translate(key, params),
    );
    return {
      title: order.title,
      kicker: order.number,
      status: {
        label: this.i18n.translate(ORDER_STATUS_LABEL[order.status]),
        kind: ORDER_STATUS_KIND[order.status],
      },
      meta: [
        ...(order.kind === 'outlay' ? [{ label: this.i18n.translate(ORDER_KIND_LABEL.outlay) }] : []),
        ...marks.map((label) => ({ label })),
      ],
      back: null,
    };
  });

  /** The next status of the work: the main button of the detail. */
  protected readonly step = computed(() => {
    const order = this.order();
    const next = order && this.canManage() ? nextStatus(order.status) : null;
    return next ? { status: next, label: this.i18n.translate(STEP_LABEL[next]) } : null;
  });

  protected readonly actions = computed<readonly Action[]>(() => {
    const order = this.order();
    if (!order || !this.canManage()) return [];
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const main = this.step()?.status ?? null;
    const item = (key: OrderAction | 'invoiceUnlink', label: string, more: Partial<Action> = {}): Action => ({
      key,
      label,
      priority: 'menu',
      ...more,
    });
    const steps = (['ordered', 'delivered'] as const)
      .filter((status) => status !== order.status && status !== main)
      .map((status) => item(status, t(STEP_LABEL[status]), { icon: status === 'ordered' ? 'send' : 'check' }));
    const book = this.auth.can('budget.book');
    return [
      ...steps,
      ...(this.auth.canAny(...BUDGET_PERMISSIONS)
        ? [item('invoiceLink', t('orders.menu.invoiceLink'), { icon: 'link' })]
        : []),
      ...(order.invoiceId
        ? [item('invoiceUnlink', t('orders.invoice.unlink'), { icon: 'x' })]
        : []),
      ...(book
        ? [
            item('invoiceNew', t('orders.menu.invoiceNew'), {
              icon: 'receipt',
              route: { commands: ['/invoices'], query: { new: 'invoice', order: order.id } },
            }),
            item('booking', t('orders.menu.booking'), {
              icon: 'plus',
              route: { commands: ['/expenses'], query: { new: 'booking', order: order.id } },
            }),
          ]
        : []),
      item('edit', t('action.edit'), {
        icon: 'edit',
        priority: 'head',
        route: { commands: ['/orders', order.id, 'edit'] },
      }),
      ...(order.status === 'cancelled' ? [] : [item('cancelled', t('orders.menu.cancel'), { icon: 'x' })]),
      item('delete', t('action.delete'), { icon: 'trash', kind: 'danger' }),
    ];
  });

  protected readonly factRows = computed(() => factRows(this.facts()));

  private readonly positions = computed(() => orderPositions(this.application()?.data));

  protected readonly facts = computed<readonly OrderFact[]>(() => {
    const order = this.order();
    if (!order) return [];
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const hidden = new Set(HEAD_FACTS.map(t));
    const difference = formatMoney(priceDifference(order), this.i18n.formatLocale(), {
      currency: this.currency(),
      signed: true,
    });
    const actual = t('orders.field.actual');
    return orderFacts(order, this.positions(), this.i18n.formatLocale(), this.currency(), t)
      .filter((fact) => !hidden.has(fact.label))
      .flatMap((fact) =>
        fact.label === actual && difference
          ? [fact, { label: t('orders.field.difference'), value: difference, mono: true }]
          : [fact],
      );
  });

  /** The positions of the Antrag that the Bestellung covers, with their preferred offer. */
  protected readonly covered = computed(() => {
    const byId = new Map(this.positions().map((p) => [p.id, p]));
    return (this.order()?.positionIds ?? []).map((id) => {
      const position = byId.get(id);
      return {
        id,
        label: position?.label ?? this.i18n.translate('orders.position.removed'),
        value: position ? this.money(positionValue(position)) : '',
      };
    });
  });

  protected readonly sumLine = computed(() => {
    const list = this.list();
    if (!list || list.total === null) return '';
    const total = this.money(list.total);
    const approved = this.money(list.approvedAmount);
    return approved ? this.i18n.translate('orders.section.sumOfApproved', { total, approved }) : total;
  });

  protected readonly warning = computed(() => {
    const over = this.money(this.list()?.overBy);
    return over ? this.i18n.translate('orders.section.over', { amount: over }) : '';
  });

  /** The Antrag, the invoice and the bookings: relations of the data, so without a remove. */
  protected readonly linked = computed<readonly LinkedLead[]>(() => {
    const order = this.order();
    if (!order) return [];
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const invoiceMark = t(order.invoiceStatus === 'paid' ? 'orders.mark.invoicePaid' : 'orders.mark.invoiceOpen');
    return [
      ...(order.applicationId
        ? [
            {
              icon: 'file' as const,
              title: order.applicationTitle || t('applications.list.untitled'),
              sub: t('orders.linked.application'),
              link: ['/applications', order.applicationId],
            },
          ]
        : []),
      ...(order.invoiceId
        ? [
            {
              icon: 'receipt' as const,
              title: order.invoiceNumber || t('orders.invoice.unnumbered'),
              sub: `${t('orders.field.invoice')} · ${invoiceMark}`,
              link: ['/invoices'],
              queryParams: { id: order.invoiceId },
            },
          ]
        : []),
      ...this.bookings().map((booking) => ({
        icon: 'swap' as const,
        title: booking.description || t('orders.linked.booking'),
        sub: `${t('orders.linked.booking')} · ${this.money(booking.amount)}`,
        link: ['/expenses'],
        queryParams: { id: booking.id },
      })),
    ];
  });

  protected readonly cancelBody = computed(() =>
    this.i18n.translate('orders.cancel.body', {
      title: this.order()?.title ?? '',
      amount: this.money(this.order()?.bookedAmount),
    }),
  );

  constructor() {
    pageItemTitle(() => this.order()?.title);
    this.route.paramMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      this.id = params.get('id') ?? '';
      this.order.set(null);
      this.application.set(null);
      this.list.set(null);
      this.bookings.set([]);
      this.offered.set([]);
      this.load();
    });
  }

  /** Read the Bestellung, then what the detail shows of its Antrag. */
  private load(): void {
    const id = this.id;
    this.failed.set(false);
    this.api.get(id).subscribe({
      next: (order) => {
        if (id !== this.id) return;
        this.order.set(order);
        this.loadAround(order);
      },
      error: () => {
        if (id === this.id) this.failed.set(true);
      },
    });
  }

  /** A read that fails leaves its part of the detail out. */
  private loadAround(order: Order): void {
    const id = this.id;
    const applicationId = order.applicationId;
    if (!applicationId) return;
    const mine = (): boolean => id === this.id;
    this.api.list(applicationId).subscribe({
      next: (list) => mine() && this.list.set(list),
      error: () => undefined,
    });
    if (!this.application()) {
      this.client.getApplication(applicationId, { quiet: true }).subscribe({
        next: (application) => mine() && this.application.set(application),
        error: () => undefined,
      });
    }
    if (this.auth.canAny(...BUDGET_PERMISSIONS)) {
      this.api.bookings(order.id).subscribe({
        next: (bookings) => mine() && this.bookings.set(bookings),
        error: () => undefined,
      });
    }
  }

  protected onAction(key: string): void {
    const order = this.order();
    if (!order) return;
    switch (key as OrderAction | 'invoiceUnlink') {
      case 'ordered':
      case 'delivered':
        return this.setStatus(key as OrderStatus);
      case 'cancelled':
        return Number(order.bookedAmount) > 0 ? this.cancelling.set(true) : this.setStatus('cancelled');
      case 'delete':
        return this.deleting.set(true);
      case 'invoiceLink':
        this.linking.set(true);
        this.invoicePick.set(order.invoiceId ?? null);
        this.invoiceSearch.sync('');
        return this.invoiceSearch.refresh();
      case 'invoiceUnlink':
        return this.setInvoice(null);
      case 'invoiceNew':
      case 'booking':
      case 'edit':
        return;
    }
  }

  protected confirmCancel(): void {
    this.cancelling.set(false);
    this.setStatus('cancelled');
  }

  protected setStatus(status: OrderStatus): void {
    const order = this.order();
    if (!order || this.busy()) return;
    this.busy.set(true);
    this.api.setStatus(order.id, status, order.version ?? 1).subscribe({
      next: (saved) => {
        this.took(saved);
        if (status === 'ordered' || status === 'delivered') this.offer(saved, status);
      },
      error: (err: { error?: { code?: string } | null }) => this.fail(err),
    });
  }

  /** Ask the flow which transitions of the Antrag fit the new status. */
  private offer(order: Order, status: 'ordered' | 'delivered'): void {
    if (!order.applicationId) return;
    this.client.transitions(order.applicationId, { orderStatus: status }).subscribe({
      next: (transitions) => this.offered.set(transitions),
      error: () => undefined,
    });
  }

  protected readonly offerActions = computed<Action[]>(() => [
    { key: '', label: this.i18n.translate('orders.offer.later') },
    ...this.offered().map((transition, index) => ({
      key: transition.id,
      label: transition.label,
      ...(index === 0 ? { kind: 'main' as const } : {}),
    })),
  ]);

  /** Fire the picked transition. One that asks for a meeting or a decision opens the Antrag. */
  protected onOffer(key: string): void {
    const transition = this.offered().find((t) => t.id === key);
    const applicationId = this.order()?.applicationId;
    this.offered.set([]);
    if (!transition || !applicationId) return;
    if (transition.addsToAgenda || transition.allowsDecision) {
      void this.router.navigate(['/applications', applicationId]);
      return;
    }
    this.client.fireTransition(applicationId, { transitionId: transition.id }).subscribe({
      next: () => this.toast.show(this.i18n.translate('orders.offer.done', { label: transition.label }), 'success'),
      error: () => this.toast.show(this.i18n.translate('orders.offer.failed'), 'error'),
    });
  }

  private showInvoices(rows: readonly Invoice[]): void {
    this.invoiceRows.set(
      rows.map((invoice) => ({
        id: invoice.id,
        title: invoice.number || this.i18n.translate('orders.invoice.unnumbered'),
        sub: [
          invoice.supplier ?? '',
          this.money(invoice.grossAmount),
          this.i18n.translate(invoice.status === 'paid' ? 'orders.mark.invoicePaid' : 'orders.mark.invoiceOpen'),
        ]
          .filter(Boolean)
          .join(' · '),
      })),
    );
    if (!rows.some((invoice) => invoice.id === this.invoicePick())) {
      this.invoicePick.set(rows[0]?.id ?? null);
    }
  }

  /** Set the invoice of the Bestellung, or take it away with null. The invoice stays. */
  protected setInvoice(invoiceId: Uuid | null): void {
    const order = this.order();
    if (!order || this.busy()) return;
    this.busy.set(true);
    this.api.setInvoice(order.id, invoiceId, order.version ?? 1).subscribe({
      next: (saved) => {
        this.linking.set(false);
        this.took(saved);
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.linking.set(false);
        this.fail(err);
      },
    });
  }

  protected confirmDelete(): void {
    const order = this.order();
    if (!order || this.busy()) return;
    this.busy.set(true);
    this.api.remove(order.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.deleting.set(false);
        this.refresh.touch();
        void this.router.navigate(['/orders'], { queryParamsHandling: 'preserve' });
      },
      error: (err: { error?: { code?: string } | null }) => {
        this.busy.set(false);
        this.deleting.set(false);
        const key = err.error?.code === 'order_has_bookings' ? 'orders.error.hasBookings' : 'orders.error.delete';
        this.toast.show(this.i18n.translate(key), 'error');
      },
    });
  }

  /** A write went through: show the answer, read the parts around it and tell the list. */
  private took(saved: Order): void {
    this.busy.set(false);
    this.order.set(saved);
    this.loadAround(saved);
    this.refresh.touch();
  }

  /** A write failed: say why, and read again after a change of another person. */
  private fail(err: { error?: { code?: string } | null }): void {
    this.busy.set(false);
    const stale = err.error?.code === 'order_version_conflict';
    this.toast.show(this.i18n.translate(stale ? 'orders.error.version' : 'orders.error.save'), 'error');
    if (stale) this.load();
  }

  private money(value: unknown): string {
    return formatMoney(value, this.i18n.formatLocale(), { currency: this.currency() });
  }
}
