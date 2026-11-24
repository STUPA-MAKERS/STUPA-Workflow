import { of } from 'rxjs';
import { type Order, type OrderList, OrdersApiService } from '@core/api/orders.service';

/** A planned Bestellung as a member reads it; `over` replaces fields. */
export function order(over: Partial<Order> = {}): Order {
  return {
    id: 'o-1',
    number: 'B-7K3QX9MD',
    title: 'Beamer',
    kind: 'order',
    status: 'planned',
    orderedOn: null,
    deliveredOn: null,
    supplier: 'Technikhaus',
    url: null,
    orderNumber: null,
    positionIds: [],
    plannedAmount: '100.00',
    actualAmount: null,
    buyerId: null,
    buyerName: null,
    buyerLabel: null,
    note: null,
    version: 1,
    ...over,
  };
}

/** The answer for an Antrag without a Bestellung and without a right. */
export const NO_ORDER_LIST: OrderList = {
  items: [],
  total: null,
  approvedAmount: null,
  overBy: null,
  canManage: false,
  canCreate: false,
};

/**
 * A provider for a spec that renders the detail of an Antrag and does not test its
 * Bestellungen: the section reads an empty list and sends no request.
 */
export const NO_ORDERS = {
  provide: OrdersApiService,
  useValue: { list: () => of(NO_ORDER_LIST) },
};
