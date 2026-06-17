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
    fullyBound: false,
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
      // amountMin = 0 is NOT empty/null/undefined → kept and stringified.
      expect(req.request.params.get('amountMin')).toBe('0');
      // q='' and fiscalYear=undefined are dropped.
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
