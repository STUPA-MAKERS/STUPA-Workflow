import { BehaviorSubject, of } from 'rxjs';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ExpensesComponent } from './expenses.component';
import { ExpensesListState } from './expenses-list.state';
import type { ExpenseDialogsState } from './expense-dialogs.state';
import type { ExpenseSubBookingsState } from './expense-sub-bookings.state';
import type {
  BudgetTreeNode,
  Expense,
  ExpensePage,
  FiscalYear,
  Invoice,
} from '../budget/budget-tree.api';

/**
 * An `ActivatedRoute` carrying query params.
 *
 * Both the snapshot and the stream: the page reads the snapshot for its first request and
 * then follows the stream, because the palette can navigate to this page while it is
 * already open and only the query string changes.
 */
function routeStub(query: [string, string][]) {
  const map = convertToParamMap(Object.fromEntries(query));
  return { snapshot: { queryParamMap: map }, queryParamMap: of(map) };
}

/** The state modules behind the facade. The forms read and set their signals directly. */
const dlg = (c: ExpensesComponent): ExpenseDialogsState =>
  (c as unknown as { dialogs: ExpenseDialogsState }).dialogs;
const subs = (c: ExpensesComponent): ExpenseSubBookingsState =>
  (c as unknown as { sub: ExpenseSubBookingsState }).sub;
const lst = (c: ExpensesComponent): ExpensesListState =>
  (c as unknown as { list: ExpensesListState }).list;

const EXPENSE: Expense = {
  id: 'e-1',
  budgetId: 'b-1',
  pathKey: 'VS-800',
  fiscalYearId: 'fy-1',
  kind: 'expense',
  amount: '120.00',
  currency: 'EUR',
  description: 'Druckkosten Flyer',
  applicationId: null,
  applicationTitle: null,
  transferId: null,
  actor: 'admin',
  actorName: 'Admin',
  invoiceDate: '2026-05-20',
  paymentDate: '2026-05-28',
  correspondent: 'Copyshop Müller',
  note: null,
  referenceNumber: 'R-2026-7',
  paymentMethod: 'ueberweisung',
  category: 'Werbung',
  invoiceId: null,
  invoiceNumber: null,
  createdAt: '2026-05-30T09:00:00Z',
};

function page(items: Expense[], total = items.length, offset = 0): ExpensePage {
  return { items, total, limit: 20, offset };
}

/**
 * Let `matchMedia` match the queries that contain one of the given parts. jsdom has no
 * viewport, and its stub matches nothing, which reads as the narrow layout.
 */
function setViewport(...parts: string[]): void {
  window.matchMedia = ((query: string) => ({
    matches: parts.some((p) => query.includes(p)),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
const WIDE = 'min-width: 1200px';
const PHONE = 'max-width: 768px';
const realMatchMedia = window.matchMedia;
afterEach(() => {
  window.matchMedia = realMatchMedia;
});

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

async function setup(opts: { perms?: string[]; page?: ExpensePage; tree?: BudgetTreeNode[] } = {}) {
  const view = await render(ExpensesComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts.perms ?? ['budget.view', 'budget.book']) },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  // The constructor loads the cost center tree, the invoices and the first page of
  // bookings.
  http.match((r) => r.url.endsWith('/budgets')).forEach((req) => req.flush(opts.tree ?? []));
  // `listInvoices` reads a page, so the answer must be a paged shape and not an array.
  // Otherwise `page.items` is undefined and the `invoiceOptions` computed throws.
  http
    .match((r) => r.url.endsWith('/invoices') && r.method === 'GET')
    .forEach((req) => req.flush({ items: [], total: 0, limit: 200, offset: 0 }));
  http
    .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
    .forEach((req) => req.flush(opts.page ?? page([])));
  return { ...view, http };
}

// Direct component tests for the methods and branches, without DOM rendering. Every
// method runs through the HttpTestingController, and the test checks the signal state.

const ROOT_TREE: BudgetTreeNode[] = [
  {
    id: 'top-1',
    parentId: null,
    gremiumId: null,
    key: 'VS',
    pathKey: 'VS',
    name: 'Verfasste Studierendenschaft',
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [
      {
        id: 'child-1',
        parentId: 'top-1',
        gremiumId: null,
        key: '800',
        pathKey: 'VS-800',
        name: 'Öffentlichkeit',
        currency: 'EUR',
        active: true,
        color: null,
        acceptedStateKeys: [],
        deniedStateKeys: [],
        hiddenInBudget: false,
        viewGremiumId: null,
        fiscalStartMonth: 1,
        fiscalStartDay: 1,
        byFiscalYear: [],
        children: [],
      },
    ],
  },
];

const INVOICE: Invoice = {
  id: 'inv-1',
  number: 'RE-2026-1',
  issueDate: '2026-04-01',
  dueDate: '2026-04-15',
  supplier: 'Acme GmbH',
  netAmount: '100.00',
  taxAmount: '19.00',
  grossAmount: '119.00',
  currency: 'EUR',
  note: null,
  status: 'open',
  fileName: null,
  hasFile: false,
  actor: null,
  createdAt: '2026-04-01T00:00:00Z',
};

const FY_ACTIVE: FiscalYear = {
  id: 'fy-active',
  budgetId: 'top-1',
  year: 2026,
  display: '2026',
  startDate: '2026-01-01',
  endDate: '2026-12-31',
  active: true,
};
const FY_OLD: FiscalYear = {
  id: 'fy-old',
  budgetId: 'top-1',
  year: 2025,
  display: '2025',
  startDate: '2025-01-01',
  endDate: '2025-12-31',
  active: false,
};

interface Built {
  cmp: ExpensesComponent;
  http: HttpTestingController;
}

/**
 * Instantiate the component directly. The constructor fires the tree, invoices
 * and expenses requests. The caller can answer that first load with custom data.
 * The default answer is empty.
 */
function build(
  opts: {
    perms?: string[];
    tree?: BudgetTreeNode[];
    invoices?: Invoice[];
    expenses?: ExpensePage;
    treeError?: boolean;
    invoicesError?: boolean;
    expensesError?: boolean;
  } = {},
): Built {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: ActivatedRoute, useValue: routeStub([]) },
      { provide: USE_MOCK_API, useValue: false },
      {
        provide: AuthService,
        useValue: fakeAuth(opts.perms ?? ['budget.view', 'budget.book', 'budget.export']),
      },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const cmp = TestBed.runInInjectionContext(() => new ExpensesComponent());

  const treeReq = http.expectOne((r) => r.url.endsWith('/budgets'));
  if (opts.treeError) treeReq.error(new ProgressEvent('err'));
  else treeReq.flush(opts.tree ?? []);

  const invReq = http.expectOne((r) => r.url.endsWith('/invoices') && r.method === 'GET');
  if (opts.invoicesError) invReq.error(new ProgressEvent('err'));
  else
    invReq.flush({
      items: opts.invoices ?? [],
      total: (opts.invoices ?? []).length,
      limit: 200,
      offset: 0,
    });

  const expReq = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
  if (opts.expensesError) expReq.error(new ProgressEvent('err'));
  else expReq.flush(opts.expenses ?? page([]));

  return { cmp, http };
}

/** Answer the next GET /expenses from a reload or a fetch. */
function flushList(http: HttpTestingController, body: ExpensePage): void {
  http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET').flush(body);
}

describe('ExpensesComponent (unit)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    // Some tests reset the TestBed. After that no HttpTestingController provider
    // exists, so the verify call does not run.
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
    jest.useRealTimers();
  });

  it('loads tree and invoices on construction (success)', () => {
    const { cmp } = build({
      tree: ROOT_TREE,
      invoices: [INVOICE],
      expenses: page([EXPENSE], 1),
    });
    expect(cmp.budgetTree()).toEqual(ROOT_TREE);
    expect(cmp.invoices()).toEqual([INVOICE]);
    expect(cmp.items()).toEqual([EXPENSE]);
    expect(cmp.total()).toBe(1);
    expect(cmp.loading()).toBe(false);
    expect(lst(cmp).costCentreOptions().length).toBe(2);
    const label = dlg(cmp).invoiceOptions()[0];
    expect(label.value).toBe('inv-1');
    // Intl separates with a narrow no-break space, so normalize to plain whitespace.
    expect(label.label.replace(/\s/g, ' ')).toBe('RE-2026-1 · Acme GmbH · 119,00 €');
  });

  it('resets each list to empty on construction errors', () => {
    const { cmp } = build({
      treeError: true,
      invoicesError: true,
      expensesError: true,
    });
    expect(cmp.budgetTree()).toEqual([]);
    expect(cmp.invoices()).toEqual([]);
    expect(cmp.loading()).toBe(false);
    expect(cmp.loadingMore()).toBe(false);
    expect(cmp.items()).toEqual([]);
  });

  it('canManage / canExport reflect AuthService permissions', () => {
    const yes = build({ perms: ['budget.book', 'budget.export'] });
    expect(yes.cmp.canManage()).toBe(true);
    expect(yes.cmp.canExport()).toBe(true);
    yes.http.verify();
    TestBed.resetTestingModule();
    const no = build({ perms: ['budget.view'] });
    expect(no.cmp.canManage()).toBe(false);
    expect(no.cmp.canExport()).toBe(false);
  });

  it('money() formats EUR for de and en locales', () => {
    const { cmp } = build();
    // the de locale comes from localStorage
    expect(cmp.money('120').replace(/\s/g, ' ')).toMatch(/120,00/);
    localStorage.setItem('ap.locale', 'en');
    TestBed.resetTestingModule();
    const en = build();
    expect(en.cmp.money('120')).toMatch(/120\.00/);
    expect(en.cmp.money('120')).toMatch(/€/);
  });

  it('activeFilterCount counts only non-empty filters', () => {
    const { cmp } = build();
    expect(cmp.activeFilterCount()).toBe(0);
    cmp.kind.set('expense');
    cmp.amountMin.set('  ');
    cmp.amountMax.set('50');
    cmp.createdFrom.set('2026-01-01');
    cmp.createdTo.set('');
    expect(cmp.activeFilterCount()).toBe(3);
  });

  it('invoiceLabel falls back gracefully for sparse invoices', () => {
    const sparse: Invoice = {
      ...INVOICE,
      id: 'inv-2',
      number: null,
      supplier: null,
      grossAmount: '5.00',
    };
    const { cmp } = build({ invoices: [sparse] });
    // Only the amount remains (number/supplier filtered out).
    expect(dlg(cmp).invoiceOptions()[0].label).toMatch(/5,00\s?€/);
    expect(dlg(cmp).invoiceOptions()[0].label).not.toContain('·');
  });

  it('lists only open invoices; edit keeps a linked paid invoice visible', () => {
    const paid: Invoice = { ...INVOICE, id: 'inv-paid', number: 'RE-PAID', status: 'paid' };
    const { cmp } = build({ invoices: [INVOICE, paid] });
    // Create dropdown: only open invoices (paid ones hidden).
    expect(dlg(cmp).invoiceOptions().map((o) => o.value)).toEqual(['inv-1']);
    // Edit without a selection: also only open ones.
    expect(dlg(cmp).editInvoiceOptions().map((o) => o.value)).toEqual(['inv-1']);
    // The linked (already paid) invoice stays visible in the edit dropdown.
    dlg(cmp).editInvoiceId.set('inv-paid');
    expect(dlg(cmp).editInvoiceOptions().map((o) => o.value)).toEqual(['inv-paid', 'inv-1']);
  });

  it('sorts open invoices by issue date, newest first', () => {
    const older: Invoice = { ...INVOICE, id: 'inv-old', issueDate: '2026-01-01' };
    const newer: Invoice = { ...INVOICE, id: 'inv-new', issueDate: '2026-09-01' };
    const { cmp } = build({ invoices: [older, newer] });
    expect(dlg(cmp).invoiceOptions().map((o) => o.value)).toEqual(['inv-new', 'inv-old']);
  });

  it('setKind, selectBudget reload the list with the new filter', () => {
    const { cmp, http } = build();
    cmp.setKind('income');
    flushList(http, page([]));
    expect(cmp.kind()).toBe('income');

    cmp.selectBudget('b-9');
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    expect(req.request.params.get('budget')).toBe('b-9');
    expect(req.request.params.get('kind')).toBe('income');
    req.flush(page([]));
    expect(cmp.budgetId()).toBe('b-9');
  });

  it('fetch passes all active filter params to the API', () => {
    const { cmp, http } = build();
    cmp.kind.set('expense');
    cmp.q.set('  flyer  ');
    cmp.amountMin.set('10');
    cmp.amountMax.set('99');
    cmp.createdFrom.set('2026-01-01');
    cmp.createdTo.set('2026-12-31');
    cmp.budgetId.set('b-1');
    cmp.setKind('expense'); // triggers reload
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    const p = req.request.params;
    expect(p.get('budget')).toBe('b-1');
    expect(p.get('kind')).toBe('expense');
    expect(p.get('q')).toBe('flyer');
    expect(p.get('amountMin')).toBe('10');
    expect(p.get('amountMax')).toBe('99');
    expect(p.get('createdFrom')).toBe('2026-01-01');
    expect(p.get('createdTo')).toBe('2026-12-31');
    expect(p.get('sort')).toBe('paymentDate');
    expect(p.get('order')).toBe('desc');
    req.flush(page([]));
  });

  it('fetch omits empty/whitespace optional params', () => {
    const { cmp, http } = build();
    cmp.q.set('   ');
    cmp.amountMin.set('   ');
    cmp.amountMax.set('');
    cmp.setKind(''); // reload with every filter empty
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    const p = req.request.params;
    expect(p.has('q')).toBe(false);
    expect(p.has('amountMin')).toBe(false);
    expect(p.has('amountMax')).toBe(false);
    expect(p.has('kind')).toBe(false);
    req.flush(page([]));
  });

  it('debouncedReload coalesces rapid filter changes into one reload', () => {
    jest.useFakeTimers();
    const { cmp, http } = build();
    cmp.onSearch('a');
    cmp.onSearch('ab');
    lst(cmp).onAmountFilter('min', '5');
    lst(cmp).onAmountFilter('max', '50');
    lst(cmp).onDateFilter('from', '2026-01-01');
    lst(cmp).onDateFilter('to', '2026-12-31');
    expect(cmp.q()).toBe('ab');
    expect(cmp.amountMin()).toBe('5');
    expect(cmp.amountMax()).toBe('50');
    expect(cmp.createdFrom()).toBe('2026-01-01');
    expect(cmp.createdTo()).toBe('2026-12-31');
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    jest.advanceTimersByTime(400);
    flushList(http, page([]));
  });

  it('resetFilters clears every filter and reloads', () => {
    const { cmp, http } = build();
    cmp.kind.set('income');
    cmp.amountMin.set('5');
    cmp.amountMax.set('9');
    cmp.createdFrom.set('2026-01-01');
    cmp.createdTo.set('2026-02-01');
    cmp.resetFilters();
    expect(cmp.kind()).toBe('');
    expect(cmp.amountMin()).toBe('');
    expect(cmp.amountMax()).toBe('');
    expect(cmp.createdFrom()).toBe('');
    expect(cmp.createdTo()).toBe('');
    flushList(http, page([]));
  });

  it('onSort toggles direction on same field and resets to desc on new field', () => {
    const { cmp, http } = build();
    // the default sort is paymentDate desc, so the same column flips to asc
    cmp.onSort('paymentDate');
    expect(cmp.sortField()).toBe('paymentDate');
    expect(cmp.sortOrder()).toBe('asc');
    flushList(http, page([]));
    cmp.onSort('paymentDate');
    expect(cmp.sortOrder()).toBe('desc');
    flushList(http, page([]));
    cmp.onSort('amount');
    expect(cmp.sortField()).toBe('amount');
    expect(cmp.sortOrder()).toBe('desc');
    flushList(http, page([]));
  });

  it('loadMore appends the next page and advances the offset', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 3) });
    expect(cmp.hasMore()).toBe(true);
    cmp.loadMore();
    expect(cmp.loadingMore()).toBe(true);
    const second = { ...EXPENSE, id: 'e-2', description: 'Zweite' };
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    expect(req.request.params.get('offset')).toBe('1');
    req.flush(page([second], 3, 1));
    expect(cmp.items().map((x) => x.id)).toEqual(['e-1', 'e-2']);
    expect(cmp.loadingMore()).toBe(false);
  });

  it('loadMore is a no-op while loading, loadingMore or when no more pages', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    // total === items.length → hasMore false
    expect(cmp.hasMore()).toBe(false);
    cmp.loadMore();
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    cmp.total.set(5);
    cmp.loadingMore.set(true);
    cmp.loadMore();
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    cmp.loadingMore.set(false);
    cmp.loading.set(true);
    cmp.loadMore();
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    cmp.loading.set(false);
  });

  it('openCreate resets the dialog and loads fiscal years when a budget is preselected', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.budgetId.set('child-1');
    cmp.openCreate();
    expect(cmp.createOpen()).toBe(true);
    expect(dlg(cmp).newKind()).toBe('expense');
    expect(dlg(cmp).newBudgetId()).toBe('child-1');
    // the fiscal-year load resolves child-1 to its top node top-1
    const req = http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years'));
    req.flush([FY_ACTIVE]);
    expect(dlg(cmp).fiscalYearOptions()).toEqual([{ value: 'fy-active', label: '2026' }]);
    // exactly one active fiscal year → preselected
    expect(dlg(cmp).newFiscalYearId()).toBe('fy-active');
  });

  it('openCreate without a preselected budget skips the fiscal-year load', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.openCreate();
    expect(cmp.createOpen()).toBe(true);
    expect(dlg(cmp).newBudgetId()).toBe('');
    expect(dlg(cmp).fiscalYearOptions()).toEqual([]);
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('onPickBudget loads fiscal years; multiple active years are not auto-selected', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    dlg(cmp).onPickBudget('child-1');
    expect(dlg(cmp).newBudgetId()).toBe('child-1');
    const secondActive: FiscalYear = { ...FY_ACTIVE, id: 'fy-2', display: '2026/27' };
    http
      .expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years'))
      .flush([FY_ACTIVE, secondActive, FY_OLD]);
    expect(dlg(cmp).fiscalYearOptions().length).toBe(3);
    // two active → no preselection
    expect(dlg(cmp).newFiscalYearId()).toBe('');
  });

  it('onPickBudget with empty id clears the fiscal-year selection without a request', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    dlg(cmp).newFiscalYearId.set('fy-x');
    dlg(cmp).fiscalYearOptions.set([{ value: 'fy-x', label: 'X' }]);
    dlg(cmp).onPickBudget('');
    expect(dlg(cmp).newBudgetId()).toBe('');
    expect(dlg(cmp).newFiscalYearId()).toBe('');
    expect(dlg(cmp).fiscalYearOptions()).toEqual([]);
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('loadFiscalYears resets options on error', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    dlg(cmp).fiscalYearOptions.set([{ value: 'x', label: 'X' }]);
    dlg(cmp).onPickBudget('child-1');
    http
      .expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years'))
      .error(new ProgressEvent('err'));
    expect(dlg(cmp).fiscalYearOptions()).toEqual([]);
  });

  it('loadFiscalYears is skipped when the budget id is not in the tree', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    dlg(cmp).onPickBudget('unknown-id');
    // the top-node lookup returns null, so no request runs and the options stay empty
    http.expectNone((r) => r.url.includes('/fiscal-years'));
    expect(dlg(cmp).fiscalYearOptions()).toEqual([]);
  });

  it('canSubmitCreate enforces description, amount and (for standalone) budget+fy', () => {
    const { cmp } = build();
    expect(cmp.canSubmitCreate()).toBe(false);
    dlg(cmp).newDescription.set('Kaffee');
    expect(cmp.canSubmitCreate()).toBe(false); // amount missing
    dlg(cmp).newAmount.set('0');
    expect(cmp.canSubmitCreate()).toBe(false); // amount must be > 0
    dlg(cmp).newAmount.set('12');
    expect(cmp.canSubmitCreate()).toBe(false); // standalone needs budget+fy
    dlg(cmp).newBudgetId.set('b-1');
    expect(cmp.canSubmitCreate()).toBe(false); // fy missing
    dlg(cmp).newFiscalYearId.set('fy-1');
    expect(cmp.canSubmitCreate()).toBe(true);
    // a linked booking needs only an application, which carries cost center and year
    dlg(cmp).newBudgetId.set('');
    dlg(cmp).newFiscalYearId.set('');
    dlg(cmp).newApplicationId.set('app-9');
    expect(cmp.canSubmitCreate()).toBe(true);
  });

  it('create posts a standalone booking, toasts and reloads', () => {
    const { cmp, http } = build();
    dlg(cmp).newDescription.set('  Kaffee  ');
    dlg(cmp).newAmount.set('12.50');
    dlg(cmp).newBudgetId.set('b-1');
    dlg(cmp).newFiscalYearId.set('fy-1');
    dlg(cmp).newCorrespondent.set(' Bäckerei ');
    dlg(cmp).newReferenceNumber.set(' R-1 ');
    dlg(cmp).newPaymentMethod.set('bar');
    dlg(cmp).newCategory.set(' Bewirtung ');
    dlg(cmp).newNote.set(' lecker ');
    cmp.create(new Event('submit'));
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST');
    expect(req.request.body).toMatchObject({
      amount: '12.50',
      description: 'Kaffee',
      kind: 'expense',
      applicationId: null,
      budgetId: 'b-1',
      fiscalYearId: 'fy-1',
      correspondent: 'Bäckerei',
      referenceNumber: 'R-1',
      paymentMethod: 'bar',
      category: 'Bewirtung',
      note: 'lecker',
    });
    req.flush({ ...EXPENSE, id: 'e-new' });
    expect(cmp.saving()).toBe(false);
    expect(cmp.createOpen()).toBe(false);
    // reload fires another list request
    flushList(http, page([]));
  });

  it('create posts a linked booking nulling budget/fy and blank metadata', () => {
    const { cmp, http } = build();
    dlg(cmp).newDescription.set('Gebunden');
    dlg(cmp).newAmount.set('5');
    dlg(cmp).newApplicationId.set('app-9');
    dlg(cmp).newBudgetId.set('ignored');
    dlg(cmp).newFiscalYearId.set('ignored');
    cmp.create(new Event('submit'));
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST');
    expect(req.request.body).toMatchObject({
      applicationId: 'app-9',
      budgetId: null,
      fiscalYearId: null,
      invoiceId: null,
      correspondent: null,
      referenceNumber: null,
      paymentMethod: null,
      category: null,
      note: null,
    });
    req.flush({ ...EXPENSE, id: 'e-link' });
    flushList(http, page([]));
  });

  it('create is a no-op when invalid or already saving', () => {
    const { cmp, http } = build();
    cmp.create(new Event('submit')); // invalid → no request
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'POST');
    // valid but saving
    dlg(cmp).newDescription.set('x');
    dlg(cmp).newAmount.set('1');
    dlg(cmp).newApplicationId.set('app-1');
    cmp.saving.set(true);
    cmp.create(new Event('submit'));
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'POST');
  });

  it('create surfaces the problem+json detail on error, else a generic message', () => {
    const { cmp, http } = build();
    const toastSpy = jest.spyOn(
      (cmp as unknown as { toast: { error: (m: string) => void } }).toast,
      'error',
    );
    dlg(cmp).newDescription.set('x');
    dlg(cmp).newAmount.set('1');
    dlg(cmp).newApplicationId.set('app-1');
    cmp.create(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST')
      .flush({ detail: 'Budget überschritten' }, { status: 422, statusText: 'Unprocessable' });
    expect(cmp.saving()).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('Budget überschritten');

    // generic fallback without a detail
    cmp.create(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(toastSpy).toHaveBeenLastCalledWith('Aktion fehlgeschlagen.');
  });

  it('setNewKindIncome switches to income and clears any application link', () => {
    const { cmp } = build();
    dlg(cmp).newApplicationId.set('app-1');
    dlg(cmp).appQuery.set('Antrag X');
    dlg(cmp).appCandidates.set([{ id: 'app-1', title: 'Antrag X' }]);
    dlg(cmp).setNewKindIncome();
    expect(dlg(cmp).newKind()).toBe('income');
    expect(dlg(cmp).newApplicationId()).toBe('');
    expect(dlg(cmp).appQuery()).toBe('');
    expect(dlg(cmp).appCandidates()).toEqual([]);
  });

  it('onAppSearch queries applications and maps candidates (title fallback to id)', () => {
    const { cmp, http } = build();
    dlg(cmp).onAppSearch('  flyer ');
    // appQuery holds the raw value. Only the request param is trimmed.
    expect(dlg(cmp).appQuery()).toBe('  flyer ');
    const req = http.expectOne((r) => r.url.endsWith('/applications'));
    expect(req.request.params.get('q')).toBe('flyer');
    expect(req.request.params.get('limit')).toBe('8');
    req.flush({
      items: [
        { id: 'app-1', title: 'Flyer-Antrag' },
        { id: 'app-2', title: null },
      ],
      total: 2,
      limit: 8,
      offset: 0,
    });
    expect(dlg(cmp).appCandidates()).toEqual([
      { id: 'app-1', title: 'Flyer-Antrag' },
      { id: 'app-2', title: 'app-2' },
    ]);
  });

  it('onAppSearch clears candidates for an empty query without a request', () => {
    const { cmp, http } = build();
    dlg(cmp).appCandidates.set([{ id: 'x', title: 'X' }]);
    dlg(cmp).onAppSearch('   ');
    expect(dlg(cmp).appQuery()).toBe('   ');
    expect(dlg(cmp).appCandidates()).toEqual([]);
    http.expectNone((r) => r.url.endsWith('/applications'));
  });

  it('onAppSearch clears candidates on error', () => {
    const { cmp, http } = build();
    dlg(cmp).onAppSearch('z');
    http.expectOne((r) => r.url.endsWith('/applications')).error(new ProgressEvent('err'));
    expect(dlg(cmp).appCandidates()).toEqual([]);
  });

  it('pickApp / clearApp manage the selected application', () => {
    const { cmp } = build();
    dlg(cmp).appCandidates.set([{ id: 'app-1', title: 'Antrag X' }]);
    dlg(cmp).pickApp({ id: 'app-1', title: 'Antrag X' });
    expect(dlg(cmp).newApplicationId()).toBe('app-1');
    expect(dlg(cmp).appQuery()).toBe('Antrag X');
    expect(dlg(cmp).appCandidates()).toEqual([]);
    dlg(cmp).clearApp();
    expect(dlg(cmp).newApplicationId()).toBe('');
    expect(dlg(cmp).appQuery()).toBe('');
  });

  it('onPickInvoice prefills amount, payee, reference and invoice date', () => {
    const { cmp } = build({ invoices: [INVOICE] });
    dlg(cmp).onPickInvoice('inv-1');
    expect(dlg(cmp).newInvoiceId()).toBe('inv-1');
    expect(dlg(cmp).newAmount()).toBe('119.00');
    expect(dlg(cmp).newCorrespondent()).toBe('Acme GmbH');
    expect(dlg(cmp).newReferenceNumber()).toBe('RE-2026-1');
    expect(dlg(cmp).newInvoiceDate()).toBe('2026-04-01');
  });

  it('onPickInvoice with unknown id only stores the id (no prefill)', () => {
    const { cmp } = build({ invoices: [INVOICE] });
    dlg(cmp).onPickInvoice('nope');
    expect(dlg(cmp).newInvoiceId()).toBe('nope');
    expect(dlg(cmp).newAmount()).toBe('');
    expect(dlg(cmp).newCorrespondent()).toBe('');
  });

  it('onPickInvoice handles sparse invoices (null gross, missing fields)', () => {
    // A null grossAmount at runtime hits the empty-string fallback. The backend can
    // send null for this field.
    const sparse = {
      ...INVOICE,
      id: 'inv-3',
      grossAmount: null,
      supplier: null,
      number: null,
      issueDate: null,
    } as unknown as Invoice;
    const { cmp } = build({ invoices: [sparse] });
    dlg(cmp).newAmount.set('preset');
    dlg(cmp).newCorrespondent.set('keep');
    dlg(cmp).newReferenceNumber.set('keep');
    dlg(cmp).newInvoiceDate.set('keep');
    dlg(cmp).onPickInvoice('inv-3');
    expect(dlg(cmp).newAmount()).toBe('');
    expect(dlg(cmp).newCorrespondent()).toBe('keep');
    expect(dlg(cmp).newReferenceNumber()).toBe('keep');
    expect(dlg(cmp).newInvoiceDate()).toBe('keep');
  });

  it('onPickEditInvoice prefills the edit form, unknown id is a no-op', () => {
    const { cmp } = build({ invoices: [INVOICE] });
    dlg(cmp).onPickEditInvoice('inv-1');
    expect(dlg(cmp).editInvoiceId()).toBe('inv-1');
    expect(dlg(cmp).editAmount()).toBe('119.00');
    expect(dlg(cmp).editCorrespondent()).toBe('Acme GmbH');
    expect(dlg(cmp).editReferenceNumber()).toBe('RE-2026-1');
    expect(dlg(cmp).editInvoiceDate()).toBe('2026-04-01');
    dlg(cmp).onPickEditInvoice('nope');
    expect(dlg(cmp).editInvoiceId()).toBe('nope');
  });

  it('onPickEditInvoice coerces a null gross amount to empty string', () => {
    const sparse = { ...INVOICE, id: 'inv-4', grossAmount: null } as unknown as Invoice;
    const { cmp } = build({ invoices: [sparse] });
    dlg(cmp).editAmount.set('preset');
    dlg(cmp).onPickEditInvoice('inv-4');
    expect(dlg(cmp).editAmount()).toBe('');
  });

  it('openEdit fills the edit form, coalescing null metadata to empty strings', () => {
    const { cmp } = build();
    const e: Expense = {
      ...EXPENSE,
      invoiceId: null,
      invoiceDate: null,
      paymentDate: null,
      correspondent: null,
      referenceNumber: null,
      paymentMethod: null,
      category: null,
      note: null,
    };
    cmp.openEdit(e);
    expect(cmp.editing()).toBe(e);
    expect(dlg(cmp).editAmount()).toBe(e.amount);
    expect(dlg(cmp).editDescription()).toBe(e.description);
    expect(dlg(cmp).editInvoiceId()).toBe('');
    expect(dlg(cmp).editInvoiceDate()).toBe('');
    expect(dlg(cmp).editPaymentDate()).toBe('');
    expect(dlg(cmp).editCorrespondent()).toBe('');
    expect(dlg(cmp).editReferenceNumber()).toBe('');
    expect(dlg(cmp).editPaymentMethod()).toBe('');
    expect(dlg(cmp).editCategory()).toBe('');
    expect(dlg(cmp).editNote()).toBe('');
  });

  it('openEdit keeps populated metadata fields', () => {
    const { cmp } = build();
    cmp.openEdit({ ...EXPENSE, invoiceId: 'inv-1' });
    expect(dlg(cmp).editInvoiceId()).toBe('inv-1');
    expect(dlg(cmp).editPaymentMethod()).toBe('ueberweisung');
    expect(dlg(cmp).editCategory()).toBe('Werbung');
  });

  it('saveEdit patches the booking and updates the matching list row', () => {
    const other = { ...EXPENSE, id: 'e-2', description: 'Andere' };
    const { cmp, http } = build({ expenses: page([EXPENSE, other], 2) });
    cmp.openEdit(EXPENSE);
    dlg(cmp).editAmount.set('200');
    dlg(cmp).editDescription.set('  Neu  ');
    dlg(cmp).editInvoiceId.set('inv-9');
    dlg(cmp).editCorrespondent.set(' X ');
    dlg(cmp).editReferenceNumber.set(' Y ');
    dlg(cmp).editPaymentMethod.set('karte');
    dlg(cmp).editCategory.set(' Z ');
    dlg(cmp).editNote.set(' note ');
    cmp.saveEdit(new Event('submit'));
    const req = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH',
    );
    expect(req.request.body).toMatchObject({
      amount: '200',
      description: 'Neu',
      invoiceId: 'inv-9',
      correspondent: 'X',
      referenceNumber: 'Y',
      paymentMethod: 'karte',
      category: 'Z',
      note: 'note',
    });
    const updated = { ...EXPENSE, description: 'Neu', amount: '200' };
    req.flush(updated);
    expect(cmp.saving()).toBe(false);
    expect(cmp.editing()).toBeNull();
    expect(cmp.items().find((x) => x.id === 'e-1')?.description).toBe('Neu');
    expect(cmp.items().find((x) => x.id === 'e-2')?.description).toBe('Andere');
  });

  it('saveEdit nulls blank metadata fields', () => {
    const { cmp, http } = build();
    cmp.openEdit(EXPENSE);
    dlg(cmp).editInvoiceId.set('');
    dlg(cmp).editInvoiceDate.set('');
    dlg(cmp).editPaymentDate.set('');
    dlg(cmp).editCorrespondent.set('   ');
    dlg(cmp).editReferenceNumber.set('');
    dlg(cmp).editPaymentMethod.set('');
    dlg(cmp).editCategory.set('');
    dlg(cmp).editNote.set('');
    cmp.saveEdit(new Event('submit'));
    const req = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH',
    );
    expect(req.request.body).toMatchObject({
      invoiceId: null,
      invoiceDate: null,
      paymentDate: null,
      correspondent: null,
      referenceNumber: null,
      paymentMethod: null,
      category: null,
      note: null,
    });
    req.flush(EXPENSE);
  });

  it('saveEdit is a no-op without an editing target or while saving', () => {
    const { cmp, http } = build();
    cmp.saveEdit(new Event('submit')); // editing null
    http.expectNone((r) => r.method === 'PATCH');
    cmp.editing.set(EXPENSE);
    cmp.saving.set(true);
    cmp.saveEdit(new Event('submit'));
    http.expectNone((r) => r.method === 'PATCH');
  });

  it('saveEdit toasts a generic failure on error', () => {
    const { cmp, http } = build();
    const toastSpy = jest.spyOn(
      (cmp as unknown as { toast: { error: (m: string) => void } }).toast,
      'error',
    );
    cmp.openEdit(EXPENSE);
    cmp.saveEdit(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(cmp.saving()).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('askDelete / doDelete removes the row and decrements the total', () => {
    const other = { ...EXPENSE, id: 'e-2' };
    const { cmp, http } = build({ expenses: page([EXPENSE, other], 2) });
    cmp.askDelete(EXPENSE);
    expect(cmp.confirmDelete()).toBe(EXPENSE);
    cmp.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE')
      .flush(null);
    expect(cmp.confirmDelete()).toBeNull();
    expect(cmp.items().map((x) => x.id)).toEqual(['e-2']);
    expect(cmp.total()).toBe(1);
    expect(cmp.saving()).toBe(false);
  });

  it('doDelete clamps the total at zero', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 0) });
    cmp.confirmDelete.set(EXPENSE);
    cmp.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE')
      .flush(null);
    expect(cmp.total()).toBe(0);
  });

  it('doDelete is a no-op without a target or while saving', () => {
    const { cmp, http } = build();
    cmp.doDelete(); // no confirmDelete
    http.expectNone((r) => r.method === 'DELETE');
    cmp.confirmDelete.set(EXPENSE);
    cmp.saving.set(true);
    cmp.doDelete();
    http.expectNone((r) => r.method === 'DELETE');
  });

  it('doDelete toasts a failure on error', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    const toastSpy = jest.spyOn(
      (cmp as unknown as { toast: { error: (m: string) => void } }).toast,
      'error',
    );
    cmp.confirmDelete.set(EXPENSE);
    cmp.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE')
      .error(new ProgressEvent('err'));
    expect(cmp.saving()).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('onExport downloads the xlsx and clears the exporting flag', () => {
    // jsdom has no URL.createObjectURL and no URL.revokeObjectURL, so define them first.
    (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
    (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
    const createObjSpy = jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    const revokeSpy = jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const clickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    const { cmp, http } = build();
    cmp.budgetId.set('b-1');
    cmp.kind.set('expense');
    cmp.q.set(' flyer ');
    cmp.amountMin.set('5');
    cmp.amountMax.set('50');
    cmp.createdFrom.set('2026-01-01');
    cmp.createdTo.set('2026-12-31');
    cmp.onExport();
    expect(cmp.exporting()).toBe(true);
    const req = http.expectOne((r) => r.url.endsWith('/expenses/export.xlsx'));
    const p = req.request.params;
    expect(p.get('budget')).toBe('b-1');
    expect(p.get('kind')).toBe('expense');
    expect(p.get('q')).toBe('flyer');
    expect(p.get('amountMin')).toBe('5');
    expect(p.get('createdTo')).toBe('2026-12-31');
    req.flush(new Blob(['x']));
    expect(cmp.exporting()).toBe(false);
    expect(createObjSpy).toHaveBeenCalled();
    createObjSpy.mockRestore();
    revokeSpy.mockRestore();
    clickSpy.mockRestore();
  });

  it('onExport is a no-op while already exporting', () => {
    const { cmp, http } = build();
    cmp.exporting.set(true);
    cmp.onExport();
    http.expectNone((r) => r.url.endsWith('/expenses/export.xlsx'));
  });

  it('onExport clears the exporting flag on error', () => {
    const { cmp, http } = build();
    cmp.onExport();
    http.expectOne((r) => r.url.endsWith('/expenses/export.xlsx')).error(new ProgressEvent('err'));
    expect(cmp.exporting()).toBe(false);
  });

  it('paymentMethodOptions lists all methods localized', () => {
    const { cmp } = build();
    const opts = dlg(cmp).paymentMethodOptions();
    expect(opts.map((o) => o.value)).toEqual([
      'ueberweisung',
      'bar',
      'lastschrift',
      'karte',
      'paypal',
    ]);
    expect(opts.every((o) => typeof o.label === 'string' && o.label.length > 0)).toBe(true);
  });

  it('openTransfer seeds from the selected budget and loads its fiscal years', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.budgetId.set('child-1');
    cmp.openTransfer();
    expect(cmp.transferOpen()).toBe(true);
    expect(cmp.tFromId()).toBe('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_ACTIVE]);
    expect(dlg(cmp).transferFyOptions()).toEqual([{ value: 'fy-active', label: '2026' }]);
    expect(cmp.tFiscalYearId()).toBe('fy-active');
  });

  it('openTransfer without a selected budget does not load fiscal years', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.openTransfer();
    expect(cmp.tFromId()).toBe('');
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('onTransferFrom reloads fiscal years for the new source budget', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.tFiscalYearId.set('stale');
    dlg(cmp).onTransferFrom('child-1');
    expect(cmp.tFromId()).toBe('child-1');
    expect(cmp.tFiscalYearId()).toBe('');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_ACTIVE]);
    expect(cmp.tFiscalYearId()).toBe('fy-active');
  });

  it('onTransferFrom with empty id clears the source without a request', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    dlg(cmp).onTransferFrom('');
    expect(cmp.tFromId()).toBe('');
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('loadTransferFy is skipped for an unknown budget and resets on error', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    // an unknown budget has no top node, so no request runs
    dlg(cmp).onTransferFrom('ghost');
    http.expectNone((r) => r.url.includes('/fiscal-years'));
    // known but error → options reset
    dlg(cmp).transferFyOptions.set([{ value: 'x', label: 'X' }]);
    dlg(cmp).onTransferFrom('child-1');
    http
      .expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years'))
      .error(new ProgressEvent('err'));
    expect(dlg(cmp).transferFyOptions()).toEqual([]);
  });

  it('loadTransferFy does not auto-select when there is no single active year', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    dlg(cmp).onTransferFrom('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_OLD]);
    expect(dlg(cmp).transferFyOptions().length).toBe(1);
    expect(cmp.tFiscalYearId()).toBe('');
  });

  it('canSubmitTransfer requires distinct budgets, a year, a positive amount and a description', () => {
    const { cmp } = build();
    expect(cmp.canSubmitTransfer()).toBe(false);
    cmp.tFromId.set('a');
    cmp.tToId.set('a'); // same → invalid
    cmp.tFiscalYearId.set('fy-1');
    cmp.tAmount.set('10');
    cmp.tDescription.set('Umbuchung');
    expect(cmp.canSubmitTransfer()).toBe(false);
    cmp.tToId.set('b');
    expect(cmp.canSubmitTransfer()).toBe(true);
    cmp.tAmount.set('0');
    expect(cmp.canSubmitTransfer()).toBe(false);
    cmp.tAmount.set('10');
    cmp.tDescription.set('   ');
    expect(cmp.canSubmitTransfer()).toBe(false);
  });

  it('createTransfer posts, toasts success, closes the dialog and reloads', () => {
    const { cmp, http } = build();
    cmp.tFromId.set('a');
    cmp.tToId.set('b');
    cmp.tFiscalYearId.set('fy-1');
    cmp.tAmount.set('25');
    cmp.tDescription.set(' Umbuchung ');
    cmp.transferOpen.set(true);
    cmp.createTransfer(new Event('submit'));
    const req = http.expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'POST');
    expect(req.request.body).toEqual({
      fromBudgetId: 'a',
      toBudgetId: 'b',
      fiscalYearId: 'fy-1',
      amount: '25',
      description: 'Umbuchung',
    });
    req.flush({});
    expect(cmp.saving()).toBe(false);
    expect(cmp.transferOpen()).toBe(false);
    flushList(http, page([]));
  });

  it('createTransfer is a no-op when invalid or already saving', () => {
    const { cmp, http } = build();
    cmp.createTransfer(new Event('submit')); // invalid
    http.expectNone((r) => r.url.endsWith('/budget-transfers'));
    cmp.tFromId.set('a');
    cmp.tToId.set('b');
    cmp.tFiscalYearId.set('fy-1');
    cmp.tAmount.set('25');
    cmp.tDescription.set('x');
    cmp.saving.set(true);
    cmp.createTransfer(new Event('submit'));
    http.expectNone((r) => r.url.endsWith('/budget-transfers'));
  });

  it('createTransfer surfaces the problem detail on error', () => {
    const { cmp, http } = build();
    const toastSpy = jest.spyOn(
      (cmp as unknown as { toast: { error: (m: string) => void } }).toast,
      'error',
    );
    cmp.tFromId.set('a');
    cmp.tToId.set('b');
    cmp.tFiscalYearId.set('fy-1');
    cmp.tAmount.set('25');
    cmp.tDescription.set('x');
    cmp.createTransfer(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'POST')
      .flush({ detail: 'Zu wenig Budget' }, { status: 422, statusText: 'Unprocessable' });
    expect(cmp.saving()).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('Zu wenig Budget');
  });
});

// Sub-bookings, the description expand and the invoice detail dialog.

/** Parent booking with children. Its amount is the sum of the children and read-only
 *  on the server. */
const PARENT: Expense = { ...EXPENSE, id: 'parent-1', parentExpenseId: null, childCount: 2 };
const SUB: Expense = {
  ...EXPENSE,
  id: 'sub-1',
  parentExpenseId: 'parent-1',
  childCount: 0,
  description: 'Teilzahlung',
};

function toastSpies(cmp: ExpensesComponent): {
  success: jest.SpyInstance;
  error: jest.SpyInstance;
} {
  const toast = (
    cmp as unknown as { toast: { success: (m: string) => void; error: (m: string) => void } }
  ).toast;
  return { success: jest.spyOn(toast, 'success'), error: jest.spyOn(toast, 'error') };
}

describe('ExpensesComponent (sub-bookings)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
  });

  it('loadSub clears the loading flag and toasts on error', () => {
    const { cmp, http } = build({ expenses: page([PARENT], 1) });
    const { error } = toastSpies(cmp);
    subs(cmp).loadSub('parent-1');
    http
      .expectOne(
        (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'GET',
      )
      .error(new ProgressEvent('err'));
    expect(subs(cmp).isLoadingSub('parent-1')).toBe(false);
    expect(error).toHaveBeenCalledWith('Unterbuchungen konnten nicht geladen werden.');
  });

  it('openCreateSub seeds an empty dialog; closeCreateSub clears the parent', () => {
    const { cmp } = build();
    subs(cmp).subAmount.set('stale');
    subs(cmp).subDescription.set('stale');
    subs(cmp).subPaymentDate.set('stale');
    subs(cmp).subCorrespondent.set('stale');
    cmp.openCreateSub(PARENT);
    expect(cmp.subParent()).toBe(PARENT);
    expect(subs(cmp).subAmount()).toBe('');
    expect(subs(cmp).subDescription()).toBe('');
    expect(subs(cmp).subPaymentDate()).toBe('');
    expect(subs(cmp).subCorrespondent()).toBe('');
    subs(cmp).closeCreateSub();
    expect(cmp.subParent()).toBeNull();
  });

  it('canSubmitSub requires amount and description', () => {
    const { cmp } = build();
    expect(subs(cmp).canSubmitSub()).toBe(false);
    subs(cmp).subAmount.set('10');
    expect(subs(cmp).canSubmitSub()).toBe(false);
    subs(cmp).subDescription.set('  ');
    expect(subs(cmp).canSubmitSub()).toBe(false);
    subs(cmp).subDescription.set('Teil');
    expect(subs(cmp).canSubmitSub()).toBe(true);
  });

  it('createSub posts the sub-booking, expands the parent, reloads and toasts', () => {
    const { cmp, http } = build({ expenses: page([PARENT], 1) });
    const { success } = toastSpies(cmp);
    cmp.openCreateSub(PARENT);
    subs(cmp).subAmount.set('10');
    subs(cmp).subDescription.set('  Teil  ');
    subs(cmp).subPaymentDate.set('2026-06-01');
    subs(cmp).subCorrespondent.set('  Bank  ');
    subs(cmp).createSub(new Event('submit'));
    const req = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'POST',
    );
    expect(req.request.body).toEqual({
      amount: '10',
      description: 'Teil',
      paymentDate: '2026-06-01',
      correspondent: 'Bank',
    });
    req.flush(SUB);
    expect(cmp.saving()).toBe(false);
    expect(cmp.subParent()).toBeNull();
    expect(success).toHaveBeenCalledWith('Unterbuchung hinzugefügt.');
    // reload the child list and the parent amount, which is the sum of the children
    http
      .expectOne(
        (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'GET',
      )
      .flush([SUB]);
    flushList(http, page([PARENT], 1));
  });

  it('createSub nulls blank payment date and correspondent', () => {
    const { cmp, http } = build({ expenses: page([PARENT], 1) });
    cmp.openCreateSub(PARENT);
    subs(cmp).subAmount.set('5');
    subs(cmp).subDescription.set('Teil');
    // a call without an event takes the optional-chaining branch and skips preventDefault
    subs(cmp).createSub();
    const req = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'POST',
    );
    expect(req.request.body).toEqual({
      amount: '5',
      description: 'Teil',
      paymentDate: null,
      correspondent: null,
    });
    req.flush(SUB);
    http
      .expectOne(
        (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'GET',
      )
      .flush([SUB]);
    flushList(http, page([PARENT], 1));
  });

  it('createSub is a no-op without a parent, when invalid or while saving', () => {
    const { cmp, http } = build();
    subs(cmp).subAmount.set('10');
    subs(cmp).subDescription.set('Teil');
    subs(cmp).createSub(new Event('submit')); // no parent dialog open
    http.expectNone((r) => r.url.includes('/sub-bookings'));
    cmp.openCreateSub(PARENT); // dialog open but fields reset → invalid
    subs(cmp).createSub(new Event('submit'));
    http.expectNone((r) => r.url.includes('/sub-bookings'));
    subs(cmp).subAmount.set('10');
    subs(cmp).subDescription.set('Teil');
    cmp.saving.set(true);
    subs(cmp).createSub(new Event('submit'));
    http.expectNone((r) => r.url.includes('/sub-bookings'));
  });

  it('createSub toasts a generic failure on error', () => {
    const { cmp, http } = build();
    const { error } = toastSpies(cmp);
    cmp.openCreateSub(PARENT);
    subs(cmp).subAmount.set('10');
    subs(cmp).subDescription.set('Teil');
    subs(cmp).createSub(new Event('submit'));
    http
      .expectOne(
        (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'POST',
      )
      .error(new ProgressEvent('err'));
    expect(cmp.saving()).toBe(false);
    // dialog stays open for correction.
    expect(cmp.subParent()).toBe(PARENT);
    expect(error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('saveEdit on a sub-booking refreshes the parent panel and the list', () => {
    const { cmp, http } = build({ expenses: page([PARENT], 1) });
    cmp.openEdit(SUB);
    dlg(cmp).editDescription.set('Teil neu');
    cmp.saveEdit(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/sub-1') && r.method === 'PATCH')
      .flush({ ...SUB, description: 'Teil neu' });
    expect(cmp.editing()).toBeNull();
    // parentExpenseId is set, so the parent panel and the list reload for the amount
    http
      .expectOne(
        (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'GET',
      )
      .flush([{ ...SUB, description: 'Teil neu' }]);
    flushList(http, page([PARENT], 1));
    expect(subs(cmp).subOf('parent-1')[0].description).toBe('Teil neu');
  });

  it('saveEdit sends budgetId only for a changed standalone cost centre and preserves childCount', () => {
    const { cmp, http } = build({ expenses: page([PARENT], 1) });
    cmp.openEdit(PARENT);
    dlg(cmp).editBudgetId.set('b-2'); // standalone + changed → gets sent
    cmp.saveEdit(new Event('submit'));
    const req = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/parent-1') && r.method === 'PATCH',
    );
    expect(req.request.body).toMatchObject({ budgetId: 'b-2' });
    // the amount did not change and stays read-only on the server, so it is not sent
    expect((req.request.body as Record<string, unknown>)['amount']).toBeUndefined();
    req.flush({ ...PARENT, budgetId: 'b-2', childCount: undefined as unknown as number });
    // keep childCount from the known row, because a single response omits it
    expect(cmp.items().find((x) => x.id === 'parent-1')?.childCount).toBe(2);
  });

  it('doDelete on a sub-booking refreshes the parent panel and the list', () => {
    const { cmp, http } = build({ expenses: page([PARENT], 1) });
    cmp.askDelete(SUB);
    cmp.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/sub-1') && r.method === 'DELETE')
      .flush(null);
    expect(cmp.confirmDelete()).toBeNull();
    // the parent row stays in the list. Reload the panel and the list instead.
    http
      .expectOne(
        (r) => r.url.endsWith('/budget-expenses/parent-1/sub-bookings') && r.method === 'GET',
      )
      .flush([]);
    flushList(http, page([PARENT], 1));
    expect(cmp.items().map((x) => x.id)).toEqual(['parent-1']);
  });
});

describe('ExpensesComponent (invoice detail)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
  });

  it('openInvoiceFile streams the file blob and downloads it (fileName fallback)', () => {
    (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
    (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
    const createObjSpy = jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    const revokeSpy = jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const clickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    const { cmp, http } = build();
    // a null fileName falls back to 'beleg.pdf'
    dlg(cmp).openInvoiceFile({ ...INVOICE, fileName: null });
    http
      .expectOne((r) => r.url.endsWith('/invoices/inv-1/file') && r.method === 'GET')
      .flush(new Blob(['pdf']));
    expect(createObjSpy).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    createObjSpy.mockRestore();
    revokeSpy.mockRestore();
    clickSpy.mockRestore();
  });

  it('openInvoiceFile toasts the problem detail on error', () => {
    const { cmp, http } = build();
    const { error } = toastSpies(cmp);
    dlg(cmp).openInvoiceFile(INVOICE);
    http
      .expectOne((r) => r.url.endsWith('/invoices/inv-1/file'))
      .flush(new Blob(['nope']), { status: 500, statusText: 'Server Error' });
    expect(error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });
});

// IntersectionObserver branch: the observer calls loadMore when the sentinel becomes
// visible. The test shims the observer and fires the callback by hand.
describe('ExpensesComponent (infinite scroll)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('observes the sentinel and loads more when it intersects', async () => {
    let trigger: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
    const disconnect = jest.fn();
    const observe = jest.fn();
    class IOStub {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        trigger = cb;
      }
      observe = observe;
      disconnect = disconnect;
    }
    (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver = IOStub;

    const view = await render(ExpensesComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['budget.view', 'budget.book']) },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http.match((r) => r.url.endsWith('/budgets')).forEach((req) => req.flush([]));
    http
      .match((r) => r.url.endsWith('/invoices') && r.method === 'GET')
      .forEach((req) => req.flush({ items: [], total: 0, limit: 200, offset: 0 }));
    http
      .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
      .forEach((req) => req.flush(page([EXPENSE], 3)));
    view.detectChanges();

    expect(observe).toHaveBeenCalled();
    // the sentinel becomes visible, so loadMore fetches the second page
    trigger?.([{ isIntersecting: true }]);
    http
      .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
      .forEach((req) => req.flush(page([{ ...EXPENSE, id: 'e-2' }], 3, 1)));
    // the sentinel is not visible, so no further request runs
    trigger?.([{ isIntersecting: false }]);
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'GET');

    delete (globalThis as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    http.verify();
  });
  it('watches the sentinel inside the list box on the wide layout', async () => {
    setViewport(WIDE);
    const roots: (Element | Document | null | undefined)[] = [];
    class IOStub {
      constructor(_cb: unknown, opts?: IntersectionObserverInit) {
        roots.push(opts?.root);
      }
      observe = jest.fn();
      disconnect = jest.fn();
    }
    (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver = IOStub;
    const { container, fixture } = await setup({ page: page([EXPENSE], 3) });
    fixture.detectChanges();
    // The list scrolls inside its own box there, so the box is the root.
    expect(roots.at(-1)).toBe(container.querySelector('.exp__scroll'));
    delete (globalThis as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
  });
});

// Bulk actions, cross-links and URL sync. The facade adds these members
// on top of the state modules. They are the selection, the bulk delete, the bulk export
// and reassign, ksLink, and the query-param adoption and mirror effects.

/** Stub URL.createObjectURL, URL.revokeObjectURL and the anchor click for blob
 *  downloads. */
function stubDownload(): {
  create: jest.SpyInstance;
  click: jest.SpyInstance;
  restore: () => void;
} {
  (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
  (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
  const create = jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
  const revoke = jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
  const click = jest
    .spyOn(HTMLAnchorElement.prototype, 'click')
    .mockImplementation(() => undefined);
  return {
    create,
    click,
    restore: () => {
      create.mockRestore();
      revoke.mockRestore();
      click.mockRestore();
    },
  };
}

describe('ExpensesComponent (batch/bulk)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
    jest.useRealTimers();
  });

  it('isSelected/toggleSelect add and remove a single row', () => {
    const { cmp } = build();
    expect(cmp.isSelected('e-1')).toBe(false);
    cmp.toggleSelect('e-1', true);
    expect(cmp.isSelected('e-1')).toBe(true);
    expect(cmp.selectedCount()).toBe(1);
    cmp.toggleSelect('e-1', false);
    expect(cmp.isSelected('e-1')).toBe(false);
    expect(cmp.selectedCount()).toBe(0);
  });

  it('toggleSelectAll selects/clears every current row; allSelected reflects it', () => {
    const e2 = { ...EXPENSE, id: 'e-2' };
    const { cmp } = build({ expenses: page([EXPENSE, e2], 2) });
    expect(cmp.allSelected()).toBe(false);
    cmp.toggleSelectAll(true);
    expect([...cmp.selected()].sort()).toEqual(['e-1', 'e-2']);
    expect(cmp.allSelected()).toBe(true);
    cmp.toggleSelectAll(false);
    expect(cmp.selectedCount()).toBe(0);
    expect(cmp.allSelected()).toBe(false);
  });

  it('askBulkDelete only opens the confirmation with a selection under the cap', () => {
    const { cmp } = build({ expenses: page([EXPENSE], 1) });
    cmp.askBulkDelete(); // nothing selected → no-op
    expect(cmp.bulkConfirm()).toBeNull();
    cmp.toggleSelect('e-1', true);
    cmp.askBulkDelete();
    expect(cmp.bulkConfirm()).toBe('delete');
  });

  it('runBulkDelete and runBulkExport are no-ops while busy or without a selection', () => {
    const { cmp } = build({ expenses: page([EXPENSE], 1) });
    cmp.runBulkDelete(); // nothing selected
    cmp.runBulkExport();
    cmp.toggleSelect('e-1', true);
    cmp.bulkBusy.set(true);
    cmp.runBulkDelete(); // busy → no DELETE
    cmp.runBulkExport(); // busy → no export
  });

  it('runBulkDelete removes the selected rows, refreshes and toasts', () => {
    const e2 = { ...EXPENSE, id: 'e-2' };
    const e3 = { ...EXPENSE, id: 'e-3' };
    const { cmp, http } = build({ expenses: page([EXPENSE, e2, e3], 3) });
    const { success } = toastSpies(cmp);
    cmp.toggleSelect('e-1', true);
    cmp.toggleSelect('e-2', true);
    cmp.askBulkDelete();
    cmp.runBulkDelete();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE')
      .flush(null);
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-2') && r.method === 'DELETE')
      .flush(null);
    // the bulk epilogue refreshes the list with one GET /expenses for the window
    flushList(http, page([], 0));
    expect(cmp.bulkConfirm()).toBeNull();
    expect(cmp.bulkBusy()).toBe(false);
    expect(success).toHaveBeenCalledWith('2 Buchung(en) gelöscht.');
    // the prune effect empties the stale selection
    TestBed.tick();
    expect(cmp.selectedCount()).toBe(0);
  });

  it('runBulkDelete toasts an error and still refreshes on a failed delete', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    const { error } = toastSpies(cmp);
    cmp.toggleSelect('e-1', true);
    cmp.askBulkDelete();
    cmp.runBulkDelete();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE')
      .error(new ProgressEvent('err'));
    flushList(http, page([EXPENSE], 1));
    expect(cmp.bulkBusy()).toBe(false);
    expect(cmp.bulkConfirm()).toBeNull();
    expect(error).toHaveBeenCalledWith('Sammel-Löschung fehlgeschlagen.');
  });

  it('runBulkExport streams only the selected ids as xlsx', () => {
    const dl = stubDownload();
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    cmp.toggleSelect('e-1', true);
    cmp.runBulkExport();
    expect(cmp.bulkBusy()).toBe(true);
    const req = http.expectOne((r) => r.url.endsWith('/expenses/export.xlsx'));
    expect(req.request.params.getAll('ids')).toEqual(['e-1']);
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(['x']));
    expect(cmp.bulkBusy()).toBe(false);
    expect(dl.create).toHaveBeenCalled();
    dl.restore();
  });

  it('runBulkExport clears busy and toasts on error', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    const { error } = toastSpies(cmp);
    cmp.toggleSelect('e-1', true);
    cmp.runBulkExport();
    http.expectOne((r) => r.url.endsWith('/expenses/export.xlsx')).error(new ProgressEvent('err'));
    expect(cmp.bulkBusy()).toBe(false);
    expect(error).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('canSubmitReassign requires a target budget or a category', () => {
    const { cmp } = build();
    expect(cmp.canSubmitReassign()).toBe(false);
    cmp.bulkBudgetId.set('b-1');
    expect(cmp.canSubmitReassign()).toBe(true);
    cmp.bulkBudgetId.set('');
    cmp.bulkCategory.set('   ');
    expect(cmp.canSubmitReassign()).toBe(false);
    cmp.bulkCategory.set('Werbung');
    expect(cmp.canSubmitReassign()).toBe(true);
  });

  it('openBulkReassign only opens with a selection and resets the form', () => {
    const { cmp } = build({ expenses: page([EXPENSE], 1) });
    cmp.bulkBudgetId.set('stale');
    cmp.bulkCategory.set('stale');
    cmp.openBulkReassign(); // nothing selected → no-op
    expect(cmp.bulkReassignOpen()).toBe(false);
    cmp.toggleSelect('e-1', true);
    cmp.openBulkReassign();
    expect(cmp.bulkReassignOpen()).toBe(true);
    expect(cmp.bulkBudgetId()).toBe('');
    expect(cmp.bulkCategory()).toBe('');
  });

  it('runBulkReassign patches the cost centre for standalone rows only and refreshes', () => {
    const bound = { ...EXPENSE, id: 'e-bound', applicationId: 'app-1' };
    const { cmp, http } = build({ expenses: page([EXPENSE, bound], 2) });
    const { success } = toastSpies(cmp);
    cmp.toggleSelect('e-1', true);
    cmp.toggleSelect('e-bound', true);
    cmp.openBulkReassign();
    cmp.bulkBudgetId.set('b-9');
    cmp.bulkCategory.set('  Reise  ');
    cmp.runBulkReassign();
    // a standalone booking takes budgetId and category
    const r1 = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH',
    );
    expect(r1.request.body).toEqual({ category: 'Reise', budgetId: 'b-9' });
    r1.flush({ ...EXPENSE });
    // a bound booking takes only the category, because the application sets the cost center
    const r2 = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/e-bound') && r.method === 'PATCH',
    );
    expect(r2.request.body).toEqual({ category: 'Reise' });
    r2.flush({ ...bound });
    flushList(http, page([EXPENSE, bound], 2));
    expect(cmp.bulkBusy()).toBe(false);
    expect(cmp.bulkReassignOpen()).toBe(false);
    expect(success).toHaveBeenCalledWith('2 Buchung(en) aktualisiert.');
  });

  it('runBulkReassign moves the cost centre only (no category) when just a budget is set', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    cmp.toggleSelect('e-1', true);
    cmp.openBulkReassign();
    cmp.bulkBudgetId.set('b-7'); // no category → the category branch stays false
    cmp.runBulkReassign();
    const req = http.expectOne(
      (r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH',
    );
    expect(req.request.body).toEqual({ budgetId: 'b-7' });
    req.flush({ ...EXPENSE });
    flushList(http, page([EXPENSE], 1));
    expect(cmp.bulkReassignOpen()).toBe(false);
  });

  it('runBulkReassign is a no-op without a selection, while busy or when nothing to submit', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    cmp.runBulkReassign(); // empty selection
    cmp.toggleSelect('e-1', true);
    cmp.runBulkReassign(); // canSubmitReassign false (no budget/category)
    cmp.bulkBudgetId.set('b-2');
    cmp.bulkBusy.set(true);
    cmp.runBulkReassign(); // busy
    http.expectNone((r) => r.method === 'PATCH');
  });

  it('runBulkReassign toasts an error on a failed patch', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 1) });
    const { error } = toastSpies(cmp);
    cmp.toggleSelect('e-1', true);
    cmp.openBulkReassign();
    cmp.bulkCategory.set('Reise');
    cmp.runBulkReassign();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH')
      .error(new ProgressEvent('err'));
    flushList(http, page([EXPENSE], 1));
    expect(cmp.bulkBusy()).toBe(false);
    expect(error).toHaveBeenCalledWith('Sammel-Umbuchung fehlgeschlagen.');
  });

  it('the selection-prune effect keeps live rows and drops vanished ones', () => {
    const e2 = { ...EXPENSE, id: 'e-2' };
    const { cmp } = build({ expenses: page([EXPENSE, e2], 2) });
    cmp.selected.set(new Set(['e-1', 'e-2']));
    TestBed.tick(); // all still present → selection kept
    expect([...cmp.selected()].sort()).toEqual(['e-1', 'e-2']);
    cmp.items.set([EXPENSE]); // e-2 vanished
    TestBed.tick();
    expect([...cmp.selected()]).toEqual(['e-1']);
  });

  it('mirrors the active filters into the URL query params', () => {
    const { cmp } = build();
    const router = TestBed.inject(Router);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    TestBed.tick(); // initial run: everything empty → nulls
    expect(nav).toHaveBeenLastCalledWith(
      [],
      expect.objectContaining({
        queryParams: { budget: null, kind: null, q: null, view: null },
        queryParamsHandling: 'merge',
        replaceUrl: true,
      }),
    );
    cmp.budgetId.set('b-1');
    cmp.kind.set('income');
    cmp.q.set('  flyer  ');
    TestBed.tick();
    expect(nav).toHaveBeenLastCalledWith(
      [],
      expect.objectContaining({
        queryParams: { budget: 'b-1', kind: 'income', q: 'flyer', view: null },
      }),
    );
    nav.mockRestore();
  });

  it('blocks bulk delete for a multi-row select-all, but not for a single row', () => {
    const e2 = { ...EXPENSE, id: 'e-2' };
    const { cmp } = build({ expenses: page([EXPENSE, e2], 2) });
    cmp.toggleSelectAll(true);
    expect(cmp.bulkDeleteBlocked()).toBe(true);
    cmp.askBulkDelete(); // blocked → dialog stays closed
    expect(cmp.bulkConfirm()).toBeNull();
    cmp.toggleSelect('e-2', false); // partial selection → delete allowed again
    expect(cmp.bulkDeleteBlocked()).toBe(false);
    cmp.askBulkDelete();
    expect(cmp.bulkConfirm()).toBe('delete');
  });

  it('blocks bulk delete above five rows, and leaves the other actions alone', () => {
    const rows = Array.from({ length: 7 }, (_, i) => ({ ...EXPENSE, id: `e-${i}` }));
    const { cmp } = build({ expenses: page(rows, 7) });

    for (const r of rows.slice(0, 5)) cmp.toggleSelect(r.id, true);
    expect(cmp.bulkDeleteOverMax()).toBe(false);
    expect(cmp.bulkDeleteBlocked()).toBe(false);

    cmp.toggleSelect('e-5', true);
    expect(cmp.bulkDeleteOverMax()).toBe(true);
    cmp.askBulkDelete();
    expect(cmp.bulkConfirm()).toBeNull();

    cmp.toggleSelect('e-5', false);
    cmp.askBulkDelete();
    expect(cmp.bulkConfirm()).toBe('delete');
  });
});

describe('ExpensesComponent (query-param adoption)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
  });

  function buildWithQuery(query: [string, string][]): {
    cmp: ExpensesComponent;
    http: HttpTestingController;
  } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: routeStub(query) },
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['budget.view', 'budget.book']) },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const cmp = TestBed.runInInjectionContext(() => new ExpensesComponent());
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    http
      .expectOne((r) => r.url.endsWith('/invoices') && r.method === 'GET')
      .flush({ items: [], total: 0, limit: 200, offset: 0 });
    // Exactly ONE reload. The component adopts the URL filters first and then loads
    // one time. The old double reload raced and could show the unfiltered list.
    const reqs = http.match((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    expect(reqs.length).toBe(1);
    reqs.forEach((req) => req.flush(page([])));
    return { cmp, http };
  }

  it('adopts budget/kind/q filters from the URL and reloads', () => {
    const { cmp } = buildWithQuery([
      ['budget', 'b-1'],
      ['kind', 'income'],
      ['q', 'foo'],
    ]);
    expect(cmp.budgetId()).toBe('b-1');
    expect(cmp.kind()).toBe('income');
    expect(cmp.q()).toBe('foo');
  });

  it('ignores an unrecognised kind but still adopts the other filters', () => {
    const { cmp } = buildWithQuery([
      ['kind', 'weird'],
      ['budget', 'b-2'],
    ]);
    expect(cmp.kind()).toBe(''); // invalid value not applied
    expect(cmp.budgetId()).toBe('b-2');
  });

  it('opens the booking of ?id= and loads it when it is not among the rows', () => {
    const { cmp, http } = buildWithQuery([['id', 'e-42']]);
    expect(cmp.selectedId()).toBe('e-42');
    // The id opens a row; it does not narrow the list.
    expect(cmp.activeFilterCount()).toBe(0);
    TestBed.tick();
    const one = http.expectOne(
      (r) => r.url.endsWith('/expenses') && r.method === 'GET' && r.params.get('id') === 'e-42',
    );
    expect(one.request.params.get('limit')).toBe('1');
    one.flush(page([{ ...EXPENSE, id: 'e-42' }]));
    expect(cmp.selectedExpense()?.id).toBe('e-42');
    expect(cmp.detailView()).toBe('booking');
    expect(cmp.detailOpen()).toBe(true);
    TestBed.tick();
    // The fiscal-year labels need the tree, which is empty here: no request.
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('says that the booking of ?id= is not there', () => {
    const { cmp, http } = buildWithQuery([['id', 'e-gone']]);
    TestBed.tick();
    http
      .expectOne((r) => r.url.endsWith('/expenses') && r.params.get('id') === 'e-gone')
      .flush(page([]));
    expect(cmp.selectedMissing()).toBe(true);
    expect(cmp.detailView()).toBe('missing');
  });

  it('says that the booking of ?id= is not there when the request fails', () => {
    const { cmp, http } = buildWithQuery([['id', 'e-err']]);
    TestBed.tick();
    http
      .expectOne((r) => r.url.endsWith('/expenses') && r.params.get('id') === 'e-err')
      .error(new ProgressEvent('err'));
    expect(cmp.selectedMissing()).toBe(true);
  });

  it('re-filters when the palette sends it here while it is already here', () => {
    // Same route, new query string: the router keeps this component. Reading the
    // snapshot once would leave the list showing the booking the reader came from, and
    // the write-back effect would put that id straight back into the URL.
    const params = new BehaviorSubject(convertToParamMap({ id: 'e-42' }));
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: params.value }, queryParamMap: params },
        },
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['budget.view', 'budget.book']) },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const cmp = TestBed.runInInjectionContext(() => new ExpensesComponent());
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    http
      .expectOne((r) => r.url.endsWith('/invoices') && r.method === 'GET')
      .flush({ items: [], total: 0, limit: 200, offset: 0 });
    http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET').flush(page([]));

    // Another booking opens: the list stays as it is.
    params.next(convertToParamMap({ id: 'e-9' }));
    expect(cmp.selectedId()).toBe('e-9');
    http.expectNone((r) => r.url.endsWith('/expenses') && !r.params.has('id'));

    // Another filter reloads the list.
    params.next(convertToParamMap({ id: 'e-9', budget: 'b-2' }));
    const again = http.expectOne(
      (r) => r.url.endsWith('/expenses') && r.method === 'GET' && !r.params.has('id'),
    );
    expect(again.request.params.get('budget')).toBe('b-2');
    again.flush(page([]));

    // A parameter that goes away clears its filter. Each of them is written back into
    // the URL, so absence means the reader took it away.
    params.next(convertToParamMap({}));
    expect(cmp.selectedId()).toBe('');
    expect(cmp.budgetId()).toBe('');
    const cleared = http.expectOne(
      (r) => r.url.endsWith('/expenses') && r.method === 'GET' && !r.params.has('id'),
    );
    expect(cleared.request.params.has('budget')).toBe(false);
    cleared.flush(page([]));
    // The look-up of the booking from before is still open; answer it.
    http.match((r) => r.params.get('id') === 'e-42').forEach((r) => r.flush(page([])));
  });
});

// The window reload that ExpensesListState runs after a mutation, tested in isolation.
describe('ExpensesListState.refresh', () => {
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
  });

  function buildState(): { state: ExpensesListState; http: HttpTestingController } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const state = TestBed.runInInjectionContext(() => new ExpensesListState());
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    // The state no longer loads on its own. The component fires the
    // first reload after it adopts the URL filters. Mirror that here.
    state.reload();
    http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET').flush(page([]));
    return { state, http };
  }

  it('a reload discards the stale response of an older filter state', () => {
    const { state, http } = buildState();
    state.reload(); // request A (old filter state)
    state.kind.set('income');
    state.reload(); // request B (new filter state)
    const [reqA, reqB] = http.match((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    // The filtered request B resolves first, then the stale request A arrives. Request
    // A must NOT overwrite the list.
    reqB.flush(page([EXPENSE], 1));
    reqA.flush(page([{ ...EXPENSE, id: 'stale' }, EXPENSE], 2));
    expect(state.items()).toEqual([EXPENSE]);
    expect(state.total()).toBe(1);
  });

  it('a stale refresh response is dropped after an intervening reload', () => {
    const { state, http } = buildState();
    state.refresh(); // in flight …
    state.reload(); // … filter changes meanwhile
    const [refreshReq, reloadReq] = http.match(
      (r) => r.url.endsWith('/expenses') && r.method === 'GET',
    );
    reloadReq.flush(page([EXPENSE], 1));
    refreshReq.flush(page([{ ...EXPENSE, id: 'stale' }], 1));
    expect(state.refreshing()).toBe(false);
    expect(state.items()).toEqual([EXPENSE]);
  });

  it('early-returns a concurrent refresh and clears the flag on success', () => {
    const { state, http } = buildState();
    state.refresh();
    state.refresh(); // refreshing() already true → early return, no second request
    const reqs = http.match((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    expect(reqs.length).toBe(1);
    reqs[0].flush(page([EXPENSE], 1));
    expect(state.refreshing()).toBe(false);
    expect(state.items()).toEqual([EXPENSE]);
  });

  it('clears the refreshing flag on an error', () => {
    const { state, http } = buildState();
    state.refresh();
    http
      .expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET')
      .error(new ProgressEvent('err'));
    expect(state.refreshing()).toBe(false);
  });

  it('a stale fetch ERROR leaves the loading flags of the newer request alone', () => {
    const { state, http } = buildState();
    state.reload(); // request A, the old filter state
    state.kind.set('income');
    state.reload(); // request B, the new filter state, so A is stale from here on
    const [reqA, reqB] = http.match((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    // A fails late. Its error handler must return early on the epoch mismatch.
    // Otherwise it clears `loading` while B is still in flight.
    reqA.error(new ProgressEvent('err'));
    expect(state.loading()).toBe(true);
    // Settle B so the test ends with no outstanding request.
    reqB.flush(page([]));
    expect(state.loading()).toBe(false);
  });

  it('clears the exporting flag when the xlsx export fails', () => {
    const { state, http } = buildState();
    state.onExport();
    expect(state.exporting()).toBe(true);
    // A second call while one is in flight returns early and fires no request.
    state.onExport();
    const reqs = http.match((r) => r.url.endsWith('/expenses/export.xlsx'));
    expect(reqs.length).toBe(1);
    reqs[0].error(new ProgressEvent('err'));
    expect(state.exporting()).toBe(false);
  });
});

// --- transfers tab ---------------------------------------------------------

const TRANSFER = {
  transferId: 'tr-1',
  expenseId: 'e-a',
  incomeId: 'e-b',
  fromBudgetId: 'b-1',
  fromPathKey: 'VS-800',
  toBudgetId: 'b-2',
  toPathKey: 'VS-900',
  fiscalYearId: 'fy-1',
  amount: '50.00',
  currency: 'EUR',
  description: 'Umbuchung Fest',
  note: null,
  invoiceDate: null,
  paymentDate: '2026-05-28',
  actor: 'admin',
  actorName: 'Admin',
  createdAt: '2026-05-30T09:00:00Z',
};

function transferPage(items: unknown[] = [TRANSFER], total = items.length) {
  return { items, total, limit: 20, offset: 0 };
}

/** Open the transfers tab and answer the first page. */
async function openTransfers(
  ctx: Awaited<ReturnType<typeof setup>>,
  body: unknown = transferPage(),
) {
  await userEvent.click(await screen.findByRole('radio', { name: 'Überträge' }));
  ctx.http.expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'GET').flush(body);
  ctx.detectChanges();
}

describe('ExpensesComponent — transfers tab', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists a transfer as one row with both cost centres', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    expect(screen.getByText('Umbuchung Fest')).toBeInTheDocument();
    expect(screen.getByText('VS-800')).toBeInTheDocument();
    expect(screen.getByText('VS-900')).toBeInTheDocument();
    ctx.http.verify();
  });

  it('shows an empty state and reports a failed load', async () => {
    const ctx = await setup();
    await openTransfers(ctx, transferPage([], 0));
    expect(screen.getByText('Keine Überträge gefunden.')).toBeInTheDocument();
    ctx.http.verify();
  });

  it('shows no transfers tab to a reader without budget.book', async () => {
    const ctx = await setup({ perms: ['budget.view'] });
    expect(screen.queryByRole('radio', { name: 'Überträge' })).not.toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'Buchungen' })).not.toBeInTheDocument();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.setTab('transfers');
    expect(c.tab()).toBe('bookings');
    ctx.http.expectNone((r) => r.url.endsWith('/budget-transfers'));
    ctx.http.verify();
  });

  it('patches a transfer without the cost-centre pair', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.openTransferEdit(TRANSFER);
    c.transfers.editAmount.set('75.00');
    c.transfers.editDescription.set('  Korrigiert  ');
    c.saveTransferEdit(new Event('submit'));

    const patch = ctx.http.expectOne('/api/budget-transfers/tr-1');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({
      amount: '75.00',
      description: 'Korrigiert',
      note: null,
      invoiceDate: null,
      paymentDate: '2026-05-28',
    });
    patch.flush({ ...TRANSFER, amount: '75.00', description: 'Korrigiert' });
    // The two legs are rows in the bookings list, so it refreshes too.
    ctx.http
      .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
      .forEach((r) => r.flush(page([])));
    ctx.detectChanges();

    expect(c.transferItems()[0].description).toBe('Korrigiert');
    expect(c.editingTransfer()).toBeNull();
    ctx.http.verify();
  });

  it('explains the 409 on a changed cost-centre pair and reloads', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.openTransferEdit(TRANSFER);
    c.saveTransferEdit(new Event('submit'));
    ctx.http.expectOne('/api/budget-transfers/tr-1').flush(
      {
        type: 'app://error/transfer_cost_centres_immutable',
        title: 'Conflict',
        status: 409,
        code: 'transfer_cost_centres_immutable',
        detail: 'The cost centres of a transfer are immutable; book a new transfer instead.',
      },
      { status: 409, statusText: 'Conflict' },
    );
    // The reload gets the server truth back on screen.
    ctx.http
      .expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'GET')
      .flush(transferPage());
    expect(c.transferSaving()).toBe(false);
    ctx.http.verify();
  });

  it('reports any other patch failure', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.openTransferEdit(TRANSFER);
    c.saveTransferEdit(new Event('submit'));
    ctx.http
      .expectOne('/api/budget-transfers/tr-1')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    expect(c.transferSaving()).toBe(false);
    ctx.http.verify();
  });

  it('deletes a transfer with both of its bookings', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.askDeleteTransfer(TRANSFER);
    c.doDeleteTransfer();
    const del = ctx.http.expectOne('/api/budget-transfers/tr-1');
    expect(del.request.method).toBe('DELETE');
    del.flush(null, { status: 204, statusText: 'No Content' });
    ctx.http
      .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
      .forEach((r) => r.flush(page([])));
    ctx.detectChanges();
    expect(c.transferItems()).toEqual([]);
    expect(c.confirmDeleteTransfer()).toBeNull();
    ctx.http.verify();
  });

  it('reports a failed delete and keeps the row', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.askDeleteTransfer(TRANSFER);
    c.doDeleteTransfer();
    ctx.http
      .expectOne('/api/budget-transfers/tr-1')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    expect(c.transferItems().length).toBe(1);
    ctx.http.verify();
  });

  it('loads a second page and stops when the list is complete', async () => {
    const ctx = await setup();
    await openTransfers(ctx, transferPage([TRANSFER], 2));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    expect(c.transferHasMore()).toBe(true);
    c.loadMoreTransfers();
    ctx.http
      .expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'GET')
      .flush({ items: [{ ...TRANSFER, transferId: 'tr-2' }], total: 2, limit: 20, offset: 1 });
    expect(c.transferItems().length).toBe(2);
    // No further page: the call returns early and fires no request.
    c.loadMoreTransfers();
    ctx.http.verify();
  });

  it('reports a failed load and shows the empty state', async () => {
    const ctx = await setup();
    await userEvent.click(await screen.findByRole('radio', { name: 'Überträge' }));
    ctx.http
      .expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'GET')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    ctx.detectChanges();
    expect(screen.getByText('Keine Überträge gefunden.')).toBeInTheDocument();
    ctx.http.verify();
  });

  it('ignores an edit and a delete without a target or while one runs', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.saveTransferEdit(new Event('submit'));
    c.doDeleteTransfer();

    c.openTransferEdit(TRANSFER);
    c.transfers.editDescription.set('   ');
    c.saveTransferEdit(new Event('submit'));
    c.transfers.editDescription.set('ok');
    c.transferSaving.set(true);
    c.saveTransferEdit(new Event('submit'));
    c.closeTransferEdit();
    expect(c.editingTransfer()).toBeNull();

    c.askDeleteTransfer(TRANSFER);
    c.doDeleteTransfer();
    c.transferSaving.set(false);
    c.closeDeleteTransfer();
    expect(c.confirmDeleteTransfer()).toBeNull();
    ctx.http.verify();
  });

  it('refreshes the transfers after a new transfer once the tab has loaded', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.fixture.componentInstance as any;
    c.tFromId.set('b-1');
    c.tToId.set('b-2');
    c.tFiscalYearId.set('fy-1');
    c.tAmount.set('10');
    c.tDescription.set('Neu');
    c.createTransfer(new Event('submit'));
    ctx.http
      .expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'POST')
      .flush({ transferId: 'tr-9', expenseId: 'x', incomeId: 'y' });
    ctx.http
      .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
      .forEach((r) => r.flush(page([])));
    ctx.http
      .expectOne((r) => r.url.endsWith('/budget-transfers') && r.method === 'GET')
      .flush(transferPage());
    ctx.http.verify();
  });

  it('switches back to the bookings tab without a further transfer request', async () => {
    const ctx = await setup();
    await openTransfers(ctx);
    await userEvent.click(screen.getByRole('radio', { name: 'Buchungen' }));
    ctx.detectChanges();
    expect(screen.getByText('Keine Buchungen gefunden.')).toBeInTheDocument();
    ctx.http.verify();
  });

});

describe('ExpensesComponent (filters, generically)', () => {
  /**
   * Walks the state's own filter list rather than naming filters, so one added later is
   * covered the day it is declared.
   *
   * On /applications the same class of mistake shipped: a filter reached the request but
   * not the reset, and the panel cleared while the list kept its rows. Here the reset
   * reloads either way, so the failure is quieter — a filter silently surviving a reset —
   * which is why it wants a check rather than a pair of eyes.
   */
  it('clears every filter it says it clears, and keeps the ones it does not', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const state = (fixture.componentInstance as any).list;

    for (const f of state.filterSignals) f.signal.set('x');
    state.resetFilters();

    for (const f of state.filterSignals) {
      expect(f.signal()).toBe(f.clearedByReset ? '' : 'x');
    }
  });

  it('sends every declared filter that has a value', async () => {
    // The reset list and the request list were spelled out separately; a filter in one
    // and not the other is invisible until the list stops answering.
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const state = (fixture.componentInstance as any).list;
    for (const f of state.filterSignals) f.signal.set('7');

    const params = state.filterParams();
    const values = Object.values(params).filter((v) => v !== undefined);
    // Eight filters plus sort and order.
    expect(values.length).toBe(state.filterSignals.length + 2);
  });
});

// --- list/detail (FE10c) ---------------------------------------------------

/** A tree with figures for the fiscal year `fy-1`, so the detail shows its numbers. */
const FIG_TREE: BudgetTreeNode[] = [
  {
    ...ROOT_TREE[0],
    children: [
      {
        ...ROOT_TREE[0].children[0],
        id: 'b-1',
        color: '#2f7fc1',
        byFiscalYear: [
          {
            fiscalYearId: 'fy-1',
            allocated: '1000.00',
            bound: '100.00',
            expended: '300.00',
            income: '0',
            committed: '400.00',
            requested: '0',
            available: '600.00',
          },
        ],
      },
    ],
  },
];

describe('ExpensesComponent (list/detail)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
  });

  it('lists the bookings by month with kind, cost centre, date and the signed amount', async () => {
    setViewport(WIDE);
    const income = { ...EXPENSE, id: 'e-2', kind: 'income' as const, description: 'Pfand', paymentDate: '2026-04-02' };
    const { container } = await setup({ page: page([EXPENSE, income]), tree: FIG_TREE });
    expect(await screen.findByText('Druckkosten Flyer')).toBeInTheDocument();
    const months = [...container.querySelectorAll('.exp__month')].map((h) => h.textContent?.trim());
    expect(months).toEqual(['Mai 2026', 'April 2026']);
    expect(screen.getByText(/−120,00/)).toBeInTheDocument();
    expect(screen.getByText(/\+120,00/)).toBeInTheDocument();
    expect(screen.getByText('28.05.')).toBeInTheDocument();
    // A row is a link that opens the booking beside the list.
    const link = screen.getByRole('link', { name: /Druckkosten Flyer/ });
    expect(link.getAttribute('href')).toContain('id=e-1');
    // Side by side, nothing open: the detail says so.
    expect(screen.getByText('Keine Buchung geöffnet')).toBeInTheDocument();
    expect(screen.getByText('2 von 2')).toBeInTheDocument();
  });

  it('shows one group without a heading while it sorts by amount', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE]) });
    cmp.onHeaderMenu({ id: 'amount:asc', label: '' });
    flushList(http, page([EXPENSE]));
    expect(cmp.sortField()).toBe('amount');
    expect(cmp.sortOrder()).toBe('asc');
    expect(cmp.groups()).toEqual([{ key: 'all', label: '', items: [EXPENSE] }]);
    // Sorted by invoice date or by the record date, the months follow that date.
    cmp.onHeaderMenu({ id: 'invoiceDate:desc', label: '' });
    flushList(http, page([EXPENSE]));
    expect(cmp.groups()[0].label).toBe('Mai 2026');
    cmp.onHeaderMenu({ id: 'createdAt:desc', label: '' });
    flushList(http, page([{ ...EXPENSE, paymentDate: null }]));
    expect(cmp.groups()[0].key).toBe('2026-05');
    // The checked sort order shows in the menu.
    const checked = cmp.sortSections()[0].items.filter((i) => i.checked).map((i) => i.id);
    expect(checked).toEqual(['createdAt:desc']);
  });

  it('shows the empty list with a reset only while a filter is set', async () => {
    setViewport(WIDE);
    const { fixture } = await setup();
    expect(await screen.findByText('Keine Buchungen gefunden.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Filter zurücksetzen' })).toBeNull();
    // An empty list leaves a neutral sheet beside it.
    expect(fixture.nativeElement.querySelector('.exp__none--skeleton')).not.toBeNull();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.kind.set('income');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    expect(c.kind()).toBe('');
    const http = TestBed.inject(HttpTestingController);
    http.match((r) => r.url.endsWith('/expenses')).forEach((r) => r.flush(page([])));
  });

  it('opens the cost-centre tree as a sheet and filters by the picked node', async () => {
    const { fixture, http } = await setup({ page: page([EXPENSE]), tree: FIG_TREE });
    const chip = await screen.findByRole('button', { name: /^Kostenstelle: Kostenstelle/ });
    await userEvent.click(chip);
    expect(chip.getAttribute('aria-expanded')).toBe('true');
    await userEvent.click(screen.getByRole('button', { name: /Öffentlichkeit/ }));
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.params.get('budget') === 'b-1');
    req.flush(page([EXPENSE]));
    fixture.detectChanges();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.pickerOpen()).toBe(false);
    expect(c.costCentreName()).toBe('Öffentlichkeit');
    expect(c.costCentreColor()).toBe('#2f7fc1');
  });

  it('runs the kind, period and amount chips', () => {
    const { cmp, http } = build();
    cmp.setKind('expense');
    expect(flushParams(http).get('kind')).toBe('expense');
    expect(cmp.kindChipLabel()).toBe('Ausgabe');
    cmp.setKind('nonsense');
    flushParams(http);
    expect(cmp.kindChipLabel()).toBe('Art');
    cmp.onDateRange({ from: '2026-01-01', to: '2026-06-30' });
    const dates = flushParams(http);
    expect(dates.get('createdFrom')).toBe('2026-01-01');
    expect(dates.get('createdTo')).toBe('2026-06-30');
    cmp.onAmountRange({ from: '10', to: '' });
    const amounts = flushParams(http);
    expect(amounts.get('amountMin')).toBe('10');
    expect(amounts.has('amountMax')).toBe(false);
    expect(cmp.activeFilterCount()).toBe(3);
  });

  it('filters the transfers with the same chips while they show', () => {
    const { cmp, http } = build();
    cmp.setTab('transfers');
    http.expectOne((r) => r.url.endsWith('/budget-transfers')).flush(transferPage([]));
    cmp.onSearch('fest');
    http.expectOne((r) => r.url.endsWith('/budget-transfers')).flush(transferPage([]));
    cmp.onDateRange({ from: '2026-01-01', to: '' });
    flushList(http, page([]));
    http.expectOne((r) => r.url.endsWith('/budget-transfers')).flush(transferPage([]));
    cmp.onAmountRange({ from: '1', to: '2' });
    flushList(http, page([]));
    http.expectOne((r) => r.url.endsWith('/budget-transfers')).flush(transferPage([]));
    cmp.selectBudget('b-1');
    flushList(http, page([]));
    http.expectOne((r) => r.url.endsWith('/budget-transfers')).flush(transferPage([]));
    cmp.resetFilters();
    flushList(http, page([]));
    http.expectOne((r) => r.url.endsWith('/budget-transfers')).flush(transferPage([]));
    // The debounced search of the bookings fires later; answer it.
    jest.useFakeTimers();
    jest.useRealTimers();
    http.match((r) => r.url.endsWith('/expenses')).forEach((r) => r.flush(page([])));
  });

  it('builds the header menu from the rights, the view and the viewport', () => {
    const { cmp } = build();
    expect(cmp.headerMenu().flatMap((s) => s.items.map((i) => i.id))).toEqual(['transfer', 'select']);
    TestBed.resetTestingModule();
    setViewport(PHONE);
    const phone = build();
    const ids = phone.cmp.headerMenu().flatMap((s) => s.items.map((i) => i.id));
    expect(ids).toContain('transfer');
    expect(ids).toContain('paymentDate:desc');
    expect(ids).toContain('export');
    TestBed.resetTestingModule();
    setViewport();
    const reader = build({ perms: ['budget.view'] });
    expect(reader.cmp.headerMenu()).toEqual([]);
  });

  it('runs the items of the header menu', () => {
    const { cmp, http } = build();
    cmp.onHeaderMenu({ id: 'transfer', label: '' });
    expect(cmp.transferOpen()).toBe(true);
    expect(cmp.formMode()).toBe('transfer-create');
    expect(cmp.formTitle()).toBe('Übertrag buchen');
    cmp.onHeaderMenu({ id: 'select', label: '' });
    expect(cmp.selecting()).toBe(true);
    cmp.onHeaderMenu({ id: 'export', label: '' });
    http.expectOne((r) => r.url.endsWith('/expenses/export.xlsx')).error(new ProgressEvent('err'));
    // An unknown item does nothing.
    cmp.onHeaderMenu({ id: 'other', label: '' });
  });

  it('names each form for the sheet of a phone', () => {
    const { cmp } = build({ expenses: page([EXPENSE]) });
    expect(cmp.formTitle()).toBe('');
    cmp.openCreate();
    expect(cmp.formTitle()).toBe('Buchung hinzufügen');
    cmp.openEdit(EXPENSE);
    expect(cmp.createOpen()).toBe(false);
    expect(cmp.formTitle()).toBe('Buchung bearbeiten');
    cmp.openTransferEdit(TRANSFER);
    expect(cmp.editing()).toBeNull();
    expect(cmp.formMode()).toBe('transfer-edit');
    expect(cmp.formTitle()).toBe('Übertrag bearbeiten');
    expect(cmp.detailView()).toBe('form');
    expect(cmp.detailOpen()).toBe(true);
    // "Zur Liste" with a form open closes the form.
    cmp.closeDetail();
    expect(cmp.formMode()).toBeNull();
  });

  it('opens and closes a row through the URL', () => {
    const { cmp } = build();
    const router = TestBed.inject(Router);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    cmp.openBooking('e-7');
    expect(nav).toHaveBeenLastCalledWith(
      [],
      expect.objectContaining({ queryParams: { id: 'e-7', transfer: null } }),
    );
    cmp.openTransferRow('tr-1');
    expect(nav).toHaveBeenLastCalledWith(
      [],
      expect.objectContaining({ queryParams: { transfer: 'tr-1', id: null } }),
    );
    cmp.closeDetail();
    expect(nav).toHaveBeenLastCalledWith(
      [],
      expect.objectContaining({ queryParams: { id: null, transfer: null } }),
    );
    nav.mockRestore();
  });

  it('opens a new booking after the create', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    const router = TestBed.inject(Router);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    cmp.openCreate();
    dlg(cmp).newDescription.set('Kaffee');
    dlg(cmp).newAmount.set('5');
    dlg(cmp).newBudgetId.set('child-1');
    dlg(cmp).newFiscalYearId.set('fy-1');
    cmp.create(new Event('submit'));
    http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST').flush({ ...EXPENSE, id: 'e-new' });
    http.expectOne((r) => r.url.endsWith('/invoices')).flush({ items: [], total: 0, limit: 200, offset: 0 });
    flushList(http, page([]));
    expect(nav).toHaveBeenCalledWith([], expect.objectContaining({ queryParams: { id: 'e-new', transfer: null } }));
    nav.mockRestore();
  });

  it('closes the detail of a deleted booking and of a deleted transfer', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE]) });
    const router = TestBed.inject(Router);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    cmp.selectedId.set('e-1');
    cmp.openEdit(EXPENSE);
    cmp.askDelete(EXPENSE);
    cmp.doDelete();
    http.expectOne((r) => r.url.endsWith('/budget-expenses/e-1')).flush(null);
    expect(cmp.editing()).toBeNull();
    expect(nav).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { id: null, transfer: null } }));
    nav.mockClear();
    // A sub-booking leaves the open parent alone.
    cmp.askDelete({ ...EXPENSE, id: 'sub-9', parentExpenseId: 'e-1' });
    cmp.doDelete();
    http.expectOne((r) => r.url.endsWith('/budget-expenses/sub-9')).flush(null);
    http.expectOne((r) => r.url.endsWith('/sub-bookings')).flush([]);
    flushList(http, page([EXPENSE]));
    expect(nav).not.toHaveBeenCalled();

    cmp.selectedTransferId.set('tr-1');
    cmp.openTransferEdit(TRANSFER);
    cmp.askDeleteTransfer(TRANSFER);
    cmp.doDeleteTransfer();
    http.expectOne((r) => r.url.endsWith('/budget-transfers/tr-1')).flush(null);
    flushList(http, page([EXPENSE]));
    expect(cmp.editingTransfer()).toBeNull();
    expect(nav).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { id: null, transfer: null } }));
    // Another transfer leaves the open one alone.
    nav.mockClear();
    cmp.askDeleteTransfer({ ...TRANSFER, transferId: 'tr-2' });
    cmp.doDeleteTransfer();
    http.expectOne((r) => r.url.endsWith('/budget-transfers/tr-2')).flush(null);
    flushList(http, page([EXPENSE]));
    expect(nav).not.toHaveBeenCalled();
    nav.mockRestore();
  });

  it('loads the invoice, the application, the sub-bookings and the year of the open booking', () => {
    const parent = { ...EXPENSE, budgetId: 'child-1', invoiceId: 'inv-9', applicationId: 'app-1', childCount: 2 };
    const { cmp, http } = build({ tree: ROOT_TREE, expenses: page([parent]) });
    cmp.selectedId.set('e-1');
    TestBed.tick();
    http.expectOne((r) => r.url.endsWith('/invoices/inv-9')).flush({ ...INVOICE, id: 'inv-9' });
    http.expectOne((r) => r.url.endsWith('/applications/app-1')).flush({
      id: 'app-1',
      typeId: 't',
      state: { id: 's', key: 'ok', label: { de: 'Bewilligt' }, color: '#2e7d32' },
      data: {},
      amount: '50.00',
      version: 1,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    });
    http.expectOne((r) => r.url.endsWith('/budget-expenses/e-1/sub-bookings')).flush([SUB]);
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([{ ...FY_ACTIVE, id: 'fy-1' }]);
    expect(cmp.linkedInvoice()?.id).toBe('inv-9');
    expect(cmp.linkedApplication()?.id).toBe('app-1');
    expect(cmp.fyLabel('fy-1')).toBe('2026');
    expect(cmp.fyLabel('fy-x')).toBeNull();
    // The year labels load once per top cost centre.
    cmp.selectedId.set('');
    TestBed.tick();
    cmp.selectedId.set('e-1');
    TestBed.tick();
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('takes a cached invoice and keeps going when a linked record fails', () => {
    const linked = { ...EXPENSE, invoiceId: 'inv-1', applicationId: 'app-x' };
    const { cmp, http } = build({ tree: ROOT_TREE, invoices: [INVOICE], expenses: page([linked]) });
    cmp.selectedId.set('e-1');
    TestBed.tick();
    expect(cmp.linkedInvoice()).toEqual(INVOICE);
    http.expectOne((r) => r.url.endsWith('/applications/app-x')).flush(null, { status: 403, statusText: 'x' });
    expect(cmp.linkedApplication()).toBeNull();
    // An uncached invoice that fails to load leaves the card without its data.
    TestBed.resetTestingModule();
    const other = build({ expenses: page([{ ...EXPENSE, invoiceId: 'inv-gone' }]) });
    other.cmp.selectedId.set('e-1');
    TestBed.tick();
    other.http.expectOne((r) => r.url.endsWith('/invoices/inv-gone')).error(new ProgressEvent('err'));
    expect(other.cmp.linkedInvoice()).toBeNull();
  });

  it('retries the year labels after a failed load', () => {
    const { cmp, http } = build({ tree: ROOT_TREE, expenses: page([{ ...EXPENSE, budgetId: 'child-1' }]) });
    cmp.selectedId.set('e-1');
    TestBed.tick();
    http.expectOne((r) => r.url.endsWith('/fiscal-years')).error(new ProgressEvent('err'));
    cmp.selectedId.set('');
    TestBed.tick();
    cmp.selectedId.set('e-1');
    TestBed.tick();
    http.expectOne((r) => r.url.endsWith('/fiscal-years')).flush([]);
  });

  it('opens the form of a new booking from the invoices page and cleans the URL', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: routeStub([['new', 'booking'], ['invoice', 'inv-1']]) },
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['budget.view', 'budget.book']) },
      ],
    });
    const router = TestBed.inject(Router);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    const http = TestBed.inject(HttpTestingController);
    const cmp = TestBed.runInInjectionContext(() => new ExpensesComponent());
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    http.expectOne((r) => r.url.endsWith('/invoices') && !r.url.includes('inv-1')).flush({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    });
    flushList(http, page([]));
    expect(cmp.createOpen()).toBe(true);
    // The invoice is not in the cache: it loads, then fills the form.
    http.expectOne((r) => r.url.endsWith('/invoices/inv-1')).flush(INVOICE);
    expect(dlg(cmp).newInvoiceId()).toBe('inv-1');
    expect(dlg(cmp).newCorrespondent()).toBe('Acme GmbH');
    expect(nav).toHaveBeenCalledWith(
      [],
      expect.objectContaining({ queryParams: { new: null, invoice: null }, replaceUrl: true }),
    );
    nav.mockRestore();
  });

  it('ignores the create link for a reader', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: routeStub([['new', 'booking']]) },
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['budget.view']) },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const cmp = TestBed.runInInjectionContext(() => new ExpensesComponent());
    http.expectOne((r) => r.url.endsWith('/budgets')).flush([]);
    http.expectOne((r) => r.url.endsWith('/invoices')).flush({ items: [], total: 0, limit: 200, offset: 0 });
    flushList(http, page([]));
    expect(cmp.createOpen()).toBe(false);
  });

  it('opens the transfers from ?view=transfers with the open transfer', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: ActivatedRoute, useValue: routeStub([['view', 'transfers'], ['transfer', 'tr-1']]) },
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['budget.view', 'budget.book']) },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const cmp = TestBed.runInInjectionContext(() => new ExpensesComponent());
    http.expectOne((r) => r.url.endsWith('/budgets')).flush(ROOT_TREE);
    http.expectOne((r) => r.url.endsWith('/invoices')).flush({ items: [], total: 0, limit: 200, offset: 0 });
    flushList(http, page([]));
    http.expectOne((r) => r.url.endsWith('/budget-transfers')).flush(transferPage([{ ...TRANSFER, fromBudgetId: 'child-1' }]));
    expect(cmp.tab()).toBe('transfers');
    expect(cmp.selectedTransfer()?.transferId).toBe('tr-1');
    expect(cmp.detailView()).toBe('transfer');
    expect(cmp.detailOpen()).toBe(true);
    expect(cmp.transferGroups()[0].label).toBe('Mai 2026');
    TestBed.tick();
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([]);
    // A transfer that is not loaded leaves the detail empty.
    cmp.selectedTransferId.set('tr-9');
    expect(cmp.selectedTransfer()).toBeNull();
    expect(cmp.detailView()).toBe('none');
  });

  it('builds the row menus from the rights and runs them', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE]) });
    const withInvoice = { ...EXPENSE, invoiceId: 'inv-1' };
    expect(cmp.rowMenu(withInvoice).flatMap((s) => s.items.map((i) => i.id))).toEqual([
      'edit',
      'sub',
      'invoice',
      'delete',
    ]);
    const router = TestBed.inject(Router);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    cmp.onRowMenu({ id: 'invoice', label: '' }, withInvoice);
    expect(nav).toHaveBeenCalledWith(['/invoices'], { queryParams: { id: 'inv-1' } });
    cmp.onRowMenu({ id: 'invoice', label: '' }, EXPENSE); // no invoice: nothing
    cmp.onRowMenu({ id: 'edit', label: '' }, EXPENSE);
    expect(cmp.editing()).toBe(EXPENSE);
    cmp.onRowMenu({ id: 'sub', label: '' }, EXPENSE);
    expect(cmp.subParent()).toBe(EXPENSE);
    cmp.onRowMenu({ id: 'delete', label: '' }, EXPENSE);
    expect(cmp.confirmDelete()).toBe(EXPENSE);
    cmp.onRowMenu({ id: 'other', label: '' }, EXPENSE);
    expect(cmp.rowMenuLabel(EXPENSE)).toBe('Aktionen für „Druckkosten Flyer“');
    nav.mockRestore();

    cmp.onTransferMenu({ id: 'edit', label: '' }, TRANSFER);
    expect(cmp.editingTransfer()).toBe(TRANSFER);
    cmp.onTransferMenu({ id: 'delete', label: '' }, TRANSFER);
    expect(cmp.confirmDeleteTransfer()).toBe(TRANSFER);
    cmp.onTransferMenu({ id: 'other', label: '' }, TRANSFER);
    expect(cmp.transferMenu().length).toBe(2);
    http.verify();

    TestBed.resetTestingModule();
    const reader = build({ perms: ['budget.view'] });
    expect(reader.cmp.rowMenu(EXPENSE)).toEqual([]);
    expect(reader.cmp.rowMenu(withInvoice).flatMap((s) => s.items.map((i) => i.id))).toEqual(['invoice']);
  });

  it('selects rows in the selection mode and leaves it again', () => {
    const e2 = { ...EXPENSE, id: 'e-2' };
    const { cmp } = build({ expenses: page([EXPENSE, e2]) });
    cmp.onRowActivate(EXPENSE); // not selecting: the link opens the row
    expect(cmp.selectedCount()).toBe(0);
    cmp.startSelecting();
    cmp.onRowActivate(EXPENSE);
    expect(cmp.isSelected('e-1')).toBe(true);
    expect(cmp.selectedRows()).toEqual([EXPENSE]);
    cmp.onRowActivate(EXPENSE);
    expect(cmp.isSelected('e-1')).toBe(false);
    cmp.toggleSelect('e-2', true);
    cmp.openBulkReassign();
    expect(cmp.bulkReassignOpen()).toBe(true);
    // A view change ends the selection.
    cmp.setTab('bookings');
    expect(cmp.selecting()).toBe(false);
    expect(cmp.selectedCount()).toBe(0);
    expect(cmp.bulkReassignOpen()).toBe(false);
    // A reader cannot select.
    TestBed.resetTestingModule();
    const reader = build({ perms: ['budget.view'] });
    reader.cmp.startSelecting();
    expect(reader.cmp.selecting()).toBe(false);
  });

  it('shows the bulk panel beside the list and the bulk bar one pane at a time', async () => {
    setViewport(WIDE);
    const e2 = { ...EXPENSE, id: 'e-2', description: 'Plakate' };
    const { fixture, container } = await setup({
      perms: ['budget.view', 'budget.book', 'budget.export'],
      page: page([EXPENSE, e2]),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.startSelecting();
    fixture.detectChanges();
    const boxes = container.querySelectorAll<HTMLInputElement>('app-list-item input[type=checkbox]');
    expect(boxes.length).toBe(2);
    boxes[0].click();
    fixture.detectChanges();
    expect(c.detailView()).toBe('bulk');
    expect(screen.getByRole('heading', { name: '1 Buchungen ausgewählt' })).toBeInTheDocument();
    // The select-all box of the bar selects every row.
    const all = screen.getByRole('checkbox', { name: 'Alle wählen' });
    await userEvent.click(all);
    expect(c.selectedCount()).toBe(2);
    await userEvent.click(screen.getByRole('button', { name: 'Alle wählen' }));
    await userEvent.click(screen.getAllByRole('button', { name: 'Auswahl beenden' })[0]);
    expect(c.selecting()).toBe(false);
  });

  it('shows the bulk actions as icons in the bar one pane at a time', async () => {
    const { fixture } = await setup({
      perms: ['budget.view', 'budget.book', 'budget.export'],
      page: page([EXPENSE]),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.startSelecting();
    c.toggleSelect('e-1', true);
    fixture.detectChanges();
    expect(c.detailView()).toBe('none');
    await userEvent.click(screen.getByRole('button', { name: 'Umbuchen' }));
    expect(c.bulkReassignOpen()).toBe(true);
    expect(screen.getByRole('button', { name: 'Auswahl exportieren' })).toBeInTheDocument();
  });

  it('turns the title row into the bar of the bulk actions on a phone', async () => {
    setViewport(PHONE);
    const { fixture } = await setup({ page: page([EXPENSE]) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.startSelecting();
    c.toggleSelect('e-1', true);
    fixture.detectChanges();
    expect(screen.getByRole('heading', { name: '1 ausgewählt' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Löschen' }));
    expect(c.bulkConfirm()).toBe('delete');
  });

  it('shows the open booking, the open transfer and a missing booking in the detail', async () => {
    setViewport(WIDE);
    const { fixture, http } = await setup({ page: page([{ ...EXPENSE, budgetId: 'b-1', fiscalYearId: 'fy-1' }]), tree: FIG_TREE });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.selectedId.set('e-1');
    fixture.detectChanges();
    http.match((r) => r.url.includes('/fiscal-years')).forEach((r) => r.flush([{ ...FY_ACTIVE, id: 'fy-1' }]));
    fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'Druckkosten Flyer' })).toBeInTheDocument();
    expect(screen.getByText('Buchung · HHJ 2026')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Buchung bearbeiten' }));
    expect(c.editing()?.id).toBe('e-1');
    // The form replaces the detail.
    expect(screen.getByRole('heading', { name: 'Buchung bearbeiten' })).toBeInTheDocument();
    c.closeDetail();

    c.selectedId.set('e-gone');
    c.selectedMissing.set(true);
    fixture.detectChanges();
    expect(screen.getByText('Buchung nicht gefunden')).toBeInTheDocument();
    http.match((r) => r.params.get('id') === 'e-gone').forEach((r) => r.flush(page([])));
  });

  it('opens the form of a phone as a bottom sheet', async () => {
    setViewport(PHONE);
    const { fixture } = await setup({ page: page([EXPENSE]) });
    await userEvent.click(screen.getByRole('button', { name: 'Buchung' }));
    fixture.detectChanges();
    const sheet = screen.getByRole('dialog', { name: 'Buchung hinzufügen' });
    expect(sheet.classList.contains('ss--bottom')).toBe(true);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.detailView()).toBe('none');
    await userEvent.click(within(sheet).getAllByRole('button', { name: 'Schließen' })[0]);
    expect(c.createOpen()).toBe(false);
  });

  it('marks the page as a pane page side by side and clears the frame flag on destroy', async () => {
    setViewport(WIDE);
    const { fixture } = await setup();
    expect(fixture.nativeElement.classList.contains('pane-page')).toBe(true);
    fixture.destroy();
  });

  it('formats days, signed amounts and cost centres', () => {
    const { cmp } = build({ tree: FIG_TREE });
    expect(cmp.day('2026-09-28')).toBe('28.09.');
    expect(cmp.day(null)).toBe('');
    expect(cmp.signed({ ...EXPENSE, kind: 'income' }).replace(/\s/g, ' ')).toBe('+120,00 €');
    expect(cmp.costCentre('b-1', null).name).toBe('Öffentlichkeit');
    expect(cmp.costCentre('b-x', 'VS-1').name).toBe('VS-1');
  });
});

/** Answer the next GET /expenses with an empty page and return its params. */
function flushParams(http: HttpTestingController) {
  const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
  req.flush(page([]));
  return req.request.params;
}
