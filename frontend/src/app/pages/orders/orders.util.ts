import type { Order, OrderInput, OrderKind } from '@core/api/orders.service';
import type { TranslationKey } from '@core/i18n/translations';
import { dayMonthYear } from '@shared/date-format';
import { formatMoney, moneyNumber } from '@shared/format-money';
import {
  type CostPosition,
  normalizePositions,
  positionValue,
  preferredOffer,
} from '@shared/forms/positions';

export const ORDER_KIND_LABEL: Readonly<Record<OrderKind, TranslationKey>> = {
  order: 'orders.kind.order',
  outlay: 'orders.kind.outlay',
};

/** A position of the Kostenaufstellung that a Bestellung can name. */
export type OrderPosition = CostPosition & { readonly id: string };

/**
 * The positions in the answers of an Antrag. The key of a positions field differs from
 * form to form, so the positions are found by their shape: a list with a row that holds
 * `offers`, as the server finds them.
 */
export function orderPositions(data: Readonly<Record<string, unknown>> | null | undefined): readonly OrderPosition[] {
  return Object.values(data ?? {})
    .filter(
      (value): value is unknown[] =>
        Array.isArray(value) &&
        value.some((row) => typeof row === 'object' && row !== null && 'offers' in row),
    )
    .flatMap((value) => normalizePositions(value))
    .filter((p): p is OrderPosition => !!p.id);
}

/** The price that a row shows: the real price, else the planned one. */
export function shownPrice(order: Pick<Order, 'actualAmount' | 'plannedAmount'>): {
  readonly amount: number | null;
  readonly planned: boolean;
} {
  const actual = moneyNumber(order.actualAmount);
  return actual !== null
    ? { amount: actual, planned: false }
    : { amount: moneyNumber(order.plannedAmount), planned: true };
}

/** The real price minus the planned price in euro, or null when one is missing or both are equal. */
export function priceDifference(order: Pick<Order, 'actualAmount' | 'plannedAmount'>): number | null {
  const actual = moneyNumber(order.actualAmount);
  const planned = moneyNumber(order.plannedAmount);
  if (actual === null || planned === null) return null;
  const cents = Math.round(actual * 100) - Math.round(planned * 100);
  return cents === 0 ? null : cents / 100;
}

/** The first `http://` or `https://` address in a text, or null. */
export function firstAddress(text: string): string | null {
  return /https?:\/\/[^\s<>"']+/i.exec(text)?.[0] ?? null;
}

/**
 * What the form fills from the picked positions: the sum of their preferred offers, and
 * with exactly one position the first address in the text of its preferred offer.
 */
export function positionPrefill(picked: readonly OrderPosition[]): {
  readonly plannedAmount: number | null;
  readonly url: string;
} {
  const cents = picked.reduce((sum, p) => sum + Math.round(positionValue(p) * 100), 0);
  const only = picked.length === 1 ? preferredOffer(picked[0]) : undefined;
  return {
    plannedAmount: picked.length ? cents / 100 : null,
    url: only ? (firstAddress(only.label) ?? '') : '',
  };
}

/**
 * The ids of the positions that another Bestellung holds whose status is not in the phase
 * `void` (spec 003036): `isVoid` reads the phase of a status key.
 */
export function takenPositions(
  orders: readonly Order[],
  selfId: string | null,
  isVoid: (status: string) => boolean,
): ReadonlySet<string> {
  return new Set(
    orders
      .filter((o) => o.id !== selfId && !isVoid(o.status))
      .flatMap((o) => o.positionIds ?? []),
  );
}

/** An amount of the form as the decimal text of the API, or null for an empty field. */
export function amountText(value: unknown): string | null {
  const n = moneyNumber(typeof value === 'number' ? value : String(value ?? ''));
  return n === null ? null : n.toFixed(2);
}

const text = (value: unknown): string | null => String(value ?? '').trim() || null;

/** The body of a create or a change from the value of the form and the picked buyer. */
export function orderBody(value: Readonly<Record<string, unknown>>, buyerId: string | null): OrderInput {
  return {
    title: String(value['title'] ?? '').trim(),
    kind: value['kind'] === 'outlay' ? 'outlay' : 'order',
    supplier: text(value['supplier']),
    url: text(value['url']),
    orderNumber: text(value['orderNumber']),
    positionIds: Array.isArray(value['positionIds']) ? value['positionIds'].map(String) : [],
    plannedAmount: amountText(value['plannedAmount']),
    actualAmount: amountText(value['actualAmount']),
    orderedOn: text(value['orderedOn']),
    deliveredOn: text(value['deliveredOn']),
    buyerId,
    buyerName: buyerId ? null : text(value['buyerName']),
    note: text(value['note']),
  };
}

/** The value of the form for a Bestellung, or the empty form. */
export function orderFormValue(order: Order | null): Record<string, unknown> {
  return {
    title: order?.title ?? '',
    kind: order?.kind ?? 'order',
    supplier: order?.supplier ?? '',
    url: order?.url ?? '',
    orderNumber: order?.orderNumber ?? '',
    positionIds: [...(order?.positionIds ?? [])],
    plannedAmount: moneyNumber(order?.plannedAmount),
    actualAmount: moneyNumber(order?.actualAmount),
    orderedOn: order?.orderedOn ?? '',
    deliveredOn: order?.deliveredOn ?? '',
    buyerName: order?.buyerId ? '' : (order?.buyerName ?? ''),
    note: order?.note ?? '',
  };
}

/** The key of a menu item that sets a status: the prefix and the key of the status. */
export const STATUS_ACTION = 'status:' as const;

export type OrderAction = 'invoiceLink' | 'invoiceNew' | 'booking' | 'edit' | 'delete';

/**
 * The marks of a Bestellung: "Rechnung offen" or "Rechnung bezahlt" from its invoice, and
 * "Verbucht" with the booked amount when it has a booking.
 */
export function orderMarks(
  order: Pick<Order, 'invoiceStatus' | 'bookedAmount'>,
  locale: string,
  currency: string | null,
  t: (key: TranslationKey, params?: Record<string, string>) => string,
): readonly string[] {
  const booked = moneyNumber(order.bookedAmount);
  return [
    ...(order.invoiceStatus === 'open' ? [t('orders.mark.invoiceOpen')] : []),
    ...(order.invoiceStatus === 'paid' ? [t('orders.mark.invoicePaid')] : []),
    ...(booked
      ? [t('orders.mark.booked', { amount: formatMoney(booked, locale, { currency }) })]
      : []),
  ];
}

/**
 * The amount of a new booking for a Bestellung: the real price, else the planned one,
 * minus the amounts already booked, and at least 0.
 */
export function bookingRest(
  order: Pick<Order, 'actualAmount' | 'plannedAmount' | 'bookedAmount'>,
): number {
  const price = shownPrice(order).amount ?? 0;
  const booked = moneyNumber(order.bookedAmount) ?? 0;
  return Math.max(0, (Math.round(price * 100) - Math.round(booked * 100)) / 100);
}

/** The payee of a booking for a Bestellung: the buyer of an Auslage, else the Händler. */
export function bookingPayee(order: Pick<Order, 'kind' | 'buyerLabel' | 'supplier'>): string {
  return (order.kind === 'outlay' ? order.buyerLabel : order.supplier) ?? '';
}

/**
 * One value of a Bestellung in the read view. `href` makes the value a link, `mono` shows
 * a number, an amount or a date in the mono face.
 */
export interface OrderFact {
  readonly label: string;
  readonly value: string;
  readonly href?: string;
  readonly mono?: boolean;
  /** The value takes a row of its own: a link, a list or a free text. */
  readonly wide?: boolean;
}

/**
 * The values in rows as the fields of an Antrag show: two short values side by side, a
 * wide value alone. A short value without a partner stands alone too.
 */
export function factRows(facts: readonly OrderFact[]): readonly (readonly OrderFact[])[] {
  return facts.reduce<readonly (readonly OrderFact[])[]>((rows, fact) => {
    const last = rows.at(-1);
    return last && last.length === 1 && !last[0].wide && !fact.wide
      ? [...rows.slice(0, -1), [last[0], fact]]
      : [...rows, [fact]];
  }, []);
}

/**
 * The values of a Bestellung for a person who reads it, in the order of the form. A value
 * that the Bestellung does not have is left out.
 */
export function orderFacts(
  order: Order,
  positions: readonly OrderPosition[],
  locale: string,
  currency: string | null,
  t: (key: TranslationKey) => string,
  statusName: (key: string) => string,
): readonly OrderFact[] {
  const money = (value: string | null | undefined): string =>
    formatMoney(value, locale, { currency });
  const labels = new Map(positions.map((p) => [p.id, p.label]));
  const picked = (order.positionIds ?? [])
    .map((id) => labels.get(id) ?? t('orders.position.removed'))
    .join(', ');
  const facts: readonly OrderFact[] = [
    { label: t('orders.field.number'), value: order.number, mono: true },
    { label: t('orders.field.kind'), value: t(ORDER_KIND_LABEL[order.kind]) },
    { label: t('orders.field.status'), value: statusName(order.status) },
    { label: t('orders.field.supplier'), value: order.supplier ?? '' },
    { label: t('orders.field.positions'), value: picked, wide: true },
    { label: t('orders.field.url'), value: order.url ?? '', href: order.url ?? undefined, wide: true },
    { label: t('orders.field.planned'), value: money(order.plannedAmount), mono: true },
    { label: t('orders.field.actual'), value: money(order.actualAmount), mono: true },
    { label: t('orders.field.orderNumber'), value: order.orderNumber ?? '', mono: true },
    { label: t('orders.field.orderedOn'), value: dayMonthYear(order.orderedOn, locale), mono: true },
    { label: t('orders.field.deliveredOn'), value: dayMonthYear(order.deliveredOn, locale), mono: true },
    { label: t('orders.field.buyer'), value: order.buyerLabel ?? '' },
    { label: t('orders.field.note'), value: order.note ?? '', wide: true },
    {
      label: t('orders.field.booked'),
      value: money(moneyNumber(order.bookedAmount) ? order.bookedAmount : null),
      mono: true,
    },
  ];
  return facts.filter((fact) => fact.value !== '');
}
