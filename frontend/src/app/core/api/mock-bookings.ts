import type {
  BudgetTransfer,
  Expense,
  ExpensePage,
  Invoice,
  InvoiceBooking,
  InvoiceParseResult,
  InvoicePage,
  TransferPage,
} from '../../pages/budget/budget-tree.api';
import { MOCK_BUDGET_TREE } from './mock-budget';

/**
 * Demo bookings, transfers and invoices for the mock backend (`?mock=1`). Dev and tests
 * only.
 *
 * The rows use the cost centres of `mock-budget.ts`, so the swatches and names of the
 * bookings page match the budget page. They show every case of the two pages: an
 * expense and an income, a booking bound to an application, a booking with
 * sub-bookings, a linked invoice with and without a receipt, and an invoice with more
 * than one booking.
 */

const FY = 'f1000000-0000-0000-0000-000000000001';
const cc = (suffix: string): string => `b1000000-0000-0000-0000-0000000000${suffix}`;

interface NodeInfo {
  pathKey: string;
  name: string;
}

/** The path and the name of every cost centre of the demo tree, by id. */
function nodeIndex(): Map<string, NodeInfo> {
  const out = new Map<string, NodeInfo>();
  const walk = (nodes: typeof MOCK_BUDGET_TREE): void => {
    for (const n of nodes) {
      out.set(n.id, { pathKey: n.pathKey, name: n.name });
      walk(n.children);
    }
  };
  walk(MOCK_BUDGET_TREE);
  return out;
}

const NODES = nodeIndex();

/** The path and the name of a demo cost centre; empty for an unknown id. */
function node(id: string): NodeInfo {
  return NODES.get(id) ?? { pathKey: '', name: '' };
}

/** The ids of a cost centre and all cost centres below it. */
function subtree(id: string): Set<string> {
  const ids = new Set<string>();
  const add = (nodes: typeof MOCK_BUDGET_TREE, inside: boolean): void => {
    for (const n of nodes) {
      const hit = inside || n.id === id;
      if (hit) ids.add(n.id);
      add(n.children, hit);
    }
  };
  add(MOCK_BUDGET_TREE, false);
  return ids;
}

const INV = {
  tools: 'd1000000-0000-0000-0000-000000000001',
  print: 'd1000000-0000-0000-0000-000000000002',
  sport: 'd1000000-0000-0000-0000-000000000003',
  stage: 'd1000000-0000-0000-0000-000000000004',
  copy: 'd1000000-0000-0000-0000-000000000005',
};

type Row = Partial<Expense> & Pick<Expense, 'id' | 'description' | 'amount' | 'budgetId'>;

function expense(row: Row): Expense {
  return {
    pathKey: node(row.budgetId).pathKey,
    fiscalYearId: FY,
    kind: 'expense',
    currency: 'EUR',
    applicationId: null,
    applicationTitle: null,
    transferId: null,
    actor: null,
    actorName: 'Demo Mitglied',
    invoiceDate: null,
    paymentDate: null,
    correspondent: null,
    note: null,
    referenceNumber: null,
    paymentMethod: 'ueberweisung',
    category: null,
    invoiceId: null,
    invoiceNumber: null,
    parentExpenseId: null,
    childCount: 0,
    createdAt: '2026-09-01T10:00:00Z',
    ...row,
  };
}

const PARENT = 'e1000000-0000-0000-0000-000000000002';

const EXPENSES: Expense[] = [
  expense({
    id: 'e1000000-0000-0000-0000-000000000001',
    description: 'Werkzeugsatz für die Projektwerkstatt',
    amount: '480.00',
    budgetId: cc('21'),
    invoiceDate: '2026-09-21',
    paymentDate: '2026-09-28',
    correspondent: 'Werkzeughandel Neckar',
    invoiceId: INV.tools,
    invoiceNumber: 'WN-2026-0412',
    referenceNumber: 'WN-2026-0412',
    category: 'Ausstattung',
  }),
  expense({
    id: PARENT,
    description: 'Siebdruckrahmen und Zubehör',
    amount: '1100.00',
    budgetId: cc('24'),
    applicationId: 'c1000000-0000-0000-0000-000000000003',
    applicationTitle: 'Siebdruckrahmen für die Werkstatt',
    invoiceDate: '2026-09-24',
    paymentDate: '2026-09-25',
    correspondent: 'Druckbedarf Süd GmbH',
    childCount: 2,
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000003',
    kind: 'income',
    description: 'Rückzahlung Pfand Sommerfest',
    amount: '210.00',
    budgetId: cc('12'),
    paymentDate: '2026-09-17',
    correspondent: 'Getränkelieferant am Campus',
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000004',
    description: 'Druck Semesterprogramm, 2.000 Stück auf Recyclingpapier mit Falzung',
    amount: '740.00',
    budgetId: cc('11'),
    invoiceDate: '2026-09-11',
    paymentDate: '2026-09-14',
    correspondent: 'Druckerei am Markt',
    invoiceId: INV.print,
    invoiceNumber: 'DM-44721',
    referenceNumber: 'DM-44721',
    category: 'Druck',
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000005',
    description: 'Lötstationen für die Projektwerkstatt',
    amount: '640.00',
    budgetId: cc('21'),
    applicationId: 'c1000000-0000-0000-0000-000000000001',
    applicationTitle: 'Lötstation für die Projektwerkstatt',
    invoiceDate: '2026-09-02',
    paymentDate: '2026-09-07',
    correspondent: 'Elektronik Versand',
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000006',
    description: 'Hallenmiete Turnier',
    amount: '200.00',
    budgetId: cc('30'),
    invoiceDate: '2026-08-28',
    paymentDate: '2026-09-03',
    correspondent: 'Sportstätten der Stadt',
    invoiceId: INV.sport,
    invoiceNumber: 'SP-88213',
    paymentMethod: 'lastschrift',
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000007',
    description: 'Schiedsrichter Turnier',
    amount: '157.00',
    budgetId: cc('30'),
    invoiceDate: '2026-08-28',
    paymentDate: '2026-09-03',
    correspondent: 'Sportstätten der Stadt',
    invoiceId: INV.sport,
    invoiceNumber: 'SP-88213',
    paymentMethod: 'bar',
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000009',
    description: 'Anzahlung Bühnentechnik Sommerfest',
    amount: '900.00',
    budgetId: cc('12'),
    invoiceDate: '2026-09-24',
    paymentDate: '2026-09-26',
    correspondent: 'Bühnentechnik Verleih',
    invoiceId: INV.stage,
    invoiceNumber: 'BT-2026-118',
    referenceNumber: 'BT-2026-118',
    category: 'Anschaffung',
    note: 'Anzahlung, der Rest folgt bei Lieferung.',
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000008',
    description: 'Exkursion Busanmietung',
    amount: '1350.00',
    budgetId: cc('22'),
    invoiceDate: '2026-08-14',
    paymentDate: '2026-08-20',
    correspondent: 'Reisedienst Alb',
  }),
];

const SUB_BOOKINGS: Expense[] = [
  expense({
    id: 'e1000000-0000-0000-0000-000000000021',
    description: 'Rahmen 60 × 90 cm',
    amount: '880.00',
    budgetId: cc('24'),
    parentExpenseId: PARENT,
    paymentDate: '2026-09-25',
  }),
  expense({
    id: 'e1000000-0000-0000-0000-000000000022',
    description: 'Rakel und Farbe',
    amount: '220.00',
    budgetId: cc('24'),
    parentExpenseId: PARENT,
    paymentDate: '2026-09-25',
  }),
];

const TRANSFERS: BudgetTransfer[] = [
  {
    transferId: 't1000000-0000-0000-0000-000000000001',
    expenseId: 'e1000000-0000-0000-0000-000000000031',
    incomeId: 'e1000000-0000-0000-0000-000000000032',
    fromBudgetId: cc('40'),
    fromPathKey: node(cc('40')).pathKey,
    toBudgetId: cc('12'),
    toPathKey: node(cc('12')).pathKey,
    fiscalYearId: FY,
    amount: '1500.00',
    currency: 'EUR',
    description: 'Aufstockung Kultur aus der Rücklage',
    note: 'Beschluss des Haushaltsausschusses',
    invoiceDate: null,
    paymentDate: '2026-09-10',
    actor: null,
    actorName: 'Demo Mitglied',
    createdAt: '2026-09-10T09:00:00Z',
  },
];

function invoiceBooking(e: Expense): InvoiceBooking {
  return {
    id: e.id,
    budgetId: e.budgetId,
    pathKey: node(e.budgetId).pathKey,
    budgetName: node(e.budgetId).name,
    fiscalYearId: e.fiscalYearId,
    kind: e.kind,
    amount: e.amount,
    description: e.description,
    paymentDate: e.paymentDate,
    parentExpenseId: e.parentExpenseId,
    createdAt: e.createdAt,
  };
}

type InvoiceRow = Partial<Invoice> & Pick<Invoice, 'id' | 'grossAmount'>;

function invoice(row: InvoiceRow): Invoice {
  return {
    number: null,
    issueDate: null,
    dueDate: null,
    supplier: null,
    netAmount: null,
    taxAmount: null,
    currency: 'EUR',
    note: null,
    status: 'open',
    fileName: null,
    hasFile: false,
    actor: null,
    createdAt: '2026-09-01T10:00:00Z',
    linkedBookings: EXPENSES.filter((e) => e.invoiceId === row.id).map(invoiceBooking),
    ...row,
  };
}

const INVOICES: Invoice[] = [
  invoice({
    id: INV.copy,
    number: 'K-2026-311',
    issueDate: '2026-09-29',
    dueDate: '2026-10-13',
    supplier: 'Copyshop am Campus',
    netAmount: '156.64',
    taxAmount: '29.76',
    grossAmount: '186.40',
    status: 'open',
  }),
  invoice({
    id: INV.stage,
    number: 'BT-2026-118',
    issueDate: '2026-09-24',
    dueDate: '2026-10-08',
    supplier: 'Bühnentechnik Verleih',
    netAmount: '2428.57',
    taxAmount: '461.43',
    grossAmount: '2890.00',
    status: 'open',
    note: 'Anzahlung 900,00 € geleistet, Rest bei Lieferung.',
    fileName: 'BT-2026-118.pdf',
    hasFile: true,
  }),
  invoice({
    id: INV.tools,
    number: 'WN-2026-0412',
    issueDate: '2026-09-21',
    dueDate: '2026-10-05',
    supplier: 'Werkzeughandel Neckar',
    netAmount: '403.36',
    taxAmount: '76.64',
    grossAmount: '480.00',
    status: 'paid',
    fileName: 'WN-2026-0412.pdf',
    hasFile: true,
  }),
  invoice({
    id: INV.print,
    number: 'DM-44721',
    issueDate: '2026-09-11',
    dueDate: '2026-09-25',
    supplier: 'Druckerei am Markt',
    netAmount: '621.85',
    taxAmount: '118.15',
    grossAmount: '740.00',
    status: 'paid',
  }),
  invoice({
    id: INV.sport,
    number: 'SP-88213',
    issueDate: '2026-08-28',
    dueDate: '2026-09-11',
    supplier: 'Sportstätten der Stadt',
    netAmount: '300.00',
    taxAmount: '57.00',
    grossAmount: '357.00',
    status: 'paid',
    fileName: 'SP-88213.pdf',
    hasFile: true,
  }),
];

function page<T>(rows: T[], params: URLSearchParams): { items: T[]; total: number; limit: number; offset: number } {
  const limit = Number(params.get('limit') ?? 20);
  const offset = Number(params.get('offset') ?? 0);
  return { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset };
}

function matches(text: string | null | undefined, q: string): boolean {
  return (text ?? '').toLowerCase().includes(q);
}

/** GET /expenses: the filters the page sends, as far as the demo needs them. */
export function mockExpenses(params: URLSearchParams): ExpensePage {
  const budget = params.get('budget');
  const ids = budget ? subtree(budget) : null;
  const kind = params.get('kind');
  const id = params.get('id');
  const q = (params.get('q') ?? '').trim().toLowerCase();
  const rows = EXPENSES.filter(
    (e) =>
      (!ids || ids.has(e.budgetId)) &&
      (!kind || e.kind === kind) &&
      (!id || e.id === id) &&
      (!q || matches(e.description, q) || matches(e.correspondent, q)),
  );
  return page(rows, params);
}

/** GET /budget-expenses/{id}/sub-bookings. */
export function mockSubBookings(parentId: string): Expense[] {
  return SUB_BOOKINGS.filter((e) => e.parentExpenseId === parentId);
}

/** GET /budget-transfers. */
export function mockTransfers(params: URLSearchParams): TransferPage {
  return page(TRANSFERS, params);
}

/**
 * GET /invoices: search, the exact invoice of a deep link, the segment (`status` plus
 * `booked`) and the counts of the segments under the other filters.
 */
export function mockInvoices(params: URLSearchParams): InvoicePage {
  const status = params.get('status');
  const booked = params.get('booked');
  const id = params.get('id');
  const q = (params.get('q') ?? '').trim().toLowerCase();
  const hasBooking = (i: Invoice): boolean => (i.linkedBookings?.length ?? 0) > 0;
  const base = INVOICES.filter(
    (i) => (!id || i.id === id) && (!q || matches(i.number, q) || matches(i.supplier, q)),
  );
  const rows = base.filter(
    (i) =>
      (!status || i.status === status) &&
      (booked === null || hasBooking(i) === (booked === 'true')),
  );
  const open = base.filter((i) => i.status === 'open');
  return {
    ...page(rows, params),
    counts: {
      all: base.length,
      inbox: open.filter((i) => !hasBooking(i)).length,
      booked: open.filter(hasBooking).length,
      paid: base.filter((i) => i.status === 'paid').length,
    },
  };
}

/** GET /invoices/{id}. */
export function mockInvoice(id: string): Invoice | null {
  return INVOICES.find((i) => i.id === id) ?? null;
}

/**
 * POST /invoices/parse. The demo reads every PDF as the invoice of the tools booking,
 * which exists already, so the review dialog shows its duplicate warning.
 */
export function mockParseInvoice(fileName: string): InvoiceParseResult {
  const known = INVOICES.find((i) => i.id === INV.tools) as Invoice;
  return {
    number: known.number,
    issueDate: known.issueDate,
    dueDate: known.dueDate,
    supplier: known.supplier,
    netAmount: known.netAmount,
    taxAmount: known.taxAmount,
    grossAmount: known.grossAmount,
    currency: 'EUR',
    fileToken: 'mock-file-token',
    fileName,
    fileMime: 'application/pdf',
    duplicate: true,
  };
}
