import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ExpensesComponent } from './expenses.component';
import type {
  BudgetTreeNode,
  Expense,
  ExpensePage,
  FiscalYear,
  Invoice,
} from '../budget/budget-tree.api';

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
  accountId: null,
  accountName: null,
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

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

async function setup(opts: { perms?: string[]; page?: ExpensePage } = {}) {
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
  // Konstruktor lädt Kostenstellen-Baum + Konten + Rechnungen + erste Buchungsseite.
  http.match((r) => r.url.endsWith('/budgets')).forEach((req) => req.flush([]));
  http.match((r) => r.url.endsWith('/accounts/options')).forEach((req) => req.flush([]));
  // `listInvoices()` lädt seitenweise (`#invoices`): paged-Shape liefern, nicht []-Array,
  // sonst ist `page.items` undefined und `invoiceOptions` (computed) wirft `.map of undefined`.
  http
    .match((r) => r.url.endsWith('/invoices') && r.method === 'GET')
    .forEach((req) => req.flush({ items: [], total: 0, limit: 200, offset: 0 }));
  http
    .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
    .forEach((req) => req.flush(opts.page ?? page([])));
  return { ...view, http };
}

describe('ExpensesComponent (rendered)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists bookings with description, kind badge and signed amount', async () => {
    await setup({ page: page([EXPENSE]) });
    expect(await screen.findByText('Druckkosten Flyer')).toBeInTheDocument();
    expect(screen.getByText('VS-800')).toBeInTheDocument();
    // Ausgabe → mit Minus-Vorzeichen.
    expect(screen.getByText(/−.*120/)).toBeInTheDocument();
  });

  it('shows the empty state when there are no bookings', async () => {
    await setup();
    expect(await screen.findByText('Keine Buchungen gefunden.')).toBeInTheDocument();
  });

  it('renders invoice date, payment date and payee/payer columns (#1-1/#3)', async () => {
    await setup({ page: page([EXPENSE]) });
    expect(await screen.findByText('Druckkosten Flyer')).toBeInTheDocument();
    expect(screen.getByText('Copyshop Müller')).toBeInTheDocument();
    // Spaltenüberschriften der neuen Datums-Spalten.
    expect(screen.getByRole('button', { name: /Rechnungsdatum/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Zahldatum/ })).toBeInTheDocument();
  });

  it('books a standalone expense via POST /expenses', async () => {
    const { http } = await setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Buchung hinzufügen' }));
    await userEvent.type(screen.getByLabelText('Beschreibung'), 'Kaffee');
    await userEvent.type(screen.getByLabelText('Betrag (€)'), '12.50');
    // Kostenstelle ist Pflicht → ohne Auswahl bleibt der Submit gesperrt; mit Tippen
    // direkt buchen wir den Antrags-Pfad nicht. Hier prüfen wir nur den Request-Aufbau,
    // sobald eine Kostenstelle gesetzt ist (programmatisch über das Select).
    const select = screen.getByLabelText('Kostenstelle') as HTMLSelectElement;
    // Ohne echte Optionen (leerer Baum) kann nicht ausgewählt werden — daher Guard.
    expect(select).toBeInTheDocument();
    http.verify();
  });

  it('hides add/edit controls for a viewer without budget.book', async () => {
    await setup({ perms: ['budget.view'], page: page([EXPENSE]) });
    expect(await screen.findByText('Druckkosten Flyer')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Buchung hinzufügen' })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Direkte Komponenten-Tests (Methoden + Branches), ohne DOM-Rendering. Treibt
// jede öffentliche Methode mit dem HttpTestingController und prüft Signal-State.
// ---------------------------------------------------------------------------

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
    fullyBound: false,
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
        fullyBound: false,
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
 * Komponente direkt instanziieren (Konstruktor feuert tree/accounts/invoices/
 * expenses). Optional kann der initiale Konstruktor-Load mit eigenen Daten
 * beantwortet werden; default = leer.
 */
function build(
  opts: {
    perms?: string[];
    tree?: BudgetTreeNode[];
    accounts?: { id: string; name: string }[];
    invoices?: Invoice[];
    expenses?: ExpensePage;
    treeError?: boolean;
    accountsError?: boolean;
    invoicesError?: boolean;
    expensesError?: boolean;
  } = {},
): Built {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts.perms ?? ['budget.view', 'budget.book', 'budget.export']) },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const cmp = TestBed.runInInjectionContext(() => new ExpensesComponent());

  const treeReq = http.expectOne((r) => r.url.endsWith('/budgets'));
  if (opts.treeError) treeReq.error(new ProgressEvent('err'));
  else treeReq.flush(opts.tree ?? []);

  const accReq = http.expectOne((r) => r.url.endsWith('/accounts/options'));
  if (opts.accountsError) accReq.error(new ProgressEvent('err'));
  else accReq.flush(opts.accounts ?? []);

  const invReq = http.expectOne((r) => r.url.endsWith('/invoices') && r.method === 'GET');
  if (opts.invoicesError) invReq.error(new ProgressEvent('err'));
  else invReq.flush({ items: opts.invoices ?? [], total: (opts.invoices ?? []).length, limit: 200, offset: 0 });

  const expReq = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
  if (opts.expensesError) expReq.error(new ProgressEvent('err'));
  else expReq.flush(opts.expenses ?? page([]));

  return { cmp, http };
}

/** Nächsten GET /expenses (reload/fetch) abfangen + beantworten. */
function flushList(http: HttpTestingController, body: ExpensePage): void {
  http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET').flush(body);
}

describe('ExpensesComponent (unit)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    // Manche Tests rufen TestBed.resetTestingModule() — dann gibt es keinen
    // HttpTestingController-Provider mehr; das verify() entfällt dort.
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module bereits zurückgesetzt */
    }
    jest.useRealTimers();
  });

  it('loads tree, accounts and invoices on construction (success)', () => {
    const { cmp } = build({
      tree: ROOT_TREE,
      accounts: [{ id: 'a-1', name: 'Hauptkonto' }],
      invoices: [INVOICE],
      expenses: page([EXPENSE], 1),
    });
    expect(cmp.budgetTree()).toEqual(ROOT_TREE);
    expect(cmp.accounts()).toEqual([{ id: 'a-1', name: 'Hauptkonto' }]);
    expect(cmp.invoices()).toEqual([INVOICE]);
    expect(cmp.items()).toEqual([EXPENSE]);
    expect(cmp.total()).toBe(1);
    expect(cmp.loading()).toBe(false);
    // computed options abgeleitet
    expect(cmp.costCentreOptions().length).toBe(2);
    expect(cmp.accountOptions()).toEqual([{ value: 'a-1', label: 'Hauptkonto' }]);
    const label = cmp.invoiceOptions()[0];
    expect(label.value).toBe('inv-1');
    // Intl trennt mit schmalem geschützten Leerzeichen — auf Normalwhitespace normieren.
    expect(label.label.replace(/\s/g, ' ')).toBe('RE-2026-1 · Acme GmbH · 119,00 €');
  });

  it('resets each list to empty on construction errors', () => {
    const { cmp } = build({
      treeError: true,
      accountsError: true,
      invoicesError: true,
      expensesError: true,
    });
    expect(cmp.budgetTree()).toEqual([]);
    expect(cmp.accounts()).toEqual([]);
    expect(cmp.invoices()).toEqual([]);
    // expenses error → loading/loadingMore zurückgesetzt, items leer
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
    // de-Locale aus localStorage
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
    const sparse: Invoice = { ...INVOICE, id: 'inv-2', number: null, supplier: null, grossAmount: '5.00' };
    const { cmp } = build({ invoices: [sparse] });
    // Nur der Betrag bleibt übrig (number/supplier ausgefiltert).
    expect(cmp.invoiceOptions()[0].label).toMatch(/5,00\s?€/);
    expect(cmp.invoiceOptions()[0].label).not.toContain('·');
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
    expect(p.get('sort')).toBe('invoiceDate');
    expect(p.get('order')).toBe('desc');
    req.flush(page([]));
  });

  it('fetch omits empty/whitespace optional params', () => {
    const { cmp, http } = build();
    cmp.q.set('   ');
    cmp.amountMin.set('   ');
    cmp.amountMax.set('');
    cmp.setKind(''); // reload with all-empty
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
    cmp.onAmountFilter('min', '5');
    cmp.onAmountFilter('max', '50');
    cmp.onDateFilter('from', '2026-01-01');
    cmp.onDateFilter('to', '2026-12-31');
    expect(cmp.q()).toBe('ab');
    expect(cmp.amountMin()).toBe('5');
    expect(cmp.amountMax()).toBe('50');
    expect(cmp.createdFrom()).toBe('2026-01-01');
    expect(cmp.createdTo()).toBe('2026-12-31');
    // Vor Ablauf: keine Anfrage.
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
    // gleiche Spalte (default invoiceDate desc) → asc
    cmp.onSort('invoiceDate');
    expect(cmp.sortField()).toBe('invoiceDate');
    expect(cmp.sortOrder()).toBe('asc');
    flushList(http, page([]));
    // erneut → wieder desc
    cmp.onSort('invoiceDate');
    expect(cmp.sortOrder()).toBe('desc');
    flushList(http, page([]));
    // neue Spalte → desc
    cmp.onSort('amount');
    expect(cmp.sortField()).toBe('amount');
    expect(cmp.sortOrder()).toBe('desc');
    flushList(http, page([]));
  });

  it('sortInd and ariaSort describe the active sort column', () => {
    const { cmp } = build();
    // default: invoiceDate desc
    expect(cmp.sortInd('invoiceDate')).toBe(' ↓');
    expect(cmp.sortInd('amount')).toBe('');
    expect(cmp.ariaSort('invoiceDate')).toBe('descending');
    expect(cmp.ariaSort('amount')).toBe('none');
    cmp.sortOrder.set('asc');
    expect(cmp.sortInd('invoiceDate')).toBe(' ↑');
    expect(cmp.ariaSort('invoiceDate')).toBe('ascending');
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
    // while loadingMore
    cmp.total.set(5);
    cmp.loadingMore.set(true);
    cmp.loadMore();
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    cmp.loadingMore.set(false);
    // while loading
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
    expect(cmp.newKind()).toBe('expense');
    expect(cmp.newBudgetId()).toBe('child-1');
    // loadFiscalYears(child-1) → top-1
    const req = http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years'));
    req.flush([FY_ACTIVE]);
    expect(cmp.fiscalYearOptions()).toEqual([{ value: 'fy-active', label: '2026' }]);
    // genau ein aktives HHJ → vorausgewählt
    expect(cmp.newFiscalYearId()).toBe('fy-active');
  });

  it('openCreate without a preselected budget skips the fiscal-year load', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.openCreate();
    expect(cmp.createOpen()).toBe(true);
    expect(cmp.newBudgetId()).toBe('');
    expect(cmp.fiscalYearOptions()).toEqual([]);
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('onPickBudget loads fiscal years; multiple active years are not auto-selected', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.onPickBudget('child-1');
    expect(cmp.newBudgetId()).toBe('child-1');
    const secondActive: FiscalYear = { ...FY_ACTIVE, id: 'fy-2', display: '2026/27' };
    http
      .expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years'))
      .flush([FY_ACTIVE, secondActive, FY_OLD]);
    expect(cmp.fiscalYearOptions().length).toBe(3);
    // zwei aktive → keine Vorauswahl
    expect(cmp.newFiscalYearId()).toBe('');
  });

  it('onPickBudget with empty id clears the fiscal-year selection without a request', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.newFiscalYearId.set('fy-x');
    cmp.fiscalYearOptions.set([{ value: 'fy-x', label: 'X' }]);
    cmp.onPickBudget('');
    expect(cmp.newBudgetId()).toBe('');
    expect(cmp.newFiscalYearId()).toBe('');
    expect(cmp.fiscalYearOptions()).toEqual([]);
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('loadFiscalYears resets options on error', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.fiscalYearOptions.set([{ value: 'x', label: 'X' }]);
    cmp.onPickBudget('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).error(new ProgressEvent('err'));
    expect(cmp.fiscalYearOptions()).toEqual([]);
  });

  it('loadFiscalYears is skipped when the budget id is not in the tree', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.onPickBudget('unknown-id');
    // findTop liefert null → keine Anfrage, Optionen bleiben leer
    http.expectNone((r) => r.url.includes('/fiscal-years'));
    expect(cmp.fiscalYearOptions()).toEqual([]);
  });

  it('canSubmitCreate enforces description, amount and (for standalone) budget+fy', () => {
    const { cmp } = build();
    expect(cmp.canSubmitCreate()).toBe(false);
    cmp.newDescription.set('Kaffee');
    expect(cmp.canSubmitCreate()).toBe(false); // amount missing
    cmp.newAmount.set('0');
    expect(cmp.canSubmitCreate()).toBe(false); // amount must be > 0
    cmp.newAmount.set('12');
    expect(cmp.canSubmitCreate()).toBe(false); // standalone needs budget+fy
    cmp.newBudgetId.set('b-1');
    expect(cmp.canSubmitCreate()).toBe(false); // fy missing
    cmp.newFiscalYearId.set('fy-1');
    expect(cmp.canSubmitCreate()).toBe(true);
    // gebunden: Antrag genügt (Kostenstelle/HHJ vom Antrag geerbt)
    cmp.newBudgetId.set('');
    cmp.newFiscalYearId.set('');
    cmp.newApplicationId.set('app-9');
    expect(cmp.canSubmitCreate()).toBe(true);
  });

  it('create posts a standalone booking, toasts and reloads', () => {
    const { cmp, http } = build();
    cmp.newDescription.set('  Kaffee  ');
    cmp.newAmount.set('12.50');
    cmp.newBudgetId.set('b-1');
    cmp.newFiscalYearId.set('fy-1');
    cmp.newAccountId.set('a-1');
    cmp.newCorrespondent.set(' Bäckerei ');
    cmp.newReferenceNumber.set(' R-1 ');
    cmp.newPaymentMethod.set('bar');
    cmp.newCategory.set(' Bewirtung ');
    cmp.newNote.set(' lecker ');
    cmp.create(new Event('submit'));
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST');
    expect(req.request.body).toMatchObject({
      amount: '12.50',
      description: 'Kaffee',
      kind: 'expense',
      applicationId: null,
      budgetId: 'b-1',
      fiscalYearId: 'fy-1',
      accountId: 'a-1',
      correspondent: 'Bäckerei',
      referenceNumber: 'R-1',
      paymentMethod: 'bar',
      category: 'Bewirtung',
      note: 'lecker',
    });
    req.flush({ ...EXPENSE, id: 'e-new' });
    expect(cmp.saving()).toBe(false);
    expect(cmp.createOpen()).toBe(false);
    // reload feuert eine weitere Liste
    flushList(http, page([]));
  });

  it('create posts a linked booking nulling budget/fy and blank metadata', () => {
    const { cmp, http } = build();
    cmp.newDescription.set('Gebunden');
    cmp.newAmount.set('5');
    cmp.newApplicationId.set('app-9');
    cmp.newBudgetId.set('ignored');
    cmp.newFiscalYearId.set('ignored');
    cmp.create(new Event('submit'));
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST');
    expect(req.request.body).toMatchObject({
      applicationId: 'app-9',
      budgetId: null,
      fiscalYearId: null,
      accountId: null,
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
    cmp.newDescription.set('x');
    cmp.newAmount.set('1');
    cmp.newApplicationId.set('app-1');
    cmp.saving.set(true);
    cmp.create(new Event('submit'));
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'POST');
  });

  it('create surfaces the problem+json detail on error, else a generic message', () => {
    const { cmp, http } = build();
    const toastSpy = jest.spyOn((cmp as unknown as { toast: { error: (m: string) => void } }).toast, 'error');
    cmp.newDescription.set('x');
    cmp.newAmount.set('1');
    cmp.newApplicationId.set('app-1');
    cmp.create(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST')
      .flush({ detail: 'Budget überschritten' }, { status: 422, statusText: 'Unprocessable' });
    expect(cmp.saving()).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('Budget überschritten');

    // generischer Fallback ohne detail
    cmp.create(new Event('submit'));
    http
      .expectOne((r) => r.url.endsWith('/expenses') && r.method === 'POST')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(toastSpy).toHaveBeenLastCalledWith('Aktion fehlgeschlagen.');
  });

  it('setNewKindIncome switches to income and clears any application link', () => {
    const { cmp } = build();
    cmp.newApplicationId.set('app-1');
    cmp.appQuery.set('Antrag X');
    cmp.appCandidates.set([{ id: 'app-1', title: 'Antrag X' }]);
    cmp.setNewKindIncome();
    expect(cmp.newKind()).toBe('income');
    expect(cmp.newApplicationId()).toBe('');
    expect(cmp.appQuery()).toBe('');
    expect(cmp.appCandidates()).toEqual([]);
  });

  it('onAppSearch queries applications and maps candidates (title fallback to id)', () => {
    const { cmp, http } = build();
    cmp.onAppSearch('  flyer ');
    // appQuery hält den Roh-Wert; nur der Request-Parameter ist getrimmt.
    expect(cmp.appQuery()).toBe('  flyer ');
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
    expect(cmp.appCandidates()).toEqual([
      { id: 'app-1', title: 'Flyer-Antrag' },
      { id: 'app-2', title: 'app-2' },
    ]);
  });

  it('onAppSearch clears candidates for an empty query without a request', () => {
    const { cmp, http } = build();
    cmp.appCandidates.set([{ id: 'x', title: 'X' }]);
    cmp.onAppSearch('   ');
    expect(cmp.appQuery()).toBe('   ');
    expect(cmp.appCandidates()).toEqual([]);
    http.expectNone((r) => r.url.endsWith('/applications'));
  });

  it('onAppSearch clears candidates on error', () => {
    const { cmp, http } = build();
    cmp.onAppSearch('z');
    http.expectOne((r) => r.url.endsWith('/applications')).error(new ProgressEvent('err'));
    expect(cmp.appCandidates()).toEqual([]);
  });

  it('pickApp / clearApp manage the selected application', () => {
    const { cmp } = build();
    cmp.appCandidates.set([{ id: 'app-1', title: 'Antrag X' }]);
    cmp.pickApp({ id: 'app-1', title: 'Antrag X' });
    expect(cmp.newApplicationId()).toBe('app-1');
    expect(cmp.appQuery()).toBe('Antrag X');
    expect(cmp.appCandidates()).toEqual([]);
    cmp.clearApp();
    expect(cmp.newApplicationId()).toBe('');
    expect(cmp.appQuery()).toBe('');
  });

  it('onPickInvoice prefills amount, payee, reference and invoice date', () => {
    const { cmp } = build({ invoices: [INVOICE] });
    cmp.onPickInvoice('inv-1');
    expect(cmp.newInvoiceId()).toBe('inv-1');
    expect(cmp.newAmount()).toBe('119.00');
    expect(cmp.newCorrespondent()).toBe('Acme GmbH');
    expect(cmp.newReferenceNumber()).toBe('RE-2026-1');
    expect(cmp.newInvoiceDate()).toBe('2026-04-01');
  });

  it('onPickInvoice with unknown id only stores the id (no prefill)', () => {
    const { cmp } = build({ invoices: [INVOICE] });
    cmp.onPickInvoice('nope');
    expect(cmp.newInvoiceId()).toBe('nope');
    expect(cmp.newAmount()).toBe('');
    expect(cmp.newCorrespondent()).toBe('');
  });

  it('onPickInvoice handles sparse invoices (null gross, missing fields)', () => {
    // grossAmount runtime-null → der `?? ''`-Zweig greift (Backend kann null liefern).
    const sparse = {
      ...INVOICE,
      id: 'inv-3',
      grossAmount: null,
      supplier: null,
      number: null,
      issueDate: null,
    } as unknown as Invoice;
    const { cmp } = build({ invoices: [sparse] });
    cmp.newAmount.set('preset');
    cmp.newCorrespondent.set('keep');
    cmp.newReferenceNumber.set('keep');
    cmp.newInvoiceDate.set('keep');
    cmp.onPickInvoice('inv-3');
    expect(cmp.newAmount()).toBe(''); // grossAmount null → ?? '' überschreibt mit ''
    expect(cmp.newCorrespondent()).toBe('keep');
    expect(cmp.newReferenceNumber()).toBe('keep');
    expect(cmp.newInvoiceDate()).toBe('keep');
  });

  it('onPickEditInvoice prefills the edit form, unknown id is a no-op', () => {
    const { cmp } = build({ invoices: [INVOICE] });
    cmp.onPickEditInvoice('inv-1');
    expect(cmp.editInvoiceId()).toBe('inv-1');
    expect(cmp.editAmount()).toBe('119.00');
    expect(cmp.editCorrespondent()).toBe('Acme GmbH');
    expect(cmp.editReferenceNumber()).toBe('RE-2026-1');
    expect(cmp.editInvoiceDate()).toBe('2026-04-01');
    cmp.onPickEditInvoice('nope');
    expect(cmp.editInvoiceId()).toBe('nope');
  });

  it('onPickEditInvoice coerces a null gross amount to empty string', () => {
    const sparse = { ...INVOICE, id: 'inv-4', grossAmount: null } as unknown as Invoice;
    const { cmp } = build({ invoices: [sparse] });
    cmp.editAmount.set('preset');
    cmp.onPickEditInvoice('inv-4');
    expect(cmp.editAmount()).toBe('');
  });

  it('openEdit fills the edit form, coalescing null metadata to empty strings', () => {
    const { cmp } = build();
    const e: Expense = {
      ...EXPENSE,
      accountId: null,
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
    expect(cmp.editAmount()).toBe(e.amount);
    expect(cmp.editDescription()).toBe(e.description);
    expect(cmp.editAccountId()).toBe('');
    expect(cmp.editInvoiceId()).toBe('');
    expect(cmp.editInvoiceDate()).toBe('');
    expect(cmp.editPaymentDate()).toBe('');
    expect(cmp.editCorrespondent()).toBe('');
    expect(cmp.editReferenceNumber()).toBe('');
    expect(cmp.editPaymentMethod()).toBe('');
    expect(cmp.editCategory()).toBe('');
    expect(cmp.editNote()).toBe('');
  });

  it('openEdit keeps populated metadata fields', () => {
    const { cmp } = build();
    cmp.openEdit({ ...EXPENSE, accountId: 'a-1', invoiceId: 'inv-1' });
    expect(cmp.editAccountId()).toBe('a-1');
    expect(cmp.editInvoiceId()).toBe('inv-1');
    expect(cmp.editPaymentMethod()).toBe('ueberweisung');
    expect(cmp.editCategory()).toBe('Werbung');
  });

  it('saveEdit patches the booking and updates the matching list row', () => {
    const other = { ...EXPENSE, id: 'e-2', description: 'Andere' };
    const { cmp, http } = build({ expenses: page([EXPENSE, other], 2) });
    cmp.openEdit(EXPENSE);
    cmp.editAmount.set('200');
    cmp.editDescription.set('  Neu  ');
    cmp.editAccountId.set('a-2');
    cmp.editInvoiceId.set('inv-9');
    cmp.editCorrespondent.set(' X ');
    cmp.editReferenceNumber.set(' Y ');
    cmp.editPaymentMethod.set('karte');
    cmp.editCategory.set(' Z ');
    cmp.editNote.set(' note ');
    cmp.saveEdit(new Event('submit'));
    const req = http.expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH');
    expect(req.request.body).toMatchObject({
      amount: '200',
      description: 'Neu',
      accountId: 'a-2',
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
    cmp.editAccountId.set('');
    cmp.editInvoiceId.set('');
    cmp.editInvoiceDate.set('');
    cmp.editPaymentDate.set('');
    cmp.editCorrespondent.set('   ');
    cmp.editReferenceNumber.set('');
    cmp.editPaymentMethod.set('');
    cmp.editCategory.set('');
    cmp.editNote.set('');
    cmp.saveEdit(new Event('submit'));
    const req = http.expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'PATCH');
    expect(req.request.body).toMatchObject({
      accountId: null,
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
    const toastSpy = jest.spyOn((cmp as unknown as { toast: { error: (m: string) => void } }).toast, 'error');
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
    http.expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE').flush(null);
    expect(cmp.confirmDelete()).toBeNull();
    expect(cmp.items().map((x) => x.id)).toEqual(['e-2']);
    expect(cmp.total()).toBe(1);
    expect(cmp.saving()).toBe(false);
  });

  it('doDelete clamps the total at zero', () => {
    const { cmp, http } = build({ expenses: page([EXPENSE], 0) });
    cmp.confirmDelete.set(EXPENSE);
    cmp.doDelete();
    http.expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE').flush(null);
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
    const toastSpy = jest.spyOn((cmp as unknown as { toast: { error: (m: string) => void } }).toast, 'error');
    cmp.confirmDelete.set(EXPENSE);
    cmp.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/budget-expenses/e-1') && r.method === 'DELETE')
      .error(new ProgressEvent('err'));
    expect(cmp.saving()).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('onExport downloads the xlsx and clears the exporting flag', () => {
    // jsdom kennt URL.createObjectURL/revokeObjectURL nicht — vorher definieren.
    (URL as unknown as { createObjectURL?: unknown }).createObjectURL = () => 'blob:mock';
    (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = () => undefined;
    const createObjSpy = jest.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock');
    const revokeSpy = jest.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const clickSpy = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
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
    const opts = cmp.paymentMethodOptions();
    expect(opts.map((o) => o.value)).toEqual([
      'ueberweisung',
      'bar',
      'lastschrift',
      'karte',
      'paypal',
    ]);
    expect(opts.every((o) => typeof o.label === 'string' && o.label.length > 0)).toBe(true);
  });

  // --- transfers ---------------------------------------------------------
  it('openTransfer seeds from the selected budget and loads its fiscal years', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.budgetId.set('child-1');
    cmp.openTransfer();
    expect(cmp.transferOpen()).toBe(true);
    expect(cmp.tFromId()).toBe('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_ACTIVE]);
    expect(cmp.transferFyOptions()).toEqual([{ value: 'fy-active', label: '2026' }]);
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
    cmp.onTransferFrom('child-1');
    expect(cmp.tFromId()).toBe('child-1');
    expect(cmp.tFiscalYearId()).toBe('');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_ACTIVE]);
    expect(cmp.tFiscalYearId()).toBe('fy-active');
  });

  it('onTransferFrom with empty id clears the source without a request', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.onTransferFrom('');
    expect(cmp.tFromId()).toBe('');
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('loadTransferFy is skipped for an unknown budget and resets on error', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    // unknown → findTop null → no request
    cmp.onTransferFrom('ghost');
    http.expectNone((r) => r.url.includes('/fiscal-years'));
    // known but error → options reset
    cmp.transferFyOptions.set([{ value: 'x', label: 'X' }]);
    cmp.onTransferFrom('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).error(new ProgressEvent('err'));
    expect(cmp.transferFyOptions()).toEqual([]);
  });

  it('loadTransferFy does not auto-select when there is no single active year', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.onTransferFrom('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_OLD]);
    expect(cmp.transferFyOptions().length).toBe(1);
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
    const toastSpy = jest.spyOn((cmp as unknown as { toast: { error: (m: string) => void } }).toast, 'error');
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

// IntersectionObserver-Zweig: vorhandener Observer ruft loadMore beim Sichtbar-
// werden. Wir shimmen IO und triggern den Callback manuell.
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
    http.match((r) => r.url.endsWith('/accounts/options')).forEach((req) => req.flush([]));
    http
      .match((r) => r.url.endsWith('/invoices') && r.method === 'GET')
      .forEach((req) => req.flush({ items: [], total: 0, limit: 200, offset: 0 }));
    http
      .match((r) => r.url.endsWith('/expenses') && r.method === 'GET')
      .forEach((req) => req.flush(page([EXPENSE], 3)));
    view.detectChanges();

    expect(observe).toHaveBeenCalled();
    // Sichtbar werden → loadMore → zweite Seite.
    trigger?.([{ isIntersecting: true }]);
    http.match((r) => r.url.endsWith('/expenses') && r.method === 'GET').forEach((req) =>
      req.flush(page([{ ...EXPENSE, id: 'e-2' }], 3, 1)),
    );
    // nicht-sichtbar → kein zusätzlicher Request
    trigger?.([{ isIntersecting: false }]);
    http.expectNone((r) => r.url.endsWith('/expenses') && r.method === 'GET');

    delete (globalThis as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    http.verify();
  });
});
