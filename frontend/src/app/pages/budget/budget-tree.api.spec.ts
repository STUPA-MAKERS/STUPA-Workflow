import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { API_BASE_URL } from '@core/api/api.config';
import {
  BudgetTreeApi,
  flattenBudgetOptions,
  flattenBudgetTreeRows,
  simplifyPathKey,
  type BudgetTreeNode,
} from './budget-tree.api';

const BASE = '/api';

function node(over: Partial<BudgetTreeNode> = {}): BudgetTreeNode {
  return {
    id: 'n-1',
    parentId: null,
    gremiumId: null,
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
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
    ...over,
  };
}

describe('BudgetTreeApi', () => {
  let api: BudgetTreeApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: BASE },
        BudgetTreeApi,
      ],
    });
    api = TestBed.inject(BudgetTreeApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('tree', () => {
    it('GETs /budgets without a gremium param when omitted', () => {
      api.tree().subscribe();
      const req = http.expectOne(`${BASE}/budgets`);
      expect(req.request.method).toBe('GET');
      expect(req.request.params.has('gremium')).toBe(false);
      req.flush([]);
    });

    it('GETs /budgets with the gremium param when provided', () => {
      api.tree('g-1').subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/budgets`);
      expect(req.request.params.get('gremium')).toBe('g-1');
      req.flush([]);
    });
  });

  it('createNode POSTs the body to /budgets', () => {
    const body = { key: 'VS', name: 'VS-Mittel' };
    let result: unknown;
    api.createNode(body).subscribe((r) => (result = r));
    const req = http.expectOne(`${BASE}/budgets`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(body);
    req.flush({ id: 'n-1' });
    expect(result).toEqual({ id: 'n-1' });
  });

  it('updateNode PATCHes /budgets/:id', () => {
    api.updateNode('n-1', { name: 'Neu' }).subscribe();
    const req = http.expectOne(`${BASE}/budgets/n-1`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ name: 'Neu' });
    req.flush({ id: 'n-1' });
  });

  it('deleteNode DELETEs /budgets/:id', () => {
    api.deleteNode('n-1').subscribe();
    const req = http.expectOne(`${BASE}/budgets/n-1`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('listFiscalYears GETs /budgets/:id/fiscal-years', () => {
    api.listFiscalYears('n-1').subscribe();
    const req = http.expectOne(`${BASE}/budgets/n-1/fiscal-years`);
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  it('createFiscalYear POSTs /budgets/:id/fiscal-years', () => {
    api.createFiscalYear('n-1', { year: 2027 }).subscribe();
    const req = http.expectOne(`${BASE}/budgets/n-1/fiscal-years`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ year: 2027 });
    req.flush({});
  });

  it('setAllocation PUTs /budgets/:id/allocations/:fy', () => {
    api.setAllocation('n-1', 'fy-1', '500').subscribe();
    const req = http.expectOne(`${BASE}/budgets/n-1/allocations/fy-1`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ allocated: '500' });
    req.flush({});
  });

  describe('applications', () => {
    it('GETs /budgets/:id/applications without a fiscalYear param when omitted', () => {
      api.applications('n-1').subscribe();
      const req = http.expectOne(`${BASE}/budgets/n-1/applications`);
      expect(req.request.params.has('fiscalYear')).toBe(false);
      req.flush([]);
    });

    it('GETs with the fiscalYear param when provided', () => {
      api.applications('n-1', 'fy-1').subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/budgets/n-1/applications`);
      expect(req.request.params.get('fiscalYear')).toBe('fy-1');
      req.flush([]);
    });
  });

  describe('listExpenses', () => {
    it('GETs /expenses with no params for an empty query', () => {
      api.listExpenses().subscribe();
      const req = http.expectOne(`${BASE}/expenses`);
      expect(req.request.params.keys().length).toBe(0);
      req.flush({ items: [], total: 0, limit: 0, offset: 0 });
    });

    it('drops undefined/null/empty values and stringifies the rest', () => {
      api
        .listExpenses({
          budget: 'b-1',
          kind: 'expense',
          amountMin: 0,
          q: '',
          fiscalYear: undefined,
        })
        .subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/expenses`);
      expect(req.request.params.get('budget')).toBe('b-1');
      expect(req.request.params.get('kind')).toBe('expense');
      // An amountMin of 0 is not empty, null or undefined, so it stays as a string.
      expect(req.request.params.get('amountMin')).toBe('0');
      // The empty q and the undefined fiscalYear both drop out.
      expect(req.request.params.has('q')).toBe(false);
      expect(req.request.params.has('fiscalYear')).toBe(false);
      req.flush({ items: [], total: 0, limit: 0, offset: 0 });
    });
  });

  it('bookExpense POSTs /expenses', () => {
    api.bookExpense({ amount: '10', description: 'x' }).subscribe();
    const req = http.expectOne(`${BASE}/expenses`);
    expect(req.request.method).toBe('POST');
    req.flush({});
  });

  it('updateExpense PATCHes /budget-expenses/:id', () => {
    api.updateExpense('e-1', { amount: '20' }).subscribe();
    const req = http.expectOne(`${BASE}/budget-expenses/e-1`);
    expect(req.request.method).toBe('PATCH');
    req.flush({});
  });

  it('deleteExpense DELETEs /budget-expenses/:id', () => {
    api.deleteExpense('e-1').subscribe();
    const req = http.expectOne(`${BASE}/budget-expenses/e-1`);
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  describe('sub-bookings (#subbookings)', () => {
    it('listSubBookings GETs /budget-expenses/:id/sub-bookings', () => {
      api.listSubBookings('e-1').subscribe();
      const req = http.expectOne(`${BASE}/budget-expenses/e-1/sub-bookings`);
      expect(req.request.method).toBe('GET');
      req.flush([]);
    });

    it('createSubBooking POSTs the body to /budget-expenses/:id/sub-bookings', () => {
      api.createSubBooking('e-1', { amount: '5', description: 'Teil' }).subscribe();
      const req = http.expectOne(`${BASE}/budget-expenses/e-1/sub-bookings`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ amount: '5', description: 'Teil' });
      req.flush({});
    });

    it('importSubBookings POSTs a multipart form to /sub-bookings/import', () => {
      const file = new File(['x'], 'kontoauszug.sta');
      api.importSubBookings('e-1', file).subscribe();
      const req = http.expectOne(`${BASE}/budget-expenses/e-1/sub-bookings/import`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body instanceof FormData).toBe(true);
      expect((req.request.body as FormData).get('file')).toBe(file);
      req.flush([]);
    });
  });

  it('createTransfer POSTs /budget-transfers', () => {
    api
      .createTransfer({
        fromBudgetId: 'a',
        toBudgetId: 'b',
        fiscalYearId: 'fy',
        amount: '5',
        description: 'd',
      })
      .subscribe();
    const req = http.expectOne(`${BASE}/budget-transfers`);
    expect(req.request.method).toBe('POST');
    req.flush({});
  });

  describe('invoices', () => {
    it('listInvoicesPaged GETs /invoices with stringified params, dropping empties', () => {
      api.listInvoicesPaged({ q: 'rent', status: 'open', grossMin: 0, dueFrom: '' }).subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/invoices`);
      expect(req.request.params.get('q')).toBe('rent');
      expect(req.request.params.get('status')).toBe('open');
      expect(req.request.params.get('grossMin')).toBe('0');
      expect(req.request.params.has('dueFrom')).toBe(false);
      req.flush({ items: [], total: 0, limit: 0, offset: 0 });
    });

    it('listInvoicesPaged GETs /invoices with no params for an empty query', () => {
      api.listInvoicesPaged().subscribe();
      const req = http.expectOne(`${BASE}/invoices`);
      expect(req.request.params.keys().length).toBe(0);
      req.flush({ items: [], total: 0, limit: 0, offset: 0 });
    });

    it('listInvoices maps the page to its items with limit=200', () => {
      let items: unknown;
      api.listInvoices().subscribe((i) => (items = i));
      const req = http.expectOne((r) => r.url === `${BASE}/invoices`);
      expect(req.request.params.get('limit')).toBe('200');
      req.flush({ items: [{ id: 'inv-1' }], total: 1, limit: 200, offset: 0 });
      expect(items).toEqual([{ id: 'inv-1' }]);
    });

    it('getInvoice GETs /invoices/:id', () => {
      api.getInvoice('inv-1').subscribe();
      const req = http.expectOne(`${BASE}/invoices/inv-1`);
      expect(req.request.method).toBe('GET');
      req.flush({ id: 'inv-1' });
    });

    it('createInvoice POSTs /invoices', () => {
      api.createInvoice({ grossAmount: '10' }).subscribe();
      const req = http.expectOne(`${BASE}/invoices`);
      expect(req.request.method).toBe('POST');
      req.flush({});
    });

    it('updateInvoice PATCHes /invoices/:id', () => {
      api.updateInvoice('inv-1', { note: 'x' }).subscribe();
      const req = http.expectOne(`${BASE}/invoices/inv-1`);
      expect(req.request.method).toBe('PATCH');
      req.flush({});
    });

    it('deleteInvoice DELETEs /invoices/:id', () => {
      api.deleteInvoice('inv-1').subscribe();
      const req = http.expectOne(`${BASE}/invoices/inv-1`);
      expect(req.request.method).toBe('DELETE');
      req.flush(null);
    });

    it('parseInvoice POSTs a multipart form to /invoices/parse', () => {
      const file = new File(['x'], 'r.pdf', { type: 'application/pdf' });
      api.parseInvoice(file).subscribe();
      const req = http.expectOne(`${BASE}/invoices/parse`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body instanceof FormData).toBe(true);
      expect((req.request.body as FormData).get('file')).toBe(file);
      req.flush({});
    });

    it('uploadInvoiceFile POSTs a multipart form to /invoices/file', () => {
      const file = new File(['x'], 'r.pdf', { type: 'application/pdf' });
      api.uploadInvoiceFile(file).subscribe();
      const req = http.expectOne(`${BASE}/invoices/file`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body instanceof FormData).toBe(true);
      req.flush({});
    });

    it('invoiceFileBlob GETs /invoices/:id/file as a blob', () => {
      api.invoiceFileBlob('inv-1').subscribe();
      const req = http.expectOne(`${BASE}/invoices/inv-1/file`);
      expect(req.request.method).toBe('GET');
      expect(req.request.responseType).toBe('blob');
      req.flush(new Blob());
    });
  });

  describe('accounts', () => {
    it('listAccounts GETs /accounts', () => {
      api.listAccounts().subscribe();
      const req = http.expectOne(`${BASE}/accounts`);
      expect(req.request.method).toBe('GET');
      req.flush([]);
    });

    it('listAccountOptions GETs /accounts/options', () => {
      api.listAccountOptions().subscribe();
      const req = http.expectOne(`${BASE}/accounts/options`);
      req.flush([]);
    });

    it('createAccount POSTs /accounts', () => {
      api.createAccount({ name: 'Kasse' }).subscribe();
      const req = http.expectOne(`${BASE}/accounts`);
      expect(req.request.method).toBe('POST');
      req.flush({});
    });

    it('updateAccount PATCHes /accounts/:id', () => {
      api.updateAccount('a-1', { active: false }).subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1`);
      expect(req.request.method).toBe('PATCH');
      req.flush({});
    });

    it('deleteAccount DELETEs /accounts/:id', () => {
      api.deleteAccount('a-1').subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1`);
      expect(req.request.method).toBe('DELETE');
      req.flush(null);
    });
  });

  describe('bank reconcile (#fints)', () => {
    it('fintsCredentialStatus GETs /accounts/:id/fints/credential', () => {
      api.fintsCredentialStatus('a-1').subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1/fints/credential`);
      expect(req.request.method).toBe('GET');
      req.flush({ configured: true, hasCredential: false, fintsLogin: null, fintsLastSyncAt: null });
    });

    it('setFintsCredential PUTs the login+pin to /accounts/:id/fints/credential', () => {
      api.setFintsCredential('a-1', { fintsLogin: 'user1', fintsPin: '1234' }).subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1/fints/credential`);
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ fintsLogin: 'user1', fintsPin: '1234' });
      req.flush({ configured: true, hasCredential: true, fintsLogin: 'user1', fintsLastSyncAt: null });
    });

    it('deleteFintsCredential DELETEs /accounts/:id/fints/credential', () => {
      api.deleteFintsCredential('a-1').subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1/fints/credential`);
      expect(req.request.method).toBe('DELETE');
      req.flush(null);
    });

    it('fintsSync POSTs /accounts/:id/fints/sync', () => {
      api.fintsSync('a-1').subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1/fints/sync`);
      expect(req.request.method).toBe('POST');
      req.flush({ status: 'done' });
    });

    it('fintsSubmitTan POSTs the tan to the session endpoint', () => {
      api.fintsSubmitTan('a-1', 's-1', '123456').subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1/fints/sessions/s-1/tan`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ tan: '123456' });
      req.flush({ status: 'done' });
    });

    it('importStatementFile POSTs multipart to /statement/import', () => {
      api.importStatementFile('a-1', new File(['x'], 's.sta')).subscribe();
      const req = http.expectOne(`${BASE}/accounts/a-1/statement/import`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body instanceof FormData).toBe(true);
      req.flush({ accountId: 'a-1', imported: 1, duplicates: 0 });
    });

    it('listStatementLines GETs /statement-lines with filters', () => {
      api.listStatementLines({ account: 'a-1', state: 'unmatched' }).subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/statement-lines`);
      expect(req.request.params.get('account')).toBe('a-1');
      expect(req.request.params.get('state')).toBe('unmatched');
      req.flush([]);
    });

    it('listStatementLines GETs /statement-lines with only paging defaults', () => {
      api.listStatementLines().subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/statement-lines`);
      expect(req.request.params.keys().sort()).toEqual(['limit', 'offset']);
      expect(req.request.params.get('limit')).toBe('50');
      expect(req.request.params.get('offset')).toBe('0');
      req.flush([]);
    });

    it('confirmStatementLine POSTs /statement-lines/:id/confirm', () => {
      api.confirmStatementLine('l-1', { budgetId: 'b-1' }).subscribe();
      const req = http.expectOne(`${BASE}/statement-lines/l-1/confirm`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ budgetId: 'b-1' });
      req.flush({ id: 'e-1' });
    });

    it('listStatementLines maps every filter + paging option onto params', () => {
      api
        .listStatementLines({
          account: 'a-1',
          state: 'matched',
          linked: false,
          kind: 'income',
          q: 'miete',
          dateFrom: '2026-01-01',
          dateTo: '2026-06-30',
          sort: 'amount',
          order: 'desc',
          limit: 25,
          offset: 75,
        })
        .subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/statement-lines`);
      // The linked flag is false and not undefined, so it goes out as a string.
      expect(req.request.params.get('linked')).toBe('false');
      expect(req.request.params.get('kind')).toBe('income');
      expect(req.request.params.get('q')).toBe('miete');
      expect(req.request.params.get('dateFrom')).toBe('2026-01-01');
      expect(req.request.params.get('dateTo')).toBe('2026-06-30');
      expect(req.request.params.get('sort')).toBe('amount');
      expect(req.request.params.get('order')).toBe('desc');
      expect(req.request.params.get('limit')).toBe('25');
      expect(req.request.params.get('offset')).toBe('75');
      req.flush({ items: [], total: 0, limit: 25, offset: 75 });
    });

    it('ignoreStatementLine POSTs /statement-lines/:id/ignore', () => {
      api.ignoreStatementLine('l-1').subscribe();
      const req = http.expectOne(`${BASE}/statement-lines/l-1/ignore`);
      expect(req.request.method).toBe('POST');
      req.flush(null);
    });

    it('unlinkStatementLine POSTs /statement-lines/:id/unlink', () => {
      api.unlinkStatementLine('l-1').subscribe();
      const req = http.expectOne(`${BASE}/statement-lines/l-1/unlink`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({});
      req.flush({ id: 'l-1', matchState: 'unmatched' });
    });
  });

  describe('exports', () => {
    it('exportExpensesXlsx GETs export.xlsx as a blob with no params by default', () => {
      api.exportExpensesXlsx().subscribe();
      const req = http.expectOne(`${BASE}/expenses/export.xlsx`);
      expect(req.request.responseType).toBe('blob');
      expect(req.request.params.keys().length).toBe(0);
      req.flush(new Blob());
    });

    it('exportExpensesXlsx keeps only truthy option values', () => {
      api.exportExpensesXlsx({ budget: 'b-1', kind: undefined, q: '' }).subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/expenses/export.xlsx`);
      expect(req.request.params.get('budget')).toBe('b-1');
      expect(req.request.params.has('kind')).toBe(false);
      expect(req.request.params.has('q')).toBe(false);
      req.flush(new Blob());
    });

    it('exportXlsx GETs budget/export.xlsx with no params by default', () => {
      api.exportXlsx().subscribe();
      const req = http.expectOne(`${BASE}/budget/export.xlsx`);
      expect(req.request.responseType).toBe('blob');
      expect(req.request.params.keys().length).toBe(0);
      req.flush(new Blob());
    });

    it('exportXlsx sets node/fiscalYear/gremium params when provided', () => {
      api.exportXlsx({ node: 'n-1', fiscalYear: 'fy-1', gremium: 'g-1' }).subscribe();
      const req = http.expectOne((r) => r.url === `${BASE}/budget/export.xlsx`);
      expect(req.request.params.get('node')).toBe('n-1');
      expect(req.request.params.get('fiscalYear')).toBe('fy-1');
      expect(req.request.params.get('gremium')).toBe('g-1');
      req.flush(new Blob());
    });

    it('exportXlsx omits falsy node/fiscalYear/gremium', () => {
      api.exportXlsx({ node: '', fiscalYear: undefined }).subscribe();
      const req = http.expectOne(`${BASE}/budget/export.xlsx`);
      expect(req.request.params.has('node')).toBe(false);
      expect(req.request.params.has('fiscalYear')).toBe(false);
      expect(req.request.params.has('gremium')).toBe(false);
      req.flush(new Blob());
    });
  });

  describe('assignBudget', () => {
    it('POSTs the budgetId to assign-budget', () => {
      api.assignBudget('app-1', 'b-1').subscribe();
      const req = http.expectOne(`${BASE}/applications/app-1/assign-budget`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ budgetId: 'b-1', fiscalYearId: null });
      req.flush({ applicationId: 'app-1', budgetId: 'b-1', fiscalYearId: null });
    });

    it('POSTs the explicit fiscalYearId when given', () => {
      api.assignBudget('app-1', 'b-1', 'fy-1').subscribe();
      const req = http.expectOne(`${BASE}/applications/app-1/assign-budget`);
      expect(req.request.body).toEqual({ budgetId: 'b-1', fiscalYearId: 'fy-1' });
      req.flush({ applicationId: 'app-1', budgetId: 'b-1', fiscalYearId: 'fy-1' });
    });

    it('POSTs null to clear the assignment', () => {
      api.assignBudget('app-1', null).subscribe();
      const req = http.expectOne(`${BASE}/applications/app-1/assign-budget`);
      expect(req.request.body).toEqual({ budgetId: null, fiscalYearId: null });
      req.flush({ applicationId: 'app-1', budgetId: null, fiscalYearId: null });
    });
  });
});

describe('re-exported simplifyPathKey', () => {
  it('is the shared implementation', () => {
    expect(simplifyPathKey('VSM-8-81-810')).toBe('VSM-810');
  });
});

describe('flattenBudgetOptions', () => {
  it('pre-order flattens with simplified "pathKey – name" labels', () => {
    const tree = [
      node({
        id: 'a',
        pathKey: 'VS-8-81',
        name: 'Root',
        children: [
          node({ id: 'b', pathKey: 'VS-8-81-330', name: 'Child', children: [] }),
        ],
      }),
    ];
    expect(flattenBudgetOptions(tree)).toEqual([
      { value: 'a', label: 'VS-81 – Root' },
      { value: 'b', label: 'VS-81-330 – Child' },
    ]);
  });

  it('returns an empty list for no nodes', () => {
    expect(flattenBudgetOptions([])).toEqual([]);
  });

  it('handles a node whose children property is empty (no recursion)', () => {
    const tree = [node({ id: 'a', pathKey: 'VS', name: 'Root', children: [] })];
    expect(flattenBudgetOptions(tree)).toEqual([{ value: 'a', label: 'VS – Root' }]);
  });
});

describe('flattenBudgetTreeRows', () => {
  it('pre-order flattens with depth per node', () => {
    const tree = [
      node({
        id: 'a',
        key: 'VS',
        name: 'Root',
        children: [
          node({
            id: 'b',
            key: '800',
            name: 'Child',
            children: [node({ id: 'c', key: '40', name: 'Grandchild', children: [] })],
          }),
        ],
      }),
    ];
    expect(flattenBudgetTreeRows(tree)).toEqual([
      { id: 'a', key: 'VS', name: 'Root', depth: 0 },
      { id: 'b', key: '800', name: 'Child', depth: 1 },
      { id: 'c', key: '40', name: 'Grandchild', depth: 2 },
    ]);
  });

  it('returns an empty list for no nodes', () => {
    expect(flattenBudgetTreeRows([])).toEqual([]);
  });
});
