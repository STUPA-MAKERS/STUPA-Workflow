import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiClient } from '@core/api/api-client.service';
import {
  ORDER_SEGMENTS,
  type Order,
  type OrderQuery,
  type OrderSegment,
  OrdersApiService,
  type PendingApplication,
} from '@core/api/orders.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { formatMoney } from '@shared/format-money';
import {
  type Action,
  type FilterDef,
  type FilterOption,
  type ListQuery,
  type ListRow,
  type LoadState,
  ToastService,
  downloadBlob,
} from '@stupa-makers/ui-kit';
import { ListDetailScreenComponent } from '@stupa-makers/ui-kit/screens';
import { BudgetTreeApi, flattenBudgetOptions } from '../budget/budget-tree.api';
import { ORDER_KIND_LABEL, ORDER_STATUS_KIND, ORDER_STATUS_LABEL, shownPrice } from './orders.util';
import { OrdersRefresh } from './orders-refresh';

/** How many rows one read of the list brings. */
export const ORDERS_PAGE_SIZE = 50;

const SEGMENT_LABEL: Readonly<Record<OrderSegment, TranslationKey>> = {
  pending: 'orders.segment.pending',
  open: 'orders.segment.open',
  delivered: 'orders.segment.delivered',
  done: 'orders.segment.done',
};

const isSegment = (value: unknown): value is OrderSegment =>
  ORDER_SEGMENTS.includes(value as OrderSegment);

const text = (value: unknown): string | undefined =>
  typeof value === 'string' && value !== '' ? value : undefined;

/** The filter of the API from the query of the screen. */
export function orderQuery(query: ListQuery): OrderQuery {
  const f = query.filters;
  return {
    fiscalYear: text(f['fiscalYear']),
    budget: text(f['budget']),
    gremium: text(f['gremium']),
    kind: text(f['kind']),
    buyer: text(f['buyer']),
    q: text(query.search.trim()),
  };
}

/**
 * The page "Bestellungen": the Bestellungen of every Antrag that the person reads, as a
 * list with the detail beside it.
 *
 * The first chip picks the segment: "Ohne Bestellung" lists the approved Anträge that
 * wait for a purchase, "Offen", "Geliefert" and "Erledigt" list the Bestellungen by the
 * step of the work. No segment shows a count. The other chips filter by Haushaltsjahr,
 * Kostenstelle, Gremium, kind and the own purchases, and the search reads the number, the
 * Bezeichnung, the Händler and the Bestellnummer. The search and the chips live in the
 * URL. A row opens its Bestellung in the pane; a row of "Ohne Bestellung" opens the form
 * of a new Bestellung for its Antrag, or the Antrag for a person without `order.manage`.
 */
@Component({
  selector: 'app-orders-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ListDetailScreenComponent],
  templateUrl: './orders-page.component.html',
})
export class OrdersPageComponent {
  private readonly api = inject(OrdersApiService);
  private readonly client = inject(ApiClient);
  private readonly budget = inject(BudgetTreeApi);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  protected readonly canManage = computed(() => this.auth.can('order.manage'));

  private readonly orders = signal<readonly Order[]>([]);
  private readonly waiting = signal<readonly PendingApplication[]>([]);
  private readonly total = signal(0);
  private readonly phase = signal<'loading' | 'ready' | 'error'>('loading');
  private readonly segment = signal<OrderSegment>('open');
  private readonly filter = signal<OrderQuery>({});
  /** Counts the reads, so an answer of an older filter is dropped. */
  private seq = 0;

  private readonly years = signal<readonly FilterOption[]>([]);
  private readonly centres = signal<readonly FilterOption[]>([]);
  private readonly gremien = signal<readonly FilterOption[]>([]);

  protected readonly filters = computed<readonly FilterDef[]>(() => {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const me = this.auth.userId();
    const single = (key: string, label: TranslationKey, options: readonly FilterOption[]): FilterDef => ({
      key,
      label: t(label),
      kind: 'single',
      options,
      value: null,
    });
    return [
      {
        key: 'segment',
        label: t('orders.filter.segment'),
        kind: 'single',
        options: ORDER_SEGMENTS.map((value) => ({ value, label: t(SEGMENT_LABEL[value]) })),
        value: 'open',
      },
      ...(this.years().length ? [single('fiscalYear', 'orders.filter.fiscalYear', this.years())] : []),
      ...(this.centres().length ? [single('budget', 'orders.filter.budget', this.centres())] : []),
      ...(this.gremien().length > 1 ? [single('gremium', 'orders.filter.gremium', this.gremien())] : []),
      single('kind', 'orders.field.kind', [
        { value: 'order', label: t(ORDER_KIND_LABEL.order) },
        { value: 'outlay', label: t(ORDER_KIND_LABEL.outlay) },
      ]),
      ...(me ? [single('buyer', 'orders.filter.buyer', [{ value: me, label: t('orders.filter.mine') }])] : []),
    ];
  });

  protected readonly actions = computed<readonly Action[]>(() =>
    this.canManage()
      ? [
          {
            key: 'new',
            label: this.i18n.translate('orders.dialog.create'),
            icon: 'plus',
            priority: 'head',
            route: { commands: ['/orders', 'new'] },
          },
          {
            key: 'export',
            label: this.i18n.translate('orders.page.export'),
            icon: 'download',
            priority: 'menu',
          },
        ]
      : [],
  );

  protected readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    const pending = this.segment() === 'pending';
    const rows = pending ? this.waiting().map((a) => this.pendingRow(a)) : this.orders().map((o) => this.row(o));
    switch (this.phase()) {
      case 'loading':
        return rows.length ? { state: 'loading', previous: rows } : { state: 'loading' };
      case 'error':
        return {
          state: 'error',
          message: this.i18n.translate('orders.page.error'),
          retry: () => this.load(),
        };
      case 'ready':
        return rows.length
          ? { state: 'ready', data: rows, more: rows.length < this.total() }
          : {
              state: 'empty',
              heading: this.i18n.translate(pending ? 'orders.page.emptyPending' : 'orders.page.empty'),
              icon: 'package',
            };
    }
  });

  constructor() {
    inject(OrdersRefresh)
      .changed.pipe(takeUntilDestroyed())
      .subscribe(() => this.load());
    this.loadOptions();
  }

  protected onQuery(query: ListQuery): void {
    const wanted = query.filters['segment'];
    this.segment.set(isSegment(wanted) ? wanted : 'open');
    this.filter.set(orderQuery(query));
    this.load();
  }

  protected onAction(key: string): void {
    if (key !== 'export') return;
    const segment = this.segment();
    this.api
      .exportXlsx({ ...this.filter(), ...(segment === 'pending' ? {} : { segment }) })
      .subscribe({
        next: (blob) => downloadBlob(blob, 'bestellungen.xlsx'),
        error: () => this.toast.show(this.i18n.translate('orders.page.exportError'), 'error'),
      });
  }

  /** Read the next rows of the segment. */
  protected more(): void {
    this.load(this.segment() === 'pending' ? this.waiting().length : this.orders().length);
  }

  /** Read the segment with the filter; `offset` above 0 adds the next rows. */
  private load(offset = 0): void {
    this.seq += 1;
    const seq = this.seq;
    const segment = this.segment();
    const query = { ...this.filter(), limit: ORDERS_PAGE_SIZE, offset };
    this.phase.set('loading');
    const fail = (): void => {
      if (seq === this.seq) this.phase.set('error');
    };
    if (segment === 'pending') {
      this.api.pending(query).subscribe({
        next: (page) => {
          if (seq !== this.seq) return;
          this.waiting.update((old) => (offset ? [...old, ...page.items] : page.items));
          this.total.set(page.total);
          this.phase.set('ready');
        },
        error: fail,
      });
      return;
    }
    this.api.page({ ...query, segment }).subscribe({
      next: (page) => {
        if (seq !== this.seq) return;
        this.orders.update((old) => (offset ? [...old, ...page.items] : page.items));
        this.total.set(page.total);
        this.phase.set('ready');
      },
      error: fail,
    });
  }

  /** The options of the chips. A read that fails leaves its chip out. */
  private loadOptions(): void {
    this.budget.listBudgetYears().subscribe({
      next: (years) =>
        this.years.set(
          years.map((y) => ({ value: y.fiscalYearId, label: `${y.budgetName} ${y.display}` })),
        ),
      error: () => undefined,
    });
    this.budget.tree().subscribe({
      next: (tree) => this.centres.set(flattenBudgetOptions(tree)),
      error: () => undefined,
    });
    this.client.listMeetingFilterGremien().subscribe({
      next: (gremien) => this.gremien.set(gremien.map((g) => ({ value: g.id, label: g.name }))),
      error: () => undefined,
    });
  }

  private money(value: unknown): string {
    return formatMoney(value, this.i18n.formatLocale());
  }

  private row(order: Order): ListRow {
    const price = shownPrice(order);
    return {
      id: order.id,
      title: order.title,
      icon: 'package',
      meta: [order.applicationTitle, order.supplier].filter((part): part is string => !!part),
      status: {
        label: this.i18n.translate(ORDER_STATUS_LABEL[order.status]),
        kind: ORDER_STATUS_KIND[order.status],
      },
      trailing: this.money(price.amount) || undefined,
      link: { commands: ['/orders', order.id] },
    };
  }

  private pendingRow(application: PendingApplication): ListRow {
    return {
      id: application.id,
      title: application.title || this.i18n.translate('applications.list.untitled'),
      icon: 'file',
      meta: application.gremiumName ? [application.gremiumName] : [],
      trailing: this.money(application.approvedAmount) || undefined,
      link: this.canManage()
        ? { commands: ['/orders', 'new'], query: { application: application.id } }
        : { commands: ['/applications', application.id] },
    };
  }
}
