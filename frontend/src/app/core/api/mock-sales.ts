import type {
  EventSales,
  FailedBooking,
  MollieConnection,
  PretixConnection,
  PretixEventOption,
  SyncResult,
} from './sales.service';

/** The pretix connection of the mock: connected, both parts on. */
export const MOCK_PRETIX: PretixConnection = {
  baseUrl: 'https://pretix.eu',
  organizer: 'stupa',
  tokenSet: true,
  showSales: true,
  bookIncome: true,
  allowedHosts: ['pretix.eu'],
};

/** The Mollie connection of the mock, with both Kostenstellen. */
export const MOCK_MOLLIE: MollieConnection = {
  tokenSet: true,
  organization: 'Studierendenschaft Hochschule Reutlingen',
  feeBudgetId: null,
  unassignedBudgetId: null,
  readOkAt: '2026-11-28T06:47:00Z',
  readError: null,
};

export const MOCK_PRETIX_FAILED: readonly FailedBooking[] = [
  { source: 'order', key: 'ABC12', error: 'fiscal_year_closed', at: '2026-11-27T21:15:00Z' },
];

export const MOCK_PRETIX_EVENTS: readonly PretixEventOption[] = [
  { slug: 'semesterparty-ws26', name: 'Semesterparty WS 26/27', dateFrom: '2026-12-11T20:00:00Z', taken: false },
  { slug: 'erstiparty-ws26', name: 'Erstiparty WS 26/27', dateFrom: '2026-10-09T20:00:00Z', taken: true },
];

/** The section "Verkauf" of each mock Event. */
export const MOCK_EVENT_SALES: EventSales = {
  connected: true,
  link: {
    slug: 'semesterparty-ws26',
    name: 'Semesterparty WS 26/27',
    dateFrom: '2026-12-11T20:00:00Z',
    incomeBudgetId: null,
    incomeBudgetName: '2.4 Veranstaltungen',
  },
  pretix: {
    products: [
      { name: 'Vorverkauf', paid: 412, pending: 9, cancelled: 6 },
      { name: 'Abendkasse', paid: 0, pending: 0, cancelled: 0 },
    ],
    paidSum: '3708.00',
    refundSum: '54.00',
    quotas: [{ name: 'Einlass', available: 79 }],
    readAt: '2026-11-28T06:47:00Z',
  },
  mollie: {
    paid: '3708.00',
    refunds: '54.00',
    chargebacks: '0.00',
    fees: '118.37',
    paidOut: '3535.63',
    settlements: [{ reference: '1234567.2611.01', settledAt: '2026-11-26T08:00:00Z', amount: '2410.12' }],
    readAt: '2026-11-28T06:47:00Z',
  },
  linkable: true,
  incomeEditable: true,
  incomeOn: true,
  refreshable: true,
};

const NONE_FAILED: SyncResult = { booked: 0, failures: [] };

/** The answer of the mock API to a call of the pretix and Mollie integrations, or undefined. */
export function mockSalesBody(method: string, p: string): unknown {
  const get = method === 'GET';
  if (get && p.endsWith('/admin/pretix')) return MOCK_PRETIX;
  if (get && p.endsWith('/admin/pretix/failed-bookings')) return { items: MOCK_PRETIX_FAILED };
  if (get && p.endsWith('/admin/mollie')) return MOCK_MOLLIE;
  if (get && p.endsWith('/admin/mollie/failed-bookings')) return { items: [] };
  if (get && p.endsWith('/pretix/events')) return MOCK_PRETIX_EVENTS;
  if (get && /\/events\/[^/]+\/sales$/.test(p)) return MOCK_EVENT_SALES;
  if (get && p.endsWith('/sales-sync')) return { pretix: true, mollie: true };
  if (method === 'POST' && /\/admin\/(pretix|mollie)\/test$/.test(p)) return { ok: true, error: null, name: MOCK_MOLLIE.organization };
  if (method === 'POST' && (p.endsWith('/sales-sync') || p.endsWith('/sales/refresh'))) return NONE_FAILED;
  return undefined;
}
