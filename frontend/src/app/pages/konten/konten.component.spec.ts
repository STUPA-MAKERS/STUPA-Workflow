import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ElementRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { KontenComponent } from './konten.component';
import { KontenLinesState } from './konten-lines.state';
import { PALETTE } from '../budget/budget-year-tree.component';
import type {
  AccountOption,
  BankSyncResult,
  BudgetTreeNode,
  Expense,
  ExpensePage,
  FintsCredentialStatus,
  FiscalYear,
  StatementLine,
  StatementLinePage,
} from '../budget/budget-tree.api';

const ACC: AccountOption = {
  id: 'a-1',
  name: 'Hauptkonto',
  fintsConfigured: true,
  fintsHasCredential: true,
  fintsLastSyncAt: '2026-06-01T10:00:00Z',
  fintsLastBalance: '1234.56',
  fintsBalanceAt: '2026-06-01',
};
const ACC2: AccountOption = {
  ...ACC,
  id: 'a-2',
  name: 'Sparkonto',
  fintsLastBalance: null,
  fintsBalanceAt: null,
};

const LINE: StatementLine = {
  id: 'l-1',
  accountId: 'a-1',
  amount: '-42.00',
  kind: 'expense',
  currency: 'EUR',
  bookingDate: '2026-05-02',
  valueDate: '2026-05-03',
  purpose: 'Miete Mai',
  counterpartyName: 'Max Muster',
  counterpartyIban: 'DE02120300000000202051',
  endToEndId: null,
  reference: null,
  matchState: 'unmatched',
  suggestedBudgetId: null,
  suggestedPathKey: null,
  suggestedExpenseId: null,
  matchedExpenseId: null,
  createdAt: '2026-05-03T00:00:00Z',
};
const LINE_MATCHED: StatementLine = {
  ...LINE,
  id: 'l-2',
  kind: 'income',
  amount: '10.00',
  purpose: 'Erstattung',
  counterpartyName: 'Uni Kasse',
  counterpartyIban: null,
  matchState: 'matched',
  matchedExpenseId: 'e-77',
};
const LINE_IGNORED: StatementLine = { ...LINE, id: 'l-3', matchState: 'ignored' };

const CRED: FintsCredentialStatus = {
  configured: true,
  hasCredential: true,
  fintsLogin: 'user1',
  fintsLastSyncAt: '2026-06-01T10:00:00Z',
  fintsLockedUntil: null,
};

const SYNC_DONE: BankSyncResult = {
  status: 'done',
  accountId: 'a-1',
  imported: 3,
  duplicates: 1,
  sessionToken: null,
  challenge: null,
  challengeHtml: null,
  challengeImage: null,
  decoupled: false,
};
const SYNC_TAN: BankSyncResult = {
  ...SYNC_DONE,
  status: 'needs_tan',
  sessionToken: 'tok-1',
  challenge: 'Bitte TAN eingeben',
  challengeImage: 'data:image/png;base64,QUJD',
};

const EXPENSE: Expense = {
  id: 'e-1',
  budgetId: 'b-1',
  pathKey: 'VS-800',
  fiscalYearId: 'fy-1',
  kind: 'expense',
  amount: '42.00',
  currency: 'EUR',
  description: 'Druckkosten Flyer',
  applicationId: null,
  applicationTitle: null,
  accountId: 'a-1',
  accountName: 'Hauptkonto',
  transferId: null,
  actor: 'admin',
  actorName: 'Admin',
  invoiceDate: null,
  paymentDate: null,
  correspondent: 'Copyshop Müller',
  note: null,
  referenceNumber: null,
  paymentMethod: null,
  category: null,
  invoiceId: null,
  invoiceNumber: null,
  createdAt: '2026-05-30T09:00:00Z',
};

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
  ...FY_ACTIVE,
  id: 'fy-old',
  year: 2025,
  display: '2025',
  active: false,
};

function linePage(items: StatementLine[], total = items.length, offset = 0): StatementLinePage {
  return { items, total, limit: 30, offset };
}
function expPage(items: Expense[], total = items.length): ExpensePage {
  return { items, total, limit: 10, offset: 0 };
}

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

/** Access to private members (toast/i18n + private helpers). */
interface Priv {
  toast: { success: (m: string) => void; error: (m: string) => void; show: (m: string, k: string) => void };
  i18n: { translate: (k: string, p?: Record<string, string>) => string };
  syncError: (e: unknown) => string;
  refreshOnLock: (e: unknown) => void;
}
const priv = (cmp: KontenComponent): Priv => cmp as unknown as Priv;

interface Built {
  cmp: KontenComponent;
  http: HttpTestingController;
}

/**
 * Instantiate the component directly. The constructor loads the account options and the
 * cost-center tree. When the caller passes accounts, flush the account-selection effect
 * with `TestBed.tick()` at once. That effect loads the lines and the connection status.
 * Without the flush it fires uncontrolled on the next fake-timer tick.
 */
function build(
  opts: {
    perms?: string[];
    tree?: BudgetTreeNode[];
    accounts?: AccountOption[];
    treeError?: boolean;
    accountsError?: boolean;
    host?: HTMLElement;
  } = {},
): Built {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts.perms ?? ['budget.view', 'budget.book']) },
      // Host element for focusOtp(). Without a fixture there is no native component element.
      { provide: ElementRef, useValue: new ElementRef(opts.host ?? document.createElement('div')) },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const cmp = TestBed.runInInjectionContext(() => new KontenComponent());

  const accReq = http.expectOne((r) => r.url.endsWith('/accounts/options'));
  if (opts.accountsError) accReq.error(new ProgressEvent('err'));
  else accReq.flush(opts.accounts ?? []);

  const treeReq = http.expectOne((r) => r.url.endsWith('/budgets'));
  if (opts.treeError) treeReq.error(new ProgressEvent('err'));
  else treeReq.flush(opts.tree ?? []);

  if (!opts.accountsError && (opts.accounts?.length ?? 0) > 0) {
    // Effect: first account selected → load the first page + connection status.
    TestBed.tick();
    http
      .expectOne((r) => r.url.endsWith('/statement-lines') && r.method === 'GET')
      .flush(linePage([]));
    http
      .expectOne((r) => r.url.endsWith('/fints/credential') && r.method === 'GET')
      .flush(CRED);
  }

  return { cmp, http };
}

/** Catch and answer the next GET /statement-lines (reload or fetch). */
function flushLines(http: HttpTestingController, body: StatementLinePage): void {
  http.expectOne((r) => r.url.endsWith('/statement-lines') && r.method === 'GET').flush(body);
}

/** OTP host with six `[data-otp]` inputs for focus control. */
function otpHost(): HTMLElement {
  const div = document.createElement('div');
  for (let i = 0; i < 6; i++) {
    const inp = document.createElement('input');
    inp.setAttribute('data-otp', String(i));
    div.appendChild(inp);
  }
  return div;
}

describe('KontenComponent (unit)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
    jest.useRealTimers();
  });

  it('loads accounts on construction and selects the first one', () => {
    const { cmp } = build({ accounts: [ACC, ACC2], tree: ROOT_TREE });
    expect(cmp.accounts()).toEqual([ACC, ACC2]);
    expect(cmp.accountId()).toBe('a-1');
    expect(cmp.selectedAccount()).toEqual(ACC);
    expect(cmp.accountOptions()).toEqual([
      { value: 'a-1', label: 'Hauptkonto' },
      { value: 'a-2', label: 'Sparkonto' },
    ]);
    // Cost-center tree → options (top + child)
    expect(cmp.costCentreOptions().length).toBe(2);
  });

  it('resets accounts and cost-centre options on construction errors', () => {
    const { cmp } = build({ accountsError: true, treeError: true });
    expect(cmp.accounts()).toEqual([]);
    expect(cmp.accountId()).toBe('');
    expect(cmp.selectedAccount()).toBeNull();
    expect(cmp.costCentreOptions()).toEqual([]);
  });

  it('canBook reflects the budget.book permission', () => {
    const yes = build({ perms: ['budget.book'] });
    expect(yes.cmp.canBook()).toBe(true);
    yes.http.verify();
    TestBed.resetTestingModule();
    const no = build({ perms: ['budget.view'] });
    expect(no.cmp.canBook()).toBe(false);
  });

  it('canIgnore reflects the budget.reconcile_ignore permission', () => {
    const yes = build({ perms: ['budget.reconcile_ignore'] });
    expect(yes.cmp.canIgnore()).toBe(true);
    yes.http.verify();
    TestBed.resetTestingModule();
    const no = build({ perms: ['budget.book'] });
    expect(no.cmp.canIgnore()).toBe(false);
  });

  it('selectAccount switches the account and discards a pending TAN session', () => {
    const { cmp } = build({ accounts: [ACC, ACC2] });
    cmp.sessionToken.set('tok-1');
    cmp.selectAccount('a-1'); // same selection → no-op
    expect(cmp.sessionToken()).toBe('tok-1');
    cmp.selectAccount('a-2');
    expect(cmp.accountId()).toBe('a-2');
    expect(cmp.sessionToken()).toBe('');
  });

  it('dotColor rotates through the palette; accountBalance handles a missing balance', () => {
    const { cmp } = build();
    expect(cmp.dotColor(0)).toBe(PALETTE[0]);
    expect(cmp.dotColor(PALETTE.length)).toBe(PALETTE[0]);
    expect(cmp.dotColor(1)).toBe(PALETTE[1]);
    expect(cmp.accountBalance(ACC).replace(/\s/g, ' ')).toContain('1.234,56');
    expect(cmp.accountBalance(ACC2)).toBe('');
  });

  it('reloadLines is a no-op without a selected account', () => {
    const { cmp, http } = build();
    cmp.reloadLines();
    http.expectNone((r) => r.url.endsWith('/statement-lines'));
  });

  it('reloadLines fetches the first page with default params and stores it', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.reloadLines();
    expect(cmp.loadingLines()).toBe(true);
    const req = http.expectOne((r) => r.url.endsWith('/statement-lines') && r.method === 'GET');
    const p = req.request.params;
    expect(p.get('account')).toBe('a-1');
    expect(p.get('limit')).toBe('30');
    expect(p.get('offset')).toBe('0');
    expect(p.get('sort')).toBe('date');
    expect(p.get('order')).toBe('desc');
    expect(p.has('linked')).toBe(false);
    expect(p.has('kind')).toBe(false);
    expect(p.has('q')).toBe(false);
    expect(p.has('dateFrom')).toBe(false);
    expect(p.has('dateTo')).toBe(false);
    req.flush(linePage([LINE], 1));
    expect(cmp.lines()).toEqual([LINE]);
    expect(cmp.total()).toBe(1);
    expect(cmp.loadingLines()).toBe(false);
    expect(cmp.hasMore()).toBe(false);
  });

  it('fetch maps the state filter to linked=true/false and passes all filters', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.kind.set('expense');
    cmp.searchQ.set('  miete ');
    cmp.dateFrom.set('2026-01-01');
    cmp.dateTo.set('2026-12-31');
    cmp.setState('linked');
    const req = http.expectOne((r) => r.url.endsWith('/statement-lines'));
    const p = req.request.params;
    expect(p.get('linked')).toBe('true');
    expect(p.get('kind')).toBe('expense');
    expect(p.get('q')).toBe('miete');
    expect(p.get('dateFrom')).toBe('2026-01-01');
    expect(p.get('dateTo')).toBe('2026-12-31');
    req.flush(linePage([]));

    cmp.setState('open');
    const req2 = http.expectOne((r) => r.url.endsWith('/statement-lines'));
    expect(req2.request.params.get('linked')).toBe('false');
    req2.flush(linePage([]));
    expect(cmp.filterState()).toBe('open');

    // 'ignored' maps to the explicit state filter, no linked flag.
    cmp.setState('ignored');
    const req3 = http.expectOne((r) => r.url.endsWith('/statement-lines'));
    expect(req3.request.params.get('state')).toBe('ignored');
    expect(req3.request.params.has('linked')).toBe(false);
    req3.flush(linePage([]));
    expect(cmp.filterState()).toBe('ignored');
  });

  it('fetch error on the initial page clears the list; on loadMore it keeps rows', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.reloadLines();
    http.expectOne((r) => r.url.endsWith('/statement-lines')).error(new ProgressEvent('err'));
    expect(cmp.lines()).toEqual([]);
    expect(cmp.loadingLines()).toBe(false);

    cmp.reloadLines();
    flushLines(http, linePage([LINE], 3));
    cmp.loadMore();
    http.expectOne((r) => r.url.endsWith('/statement-lines')).error(new ProgressEvent('err'));
    expect(cmp.lines()).toEqual([LINE]); // existing rows remain
    expect(cmp.loadingMore()).toBe(false);
  });

  it('loadMore appends the next page and advances the offset', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.reloadLines();
    flushLines(http, linePage([LINE], 3));
    expect(cmp.hasMore()).toBe(true);
    cmp.loadMore();
    expect(cmp.loadingMore()).toBe(true);
    const req = http.expectOne((r) => r.url.endsWith('/statement-lines'));
    expect(req.request.params.get('offset')).toBe('1');
    req.flush(linePage([LINE_MATCHED], 3, 1));
    expect(cmp.lines().map((l) => l.id)).toEqual(['l-1', 'l-2']);
    expect(cmp.loadingMore()).toBe(false);
  });

  it('loadMore is a no-op while loading, loadingMore or without more pages', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.reloadLines();
    flushLines(http, linePage([LINE], 1)); // total reached → hasMore false
    cmp.loadMore();
    http.expectNone((r) => r.url.endsWith('/statement-lines'));
    cmp.total.set(5);
    cmp.loadingMore.set(true);
    cmp.loadMore();
    http.expectNone((r) => r.url.endsWith('/statement-lines'));
    cmp.loadingMore.set(false);
    cmp.loadingLines.set(true);
    cmp.loadMore();
    http.expectNone((r) => r.url.endsWith('/statement-lines'));
  });

  it('money/balanceMoney/signedMoney format EUR per locale and sign', () => {
    const { cmp } = build();
    expect(cmp.money('-42.5').replace(/\s/g, ' ')).toContain('42,50');
    expect(cmp.balanceMoney('-42.5').replace(/\s/g, ' ')).toContain('-42,50');
    expect(cmp.signedMoney(LINE)).toContain('−');
    expect(cmp.signedMoney(LINE_MATCHED)).toContain('+');
    localStorage.setItem('ap.locale', 'en');
    TestBed.resetTestingModule();
    const en = build();
    expect(en.cmp.money('120')).toMatch(/120\.00/);
    expect(en.cmp.balanceMoney('-120')).toMatch(/120\.00/);
  });

  it('counterparty splits IBAN and name across all input shapes', () => {
    const { cmp } = build();
    // IBAN set + name with an IBAN prefix → prefix removed
    expect(
      cmp.counterparty({
        ...LINE,
        counterpartyIban: 'DE02120300000000202051',
        counterpartyName: 'DE02120300000000202051 Max Muster',
      }),
    ).toEqual({ name: 'Max Muster', iban: 'DE02120300000000202051' });
    // no IBAN, but the name starts with one → extracted
    expect(
      cmp.counterparty({
        ...LINE,
        counterpartyIban: null,
        counterpartyName: 'DE02120300000000202051 Erika Muster',
      }),
    ).toEqual({ name: 'Erika Muster', iban: 'DE02120300000000202051' });
    // no IBAN, plain name → unchanged
    expect(cmp.counterparty({ ...LINE, counterpartyIban: null, counterpartyName: 'Copyshop' })).toEqual({
      name: 'Copyshop',
      iban: '',
    });
    // both empty/null
    expect(cmp.counterparty({ ...LINE, counterpartyIban: null, counterpartyName: null })).toEqual({
      name: '',
      iban: '',
    });
  });

  it('setKind and onDateFilter reload the list; activeFilterCount counts groups', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    expect(cmp.activeFilterCount()).toBe(0);
    cmp.setKind('income');
    flushLines(http, linePage([]));
    cmp.onDateFilter('from', '2026-01-01');
    flushLines(http, linePage([]));
    cmp.onDateFilter('to', '');
    flushLines(http, linePage([]));
    expect(cmp.kind()).toBe('income');
    expect(cmp.dateFrom()).toBe('2026-01-01');
    expect(cmp.dateTo()).toBe('');
    cmp.filterState.set('open');
    // status + kind + date range = 3 (from/to count as one group)
    expect(cmp.activeFilterCount()).toBe(3);
  });

  it('resetFilters clears every filter and reloads', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.filterState.set('linked');
    cmp.kind.set('expense');
    cmp.dateFrom.set('2026-01-01');
    cmp.dateTo.set('2026-02-01');
    cmp.resetFilters();
    expect(cmp.filterState()).toBe('');
    expect(cmp.kind()).toBe('');
    expect(cmp.dateFrom()).toBe('');
    expect(cmp.dateTo()).toBe('');
    flushLines(http, linePage([]));
  });

  it('onSearch debounces rapid input into a single reload', () => {
    jest.useFakeTimers();
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.onSearch('m');
    cmp.onSearch('miete');
    expect(cmp.searchQ()).toBe('miete');
    http.expectNone((r) => r.url.endsWith('/statement-lines'));
    // The account effect also tracks searchQ, because fetch runs in the effect context.
    // It reloads once on the next scheduler tick. The debounced reload follows at 400 ms.
    jest.advanceTimersByTime(399);
    http.expectOne((r) => r.url.endsWith('/statement-lines')).flush(linePage([]));
    http.expectOne((r) => r.url.endsWith('/fints/credential') && r.method === 'GET').flush(CRED);
    jest.advanceTimersByTime(1);
    const req = http.expectOne((r) => r.url.endsWith('/statement-lines'));
    expect(req.request.params.get('q')).toBe('miete');
    req.flush(linePage([]));
  });

  it('onSort toggles the direction on the same field and resets on a new field', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.onSort('date'); // default date desc → asc
    expect(cmp.sortOrder()).toBe('asc');
    flushLines(http, linePage([]));
    cmp.onSort('date');
    expect(cmp.sortOrder()).toBe('desc');
    flushLines(http, linePage([]));
    cmp.onSort('amount');
    expect(cmp.sortField()).toBe('amount');
    expect(cmp.sortOrder()).toBe('desc');
    flushLines(http, linePage([]));
  });

  it('sortInd and ariaSort describe the active sort column', () => {
    const { cmp } = build();
    expect(cmp.sortInd('date')).toBe(' ↓');
    expect(cmp.sortInd('amount')).toBe('');
    expect(cmp.ariaSort('date')).toBe('descending');
    expect(cmp.ariaSort('amount')).toBe('none');
    cmp.sortOrder.set('asc');
    expect(cmp.sortInd('date')).toBe(' ↑');
    expect(cmp.ariaSort('date')).toBe('ascending');
  });

  it('openConnect prefills the stored login and clears the PIN; closeConnect resets it', () => {
    const { cmp } = build();
    cmp.credStatus.set(CRED);
    cmp.credPin.set('geheim');
    cmp.openConnect();
    expect(cmp.connectOpen()).toBe(true);
    expect(cmp.credLogin()).toBe('user1');
    expect(cmp.credPin()).toBe('');
    cmp.credPin.set('1234');
    cmp.closeConnect();
    expect(cmp.connectOpen()).toBe(false);
    expect(cmp.credPin()).toBe('');
  });

  it('openConnect without a credential status falls back to an empty login', () => {
    const { cmp } = build();
    cmp.openConnect();
    expect(cmp.credLogin()).toBe('');
  });

  it('saveCred is a no-op without account, login, pin or while saving', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.saveCred(); // login+pin missing
    cmp.credLogin.set('user1');
    cmp.saveCred(); // pin missing
    cmp.credPin.set('1234');
    cmp.savingCred.set(true);
    cmp.saveCred(); // busy
    cmp.savingCred.set(false);
    cmp.accountId.set('');
    cmp.saveCred(); // no account
    http.expectNone((r) => r.url.endsWith('/fints/credential'));
  });

  it('saveCred stores the credential, toasts and closes the dialog', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.openConnect();
    cmp.credLogin.set('  user1  ');
    cmp.credPin.set('1234');
    cmp.saveCred();
    const req = http.expectOne(
      (r) => r.url.endsWith('/accounts/a-1/fints/credential') && r.method === 'PUT',
    );
    expect(req.request.body).toEqual({ fintsLogin: 'user1', fintsPin: '1234' });
    req.flush(CRED);
    expect(cmp.savingCred()).toBe(false);
    expect(cmp.credStatus()).toEqual(CRED);
    expect(cmp.connectOpen()).toBe(false);
    expect(success).toHaveBeenCalledWith('Zugangsdaten gespeichert.');
  });

  it('saveCred surfaces a mapped FinTS error on failure', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.credLogin.set('user1');
    cmp.credPin.set('1234');
    cmp.saveCred();
    http
      .expectOne((r) => r.method === 'PUT')
      .flush({ code: 'fints_auth_rejected' }, { status: 400, statusText: 'Bad Request' });
    expect(cmp.savingCred()).toBe(false);
    expect(error).toHaveBeenCalledWith(priv(cmp).i18n.translate('fints.errAuthRejected'));
  });

  it('removeCred deletes the credential, resets TAN state and reloads the status', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.sessionToken.set('tok-1');
    cmp.connectOpen.set(true);
    cmp.removeCred();
    http.expectOne((r) => r.url.endsWith('/accounts/a-1/fints/credential') && r.method === 'DELETE').flush(null);
    expect(cmp.sessionToken()).toBe('');
    expect(cmp.connectOpen()).toBe(false);
    // loadCredStatus: login `null` → empty login, PIN cleared
    http
      .expectOne((r) => r.url.endsWith('/accounts/a-1/fints/credential') && r.method === 'GET')
      .flush({ ...CRED, hasCredential: false, fintsLogin: null });
    expect(cmp.credLogin()).toBe('');
    expect(cmp.connected()).toBe(false);
    expect(success).toHaveBeenCalledWith('Zugangsdaten entfernt.');
  });

  it('removeCred guards and toasts a booking error on failure', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.savingCred.set(true);
    cmp.removeCred(); // busy
    cmp.savingCred.set(false);
    cmp.accountId.set('');
    cmp.removeCred(); // no account
    http.expectNone((r) => r.method === 'DELETE');
    cmp.accountId.set('a-1');
    cmp.removeCred();
    http.expectOne((r) => r.method === 'DELETE').error(new ProgressEvent('err'));
    expect(cmp.savingCred()).toBe(false);
    expect(error).toHaveBeenCalledWith('Buchen fehlgeschlagen.');
  });

  it('loadCredStatus error clears the credential status (via removeCred reload)', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.credStatus.set(CRED);
    cmp.removeCred();
    http.expectOne((r) => r.method === 'DELETE').flush(null);
    http
      .expectOne((r) => r.url.endsWith('/fints/credential') && r.method === 'GET')
      .error(new ProgressEvent('err'));
    expect(cmp.credStatus()).toBeNull();
  });

  it('configured/connected/locked/lockedUntilLabel derive from the credential status', () => {
    const { cmp } = build();
    expect(cmp.configured()).toBe(false);
    expect(cmp.connected()).toBe(false);
    expect(cmp.locked()).toBe(false);
    expect(cmp.lockedUntilLabel()).toBe('');
    const future = new Date(Date.now() + 3_600_000).toISOString();
    cmp.credStatus.set({ ...CRED, fintsLockedUntil: future });
    expect(cmp.configured()).toBe(true);
    expect(cmp.connected()).toBe(true);
    expect(cmp.locked()).toBe(true);
    expect(cmp.lockedUntilLabel()).not.toBe('');
    // expired lock → no longer locked
    cmp.credStatus.set({ ...CRED, fintsLockedUntil: '2020-01-01T00:00:00Z' });
    expect(cmp.locked()).toBe(false);
  });

  it('startSync guards: no account, already syncing, locked', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.credStatus.set(CRED);
    cmp.syncing.set(true);
    cmp.startSync();
    cmp.syncing.set(false);
    cmp.credStatus.set({ ...CRED, fintsLockedUntil: new Date(Date.now() + 3_600_000).toISOString() });
    cmp.startSync();
    cmp.credStatus.set(CRED);
    cmp.accountId.set('');
    cmp.startSync();
    http.expectNone((r) => r.url.endsWith('/fints/sync'));
  });

  it('startSync without a stored credential opens the connect dialog instead', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.credStatus.set({ ...CRED, hasCredential: false, fintsLogin: null });
    cmp.startSync();
    expect(cmp.connectOpen()).toBe(true);
    http.expectNone((r) => r.url.endsWith('/fints/sync'));
  });

  it('startSync done reports counts, reloads lines, status and accounts', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.credStatus.set(CRED);
    cmp.startSync();
    expect(cmp.syncing()).toBe(true);
    http.expectOne((r) => r.url.endsWith('/accounts/a-1/fints/sync') && r.method === 'POST').flush(SYNC_DONE);
    expect(cmp.syncing()).toBe(false);
    expect(success).toHaveBeenCalledWith('3 neu, 1 bereits vorhanden.');
    flushLines(http, linePage([LINE], 1));
    http.expectOne((r) => r.url.endsWith('/fints/credential') && r.method === 'GET').flush(CRED);
    // refreshAccounts after sync: the existing selection is kept
    http.expectOne((r) => r.url.endsWith('/accounts/options')).flush([ACC, ACC2]);
    expect(cmp.accountId()).toBe('a-1');
    expect(cmp.accounts().length).toBe(2);
  });

  it('startSync needs_tan stores the TAN challenge incl. a safe data-URL image', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.credStatus.set(CRED);
    cmp.startSync();
    http.expectOne((r) => r.url.endsWith('/fints/sync')).flush(SYNC_TAN);
    expect(cmp.hasPendingTan()).toBe(true);
    expect(cmp.sessionToken()).toBe('tok-1');
    expect(cmp.challenge()).toBe('Bitte TAN eingeben');
    expect(cmp.challengeImage()).toBe('data:image/png;base64,QUJD');
    expect(cmp.decoupled()).toBe(false);
  });

  it('handleSync rejects a non-data-URL challenge image and coalesces null fields', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.credStatus.set(CRED);
    cmp.startSync();
    http.expectOne((r) => r.url.endsWith('/fints/sync')).flush({
      ...SYNC_TAN,
      sessionToken: 'tok-2',
      challenge: null,
      challengeImage: 'https://evil.example/x.png',
      decoupled: true,
    });
    expect(cmp.sessionToken()).toBe('tok-2');
    expect(cmp.challenge()).toBe('');
    expect(cmp.challengeImage()).toBe('');
    expect(cmp.decoupled()).toBe(true);
    // Defensive: needs_tan with no token/image at all → empty strings instead of null
    cmp.startSync();
    http
      .expectOne((r) => r.url.endsWith('/fints/sync'))
      .flush({ ...SYNC_TAN, sessionToken: null, challengeImage: null });
    expect(cmp.sessionToken()).toBe('');
    expect(cmp.challengeImage()).toBe('');
  });

  it('startSync error toasts a mapped message and reloads the status on a lock code', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.credStatus.set(CRED);
    cmp.startSync();
    http
      .expectOne((r) => r.url.endsWith('/fints/sync'))
      .flush({ code: 'fints_bank_locked' }, { status: 423, statusText: 'Locked' });
    expect(cmp.syncing()).toBe(false);
    expect(error).toHaveBeenCalledWith(priv(cmp).i18n.translate('fints.errBankLocked'));
    // lock → reload the connection status
    http.expectOne((r) => r.url.endsWith('/fints/credential') && r.method === 'GET').flush(CRED);

    // other error → no status reload
    cmp.startSync();
    http
      .expectOne((r) => r.url.endsWith('/fints/sync'))
      .flush({ code: 'fints_pin_undecryptable' }, { status: 400, statusText: 'Bad Request' });
    http.expectNone((r) => r.url.endsWith('/fints/credential'));
  });

  it('refreshOnLock skips the reload without a selected account', () => {
    const { cmp, http } = build();
    priv(cmp).refreshOnLock({ error: { code: 'fints_bank_locked' } });
    http.expectNone((r) => r.url.endsWith('/fints/credential'));
  });

  it('submitTan guards: no account, no session token, busy', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.submitTan(); // no token
    cmp.sessionToken.set('tok-1');
    cmp.tanBusy.set(true);
    cmp.submitTan(); // busy
    cmp.tanBusy.set(false);
    cmp.accountId.set('');
    cmp.submitTan(); // no account
    http.expectNone((r) => r.url.includes('/fints/sessions/'));
  });

  it('submitTan keeps the session pending while the decoupled TAN is unapproved', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const show = jest.spyOn(priv(cmp).toast, 'show');
    cmp.sessionToken.set('tok-1');
    cmp.tanCode.set(' 123456 ');
    cmp.submitTan();
    const req = http.expectOne(
      (r) => r.url.endsWith('/accounts/a-1/fints/sessions/tok-1/tan') && r.method === 'POST',
    );
    expect(req.request.body).toEqual({ tan: '123456' });
    req.flush({ ...SYNC_TAN, imported: 0 });
    expect(cmp.tanBusy()).toBe(false);
    expect(cmp.sessionToken()).toBe('tok-1'); // session stays open
    expect(show).toHaveBeenCalledWith('Noch nicht freigegeben — bitte in der App bestätigen.', 'info');
  });

  it('submitTan done resets the TAN state and finishes the sync', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.sessionToken.set('tok-1');
    cmp.tanCode.set('123456');
    cmp.submitTan();
    http.expectOne((r) => r.url.includes('/fints/sessions/tok-1/tan')).flush(SYNC_DONE);
    expect(cmp.sessionToken()).toBe('');
    expect(cmp.tanCode()).toBe('');
    expect(success).toHaveBeenCalled();
    flushLines(http, linePage([]));
    http.expectOne((r) => r.url.endsWith('/fints/credential') && r.method === 'GET').flush(CRED);
    http.expectOne((r) => r.url.endsWith('/accounts/options')).flush([ACC]);
  });

  it('submitTan error toasts and reloads the status on an auth-rejected code', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.sessionToken.set('tok-1');
    cmp.submitTan();
    http
      .expectOne((r) => r.url.includes('/fints/sessions/tok-1/tan'))
      .flush({ code: 'fints_auth_rejected' }, { status: 403, statusText: 'Forbidden' });
    expect(cmp.tanBusy()).toBe(false);
    expect(error).toHaveBeenCalledWith(priv(cmp).i18n.translate('fints.errAuthRejected'));
    http.expectOne((r) => r.url.endsWith('/fints/credential') && r.method === 'GET').flush(CRED);
  });

  it('syncError maps every known FinTS code and falls back generically', () => {
    const { cmp } = build();
    const p = priv(cmp);
    const cases: [string, string][] = [
      ['fints_not_configured', 'fints.errNotConfigured'],
      ['fints_no_credential', 'fints.errNoCredential'],
      ['fints_pin_undecryptable', 'fints.errPin'],
      ['fints_tan_expired', 'fints.errTanExpired'],
      ['fints_bank_locked', 'fints.errBankLocked'],
      ['fints_auth_rejected', 'fints.errAuthRejected'],
    ];
    for (const [code, key] of cases) {
      expect(p.syncError({ error: { code } })).toBe(p.i18n.translate(key));
    }
    expect(p.syncError({ error: {} })).toBe(p.i18n.translate('fints.errSync'));
    expect(p.syncError(undefined)).toBe(p.i18n.translate('fints.errSync'));
  });

  it('closeTan discards the pending TAN session completely', () => {
    const { cmp } = build();
    cmp.sessionToken.set('tok-1');
    cmp.challenge.set('x');
    cmp.challengeImage.set('data:image/png;base64,QUJD');
    cmp.decoupled.set(true);
    cmp.tanCode.set('123');
    cmp.otpMode.set(false);
    cmp.closeTan();
    expect(cmp.hasPendingTan()).toBe(false);
    expect(cmp.challenge()).toBe('');
    expect(cmp.challengeImage()).toBe('');
    expect(cmp.decoupled()).toBe(false);
    expect(cmp.tanCode()).toBe('');
    expect(cmp.otpMode()).toBe(true);
    expect(cmp.otpDigits()).toEqual(['', '', '', '', '', '']);
  });

  it('tanReady requires 6 digits in OTP mode, any input in single-field mode', () => {
    const { cmp } = build();
    expect(cmp.tanReady()).toBe(false);
    cmp.tanCode.set('123456');
    expect(cmp.tanReady()).toBe(true);
    cmp.tanCode.set('123');
    expect(cmp.tanReady()).toBe(false);
    cmp.useSingleTanField();
    expect(cmp.otpMode()).toBe(false);
    expect(cmp.tanCode()).toBe('');
    cmp.tanCode.set('12');
    expect(cmp.tanReady()).toBe(true);
  });

  it('onOtpInput keeps the last digit, syncs the TAN and advances the focus', () => {
    const focusSpy = jest.spyOn(HTMLInputElement.prototype, 'focus').mockImplementation(() => undefined);
    const { cmp } = build({ host: otpHost() });
    const el = document.createElement('input');
    el.value = 'a57';
    cmp.onOtpInput(0, { target: el } as unknown as Event);
    expect(cmp.otpDigits()[0]).toBe('7');
    expect(el.value).toBe('7');
    expect(cmp.tanCode()).toBe('7');
    expect(focusSpy).toHaveBeenCalledTimes(1); // → box 1
    // last box → no forward focus
    el.value = '9';
    cmp.onOtpInput(5, { target: el } as unknown as Event);
    expect(focusSpy).toHaveBeenCalledTimes(1);
    // non-digit → slot cleared, no focus jump
    el.value = 'x';
    cmp.onOtpInput(1, { target: el } as unknown as Event);
    expect(cmp.otpDigits()[1]).toBe('');
    expect(focusSpy).toHaveBeenCalledTimes(1);
    focusSpy.mockRestore();
  });

  it('onOtpKeydown handles backspace on an empty box (and only then)', () => {
    const focusSpy = jest.spyOn(HTMLInputElement.prototype, 'focus').mockImplementation(() => undefined);
    const { cmp } = build({ host: otpHost() });
    cmp.otpDigits.set(['1', '', '', '', '', '']);
    const prevent = jest.fn();
    cmp.onOtpKeydown(1, { key: 'Backspace', preventDefault: prevent } as unknown as KeyboardEvent);
    expect(prevent).toHaveBeenCalled();
    expect(cmp.otpDigits()[0]).toBe(''); // previous box cleared
    expect(focusSpy).toHaveBeenCalledTimes(1);
    // box not empty → no-op
    cmp.otpDigits.set(['1', '2', '', '', '', '']);
    cmp.onOtpKeydown(1, { key: 'Backspace', preventDefault: prevent } as unknown as KeyboardEvent);
    // first box → no-op
    cmp.onOtpKeydown(0, { key: 'Backspace', preventDefault: prevent } as unknown as KeyboardEvent);
    // other key → no-op
    cmp.onOtpKeydown(1, { key: 'a', preventDefault: prevent } as unknown as KeyboardEvent);
    expect(prevent).toHaveBeenCalledTimes(1);
    focusSpy.mockRestore();
  });

  it('onOtpPaste distributes pasted digits and focuses the last filled box', () => {
    const focusSpy = jest.spyOn(HTMLInputElement.prototype, 'focus').mockImplementation(() => undefined);
    const { cmp } = build({ host: otpHost() });
    const prevent = jest.fn();
    cmp.onOtpPaste({
      clipboardData: { getData: () => '12-34-56-78' },
      preventDefault: prevent,
    } as unknown as ClipboardEvent);
    expect(cmp.otpDigits()).toEqual(['1', '2', '3', '4', '5', '6']); // capped to 6
    expect(cmp.tanCode()).toBe('123456');
    expect(prevent).toHaveBeenCalled();
    // partial paste → rest empty
    cmp.onOtpPaste({
      clipboardData: { getData: () => '12' },
      preventDefault: prevent,
    } as unknown as ClipboardEvent);
    expect(cmp.otpDigits()).toEqual(['1', '2', '', '', '', '']);
    // without digits (or without clipboardData) → no-op
    cmp.onOtpPaste({ clipboardData: null, preventDefault: prevent } as unknown as ClipboardEvent);
    expect(cmp.otpDigits()).toEqual(['1', '2', '', '', '', '']);
    focusSpy.mockRestore();
  });

  it('focusOtp tolerates a host without OTP boxes', () => {
    const { cmp } = build(); // empty host → querySelector returns null
    const el = document.createElement('input');
    el.value = '5';
    expect(() => cmp.onOtpInput(0, { target: el } as unknown as Event)).not.toThrow();
  });

  it('openImport prefills budget suggestion + purpose and loads fiscal years', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.openImport({ ...LINE, suggestedBudgetId: 'child-1' });
    expect(cmp.importLine()?.id).toBe('l-1');
    expect(cmp.impBudgetId()).toBe('child-1');
    expect(cmp.impDescription()).toBe('Miete Mai');
    // a single fiscal year → preselected
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_ACTIVE]);
    expect(cmp.fiscalYearOptions()).toEqual([{ value: 'fy-active', label: '2026' }]);
    expect(cmp.impFiscalYearId()).toBe('fy-active');
  });

  it('openImport without a suggestion clears the fiscal years (null purpose → empty)', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.fiscalYearOptions.set([{ value: 'x', label: 'X' }]);
    cmp.openImport({ ...LINE, purpose: null });
    expect(cmp.impBudgetId()).toBe('');
    expect(cmp.impDescription()).toBe('');
    expect(cmp.fiscalYearOptions()).toEqual([]);
    http.expectNone((r) => r.url.includes('/fiscal-years'));
  });

  it('onPickImportBudget loads fiscal years; multiple years are not auto-selected', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.onPickImportBudget('child-1');
    expect(cmp.impBudgetId()).toBe('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).flush([FY_ACTIVE, FY_OLD]);
    expect(cmp.fiscalYearOptions().length).toBe(2);
    expect(cmp.impFiscalYearId()).toBe('');
  });

  it('loadFiscalYears skips unknown budgets and resets the options on error', () => {
    const { cmp, http } = build({ tree: ROOT_TREE });
    cmp.onPickImportBudget('ghost'); // not in the tree → no request
    http.expectNone((r) => r.url.includes('/fiscal-years'));
    cmp.onPickImportBudget('child-1');
    http.expectOne((r) => r.url.endsWith('/budgets/top-1/fiscal-years')).error(new ProgressEvent('err'));
    expect(cmp.fiscalYearOptions()).toEqual([]);
  });

  it('confirmImport books the line, toasts, closes the dialog and reloads', () => {
    const { cmp, http } = build({ accounts: [ACC], tree: ROOT_TREE });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.importLine.set(LINE);
    cmp.impBudgetId.set('child-1');
    cmp.impFiscalYearId.set('fy-active');
    cmp.impDescription.set('  Miete  ');
    cmp.confirmImport();
    const req = http.expectOne(
      (r) => r.url.endsWith('/statement-lines/l-1/confirm') && r.method === 'POST',
    );
    expect(req.request.body).toEqual({
      budgetId: 'child-1',
      fiscalYearId: 'fy-active',
      description: 'Miete',
    });
    req.flush(EXPENSE);
    expect(cmp.booking()).toBe(false);
    expect(cmp.importLine()).toBeNull();
    expect(success).toHaveBeenCalledWith('Umsatz gebucht.');
    flushLines(http, linePage([]));
  });

  it('confirmImport omits an empty fiscal year and description', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.importLine.set(LINE);
    cmp.impBudgetId.set('child-1');
    cmp.impFiscalYearId.set('');
    cmp.impDescription.set('   ');
    cmp.confirmImport();
    const req = http.expectOne((r) => r.url.endsWith('/statement-lines/l-1/confirm'));
    expect(req.request.body.fiscalYearId).toBeUndefined();
    expect(req.request.body.description).toBeUndefined();
    req.flush(EXPENSE);
    flushLines(http, linePage([]));
  });

  it('confirmImport guards: no line, no budget, already booking; error toasts', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.confirmImport(); // no line
    cmp.importLine.set(LINE);
    cmp.confirmImport(); // no cost center
    cmp.impBudgetId.set('child-1');
    cmp.booking.set(true);
    cmp.confirmImport(); // busy
    http.expectNone((r) => r.url.endsWith('/confirm'));
    cmp.booking.set(false);
    cmp.confirmImport();
    http
      .expectOne((r) => r.url.endsWith('/statement-lines/l-1/confirm'))
      .flush({ code: 'fints_bank_locked' }, { status: 423, statusText: 'Locked' });
    expect(cmp.booking()).toBe(false);
    expect(error).toHaveBeenCalledWith(priv(cmp).i18n.translate('fints.errBankLocked'));
  });

  it('candidateLabel joins description, amount and optional correspondent/pathKey', () => {
    const { cmp } = build();
    const full = cmp.candidateLabel(EXPENSE).replace(/\s/g, ' ');
    expect(full).toContain('Druckkosten Flyer');
    expect(full).toContain('42,00');
    expect(full).toContain('Copyshop Müller');
    expect(full).toContain('VS-800');
    const sparse = cmp.candidateLabel({ ...EXPENSE, correspondent: null, pathKey: null });
    expect(sparse).not.toContain('Copyshop');
    expect(sparse.split(' · ').length).toBe(2);
  });

  it('openLink seeds a search bounded to the exact amount and kind', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.openLink(LINE);
    expect(cmp.linkLine()).toBe(LINE);
    expect(cmp.linkQuery()).toBe('');
    expect(cmp.linkLoading()).toBe(true);
    const req = http.expectOne((r) => r.url.endsWith('/expenses') && r.method === 'GET');
    const p = req.request.params;
    expect(p.get('account')).toBe('a-1');
    expect(p.get('kind')).toBe('expense');
    expect(p.get('unallocated')).toBe('true');
    expect(p.get('amountMin')).toBe('42');
    expect(p.get('amountMax')).toBe('42');
    expect(p.get('limit')).toBe('10');
    expect(p.has('q')).toBe(false);
    req.flush(expPage([EXPENSE]));
    expect(cmp.linkCandidates()).toEqual([EXPENSE]);
    expect(cmp.linkLoading()).toBe(false);
  });

  it('onLinkSearch debounces and searches freely (no amount bounds) with a query', () => {
    jest.useFakeTimers();
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.onLinkSearch('x'); // without an open dialog → no-op
    jest.advanceTimersByTime(300);
    http.expectNone((r) => r.url.endsWith('/expenses'));
    cmp.linkLine.set(LINE);
    cmp.linkSelected.set(EXPENSE);
    cmp.onLinkSearch('fly');
    cmp.onLinkSearch('flyer');
    expect(cmp.linkQuery()).toBe('flyer');
    expect(cmp.linkSelected()).toBeNull();
    http.expectNone((r) => r.url.endsWith('/expenses'));
    jest.advanceTimersByTime(300);
    const req = http.expectOne((r) => r.url.endsWith('/expenses'));
    expect(req.request.params.get('q')).toBe('flyer');
    expect(req.request.params.has('amountMin')).toBe(false);
    expect(req.request.params.has('amountMax')).toBe(false);
    req.flush(expPage([]));
  });

  it('searchLinkCandidates clears the candidates on error', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.linkCandidates.set([EXPENSE]);
    cmp.openLink(LINE);
    http.expectOne((r) => r.url.endsWith('/expenses')).error(new ProgressEvent('err'));
    expect(cmp.linkCandidates()).toEqual([]);
    expect(cmp.linkLoading()).toBe(false);
  });

  it('pickLinkCandidate selects and mirrors the label into the query', () => {
    const { cmp } = build();
    cmp.linkCandidates.set([EXPENSE]);
    cmp.pickLinkCandidate(EXPENSE);
    expect(cmp.linkSelected()).toBe(EXPENSE);
    expect(cmp.linkCandidates()).toEqual([]);
    expect(cmp.linkQuery()).toBe(cmp.candidateLabel(EXPENSE));
  });

  it('closeLink clears the dialog and cancels a pending typeahead', () => {
    jest.useFakeTimers();
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.closeLink(); // without a timer → no error
    cmp.linkLine.set(LINE);
    cmp.onLinkSearch('flyer');
    cmp.closeLink();
    expect(cmp.linkLine()).toBeNull();
    jest.advanceTimersByTime(300);
    http.expectNone((r) => r.url.endsWith('/expenses'));
  });

  it('confirmLink posts the match, toasts and reloads; guards + error path', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.confirmLink(); // no line
    cmp.linkLine.set(LINE);
    cmp.confirmLink(); // no selection
    cmp.linkSelected.set(EXPENSE);
    cmp.booking.set(true);
    cmp.confirmLink(); // busy
    http.expectNone((r) => r.url.endsWith('/confirm'));
    cmp.booking.set(false);
    cmp.confirmLink();
    const req = http.expectOne(
      (r) => r.url.endsWith('/statement-lines/l-1/confirm') && r.method === 'POST',
    );
    expect(req.request.body).toEqual({ matchExpenseId: 'e-1' });
    req.flush(EXPENSE);
    expect(cmp.linkLine()).toBeNull();
    expect(success).toHaveBeenCalledWith('Mit Buchung verknüpft.');
    flushLines(http, linePage([]));

    cmp.linkLine.set(LINE);
    cmp.linkSelected.set(EXPENSE);
    cmp.confirmLink();
    http
      .expectOne((r) => r.url.endsWith('/statement-lines/l-1/confirm'))
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(cmp.booking()).toBe(false);
    expect(error).toHaveBeenCalledWith(priv(cmp).i18n.translate('fints.errSync'));
  });

  it('unlink releases the match, toasts and reloads; guard + error path', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.booking.set(true);
    cmp.unlink(LINE_MATCHED); // busy → no-op
    http.expectNone((r) => r.url.endsWith('/unlink'));
    cmp.booking.set(false);
    cmp.unlink(LINE_MATCHED);
    http
      .expectOne((r) => r.url.endsWith('/statement-lines/l-2/unlink') && r.method === 'POST')
      .flush({ ...LINE_MATCHED, matchState: 'unmatched' });
    expect(cmp.booking()).toBe(false);
    expect(success).toHaveBeenCalledWith('Verknüpfung gelöst.');
    flushLines(http, linePage([]));

    cmp.unlink(LINE_MATCHED);
    http.expectOne((r) => r.url.endsWith('/unlink')).error(new ProgressEvent('err'));
    expect(cmp.booking()).toBe(false);
    expect(error).toHaveBeenCalledWith('Buchen fehlgeschlagen.');
  });

  it('openIgnore + confirmIgnore posts the trimmed reason, closes, toasts, reloads; guard + close', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.confirmIgnore(); // no line selected → no-op
    http.expectNone((r) => r.url.endsWith('/ignore'));
    cmp.openIgnore(LINE);
    expect(cmp.ignoreLine()).toEqual(LINE);
    cmp.closeIgnore();
    expect(cmp.ignoreLine()).toBeNull();

    cmp.openIgnore(LINE);
    cmp.ignoreReason.set('  Doppelbuchung  ');
    cmp.booking.set(true);
    cmp.confirmIgnore(); // busy → no-op
    http.expectNone((r) => r.url.endsWith('/ignore'));
    cmp.booking.set(false);
    cmp.confirmIgnore();
    const req = http.expectOne(
      (r) => r.url.endsWith('/statement-lines/l-1/ignore') && r.method === 'POST',
    );
    expect(req.request.body).toEqual({ reason: 'Doppelbuchung' });
    req.flush(null);
    expect(cmp.ignoreLine()).toBeNull();
    expect(cmp.booking()).toBe(false);
    expect(success).toHaveBeenCalledWith('Transaktion ignoriert.');
    flushLines(http, linePage([]));
  });

  it('confirmIgnore without a reason omits it and surfaces an error', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.openIgnore(LINE);
    cmp.confirmIgnore();
    const req = http.expectOne((r) => r.url.endsWith('/ignore'));
    expect(req.request.body.reason).toBeUndefined();
    req.error(new ProgressEvent('err'));
    expect(cmp.booking()).toBe(false);
    expect(error).toHaveBeenCalled();
  });

  it('reactivate returns an ignored line to the queue; guard + error path', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.booking.set(true);
    cmp.reactivate(LINE_IGNORED); // busy → no-op
    http.expectNone((r) => r.url.endsWith('/reactivate'));
    cmp.booking.set(false);
    cmp.reactivate(LINE_IGNORED);
    http
      .expectOne((r) => r.url.endsWith('/statement-lines/l-3/reactivate') && r.method === 'POST')
      .flush({ ...LINE_IGNORED, matchState: 'unmatched' });
    expect(cmp.booking()).toBe(false);
    expect(success).toHaveBeenCalledWith('Transaktion reaktiviert.');
    flushLines(http, linePage([]));

    cmp.reactivate(LINE_IGNORED);
    http.expectOne((r) => r.url.endsWith('/reactivate')).error(new ProgressEvent('err'));
    expect(cmp.booking()).toBe(false);
    expect(error).toHaveBeenCalled();
  });

  it('ngOnDestroy cancels pending search and typeahead timers', () => {
    jest.useFakeTimers();
    // Without an account the debounced reload hits the guard anyway. The link typeahead
    // would still fire an /expenses request after 300 ms without clearTimeout.
    const { cmp, http } = build();
    cmp.onSearch('miete');
    cmp.linkLine.set(LINE);
    cmp.onLinkSearch('flyer');
    cmp.ngOnDestroy();
    jest.advanceTimersByTime(1000);
    http.expectNone((r) => r.url.endsWith('/statement-lines'));
    http.expectNone((r) => r.url.endsWith('/expenses'));
  });

  it('ngOnDestroy is safe without pending timers', () => {
    const { cmp } = build();
    expect(() => cmp.ngOnDestroy()).not.toThrow();
  });
});

// Rendered tests: the account effect (a selection loads lines and status), the table,
// permission gating and infinite scroll (the IntersectionObserver branch).

async function setup(
  opts: {
    perms?: string[];
    accounts?: AccountOption[];
    page?: StatementLinePage;
    cred?: FintsCredentialStatus;
  } = {},
) {
  const view = await render(KontenComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(opts.perms ?? ['budget.view', 'budget.book']) },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.match((r) => r.url.endsWith('/accounts/options')).forEach((req) => req.flush(opts.accounts ?? [ACC]));
  http.match((r) => r.url.endsWith('/budgets')).forEach((req) => req.flush([]));
  // Effect: account selected → load transactions + connection status.
  view.detectChanges();
  http
    .match((r) => r.url.endsWith('/statement-lines') && r.method === 'GET')
    .forEach((req) => req.flush(opts.page ?? linePage([])));
  http
    .match((r) => r.url.endsWith('/fints/credential') && r.method === 'GET')
    .forEach((req) => req.flush(opts.cred ?? CRED));
  return { ...view, http };
}

describe('KontenComponent (rendered)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists transactions with counterparty, purpose, signed amount and row actions', async () => {
    await setup({ page: linePage([LINE, LINE_MATCHED], 2) });
    expect(await screen.findByText('Miete Mai')).toBeInTheDocument();
    expect(screen.getByText('Max Muster')).toBeInTheDocument();
    expect(screen.getByText('DE02120300000000202051')).toBeInTheDocument();
    expect(screen.getByText(/−.*42/)).toBeInTheDocument();
    expect(screen.getByText(/\+.*10/)).toBeInTheDocument();
    // open row → link/import, linked row → unlink
    expect(screen.getByRole('button', { name: 'Verknüpfen' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Importieren' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Trennen' })).toBeInTheDocument();
    // balance from the account option in the header
    expect(screen.getByText(/Kontostand/)).toBeInTheDocument();
  });

  it('shows the empty state for an account without transactions', async () => {
    await setup();
    expect(await screen.findByText('Noch keine Transaktionen — synchronisieren.')).toBeInTheDocument();
  });

  it('asks to pick an account when none exist', async () => {
    await setup({ accounts: [] });
    expect(await screen.findByText('Keine Konten vorhanden.')).toBeInTheDocument();
    expect(screen.getByText('Konto links wählen.')).toBeInTheDocument();
  });

  it('hides sync/connection and row actions for a viewer without budget.book', async () => {
    await setup({ perms: ['budget.view'], page: linePage([LINE], 1) });
    expect(await screen.findByText('Miete Mai')).toBeInTheDocument();
    expect(screen.queryByText('Verbindung')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Verknüpfen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Importieren' })).toBeNull();
  });
});

// IntersectionObserver branch: a visible sentinel loads the next page.
describe('KontenComponent (infinite scroll)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('observes the sentinel and loads more when it intersects', async () => {
    let trigger: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
    const observe = jest.fn();
    const disconnect = jest.fn();
    class IOStub {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        trigger = cb;
      }
      observe = observe;
      disconnect = disconnect;
    }
    (globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver = IOStub;

    const { http, detectChanges } = await setup({ page: linePage([LINE], 3) });
    detectChanges(); // sentinel rendered → the effect observes it
    expect(observe).toHaveBeenCalled();

    trigger?.([{ isIntersecting: true }]);
    http
      .match((r) => r.url.endsWith('/statement-lines') && r.method === 'GET')
      .forEach((req) => req.flush(linePage([LINE_MATCHED], 3, 1)));
    // not visible → no further request
    trigger?.([{ isIntersecting: false }]);
    http.expectNone((r) => r.url.endsWith('/statement-lines') && r.method === 'GET');

    delete (globalThis as unknown as { IntersectionObserver?: unknown }).IntersectionObserver;
    http.verify();
  });
});

// Bulk actions and cross-links (#expenses-ux): selection, bulk unlink and ignore,
// the match-state subset computeds and the bookingLink deep-link.

const LINE_SUGGESTED: StatementLine = { ...LINE, id: 'l-4', matchState: 'suggested' };

describe('KontenComponent (batch/bulk #expenses-ux)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
    jest.useRealTimers();
  });

  it('bookingLink uses the exact booking id when present, else the text fallback', () => {
    const { cmp } = build();
    // Matched line with an allocation → exact deep link via the hidden id filter.
    expect(cmp.bookingLink(LINE_MATCHED)).toEqual({ id: 'e-77' });
    // No matchedExpenseId (legacy) → account + reference/endToEndId/purpose fallback.
    expect(cmp.bookingLink(LINE)).toEqual({ account: 'a-1', q: 'Miete Mai' }); // purpose
    expect(cmp.bookingLink({ ...LINE, reference: 'RF-1' })).toEqual({ account: 'a-1', q: 'RF-1' });
    expect(cmp.bookingLink({ ...LINE, purpose: null, endToEndId: 'E2E-9' })).toEqual({
      account: 'a-1',
      q: 'E2E-9',
    });
    expect(
      cmp.bookingLink({ ...LINE, purpose: null, reference: null, endToEndId: null }),
    ).toEqual({ account: 'a-1', q: null });
  });

  it('isSelected/toggleSelect/toggleSelectAll manage the selection', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.reloadLines();
    flushLines(http, linePage([LINE, LINE_SUGGESTED, LINE_MATCHED, LINE_IGNORED], 4));
    expect(cmp.isSelected('l-1')).toBe(false);
    cmp.toggleSelect('l-1', true);
    expect(cmp.isSelected('l-1')).toBe(true);
    cmp.toggleSelect('l-1', false);
    expect(cmp.selectedCount()).toBe(0);
    expect(cmp.allSelected()).toBe(false);
    cmp.toggleSelectAll(true);
    expect(cmp.selectedCount()).toBe(4);
    expect(cmp.allSelected()).toBe(true);
    expect(cmp.selectedMatched()).toBe(1); // l-2
    expect(cmp.selectedIgnorable()).toBe(2); // l-1 unmatched and l-4 suggested
    cmp.toggleSelectAll(false);
    expect(cmp.selectedCount()).toBe(0);
  });

  it('askBulk opens only when the relevant subset is non-empty', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.reloadLines();
    flushLines(http, linePage([LINE], 1)); // unmatched only
    cmp.toggleSelect('l-1', true);
    cmp.askBulk('unlink'); // selectedMatched 0 → no-op
    expect(cmp.bulkConfirm()).toBeNull();
    cmp.askBulk('ignore'); // selectedIgnorable 1 → opens
    expect(cmp.bulkConfirm()).toBe('ignore');
  });

  it('runBulk unlink releases the matched lines, refreshes and toasts', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.reloadLines();
    flushLines(http, linePage([LINE_MATCHED], 1));
    cmp.toggleSelect('l-2', true);
    cmp.askBulk('unlink');
    cmp.runBulk();
    http
      .expectOne((r) => r.url.endsWith('/statement-lines/l-2/unlink') && r.method === 'POST')
      .flush({ ...LINE_MATCHED, matchState: 'unmatched' });
    flushLines(http, linePage([])); // afterBulk → refresh
    expect(cmp.bulkConfirm()).toBeNull();
    expect(cmp.bulkBusy()).toBe(false);
    expect(success).toHaveBeenCalledWith('1 Zuordnung(en) gelöst.');
    TestBed.tick(); // prune effect empties the stale selection
    expect(cmp.selectedCount()).toBe(0);
  });

  it('runBulk ignore covers unmatched and suggested lines', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const success = jest.spyOn(priv(cmp).toast, 'success');
    cmp.reloadLines();
    flushLines(http, linePage([LINE, LINE_SUGGESTED], 2));
    cmp.toggleSelectAll(true);
    cmp.askBulk('ignore');
    expect(cmp.bulkConfirm()).toBe('ignore');
    cmp.runBulk();
    http.expectOne((r) => r.url.endsWith('/statement-lines/l-1/ignore') && r.method === 'POST').flush(null);
    http.expectOne((r) => r.url.endsWith('/statement-lines/l-4/ignore') && r.method === 'POST').flush(null);
    flushLines(http, linePage([]));
    expect(success).toHaveBeenCalledWith('2 Umsatz/Umsätze ignoriert.');
    TestBed.tick();
    expect(cmp.selectedCount()).toBe(0);
  });

  it('runBulk is a no-op without a pending action, while busy or with no eligible line', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    cmp.reloadLines();
    flushLines(http, linePage([LINE], 1)); // unmatched
    cmp.runBulk(); // bulkConfirm null → nothing
    cmp.bulkConfirm.set('unlink');
    cmp.bulkBusy.set(true);
    cmp.runBulk(); // busy → nothing
    cmp.bulkBusy.set(false);
    cmp.toggleSelect('l-1', true);
    cmp.bulkConfirm.set('unlink'); // unmatched line → no matched-eligible row
    cmp.runBulk();
    expect(cmp.bulkConfirm()).toBeNull(); // eligible-empty branch resets the dialog
    http.expectNone((r) => r.url.endsWith('/unlink'));
  });

  it('afterBulk toasts an error and still refreshes on a failed bulk op', () => {
    const { cmp, http } = build({ accounts: [ACC] });
    const error = jest.spyOn(priv(cmp).toast, 'error');
    cmp.reloadLines();
    flushLines(http, linePage([LINE_MATCHED], 1));
    cmp.toggleSelect('l-2', true);
    cmp.askBulk('unlink');
    cmp.runBulk();
    http.expectOne((r) => r.url.endsWith('/statement-lines/l-2/unlink')).error(new ProgressEvent('err'));
    flushLines(http, linePage([])); // refresh still runs
    expect(cmp.bulkBusy()).toBe(false);
    expect(cmp.bulkConfirm()).toBeNull();
    expect(error).toHaveBeenCalledWith('Sammel-Aktion fehlgeschlagen.');
    TestBed.tick();
  });
});

// `KontenLinesState.refresh()` in isolation: the post-mutation window reload.
describe('KontenLinesState.refresh (#expenses-ux)', () => {
  afterEach(() => {
    try {
      TestBed.inject(HttpTestingController).verify();
    } catch {
      /* module already reset */
    }
  });

  function buildState(accounts: AccountOption[]): { state: KontenLinesState; http: HttpTestingController } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const state = TestBed.runInInjectionContext(() => new KontenLinesState());
    http.expectOne((r) => r.url.endsWith('/accounts/options')).flush(accounts);
    return { state, http };
  }

  it('is a no-op without a selected account', () => {
    const { state, http } = buildState([]);
    expect(state.accountId()).toBe('');
    state.refresh();
    http.expectNone((r) => r.url.endsWith('/statement-lines'));
  });

  it('early-returns a concurrent refresh and clears the flag on success', () => {
    const { state, http } = buildState([ACC]); // refreshAccounts selects a-1
    state.refresh();
    state.refresh(); // refreshing() already true → early return
    const reqs = http.match((r) => r.url.endsWith('/statement-lines') && r.method === 'GET');
    expect(reqs.length).toBe(1);
    reqs[0].flush(linePage([LINE], 1));
    expect(state.refreshing()).toBe(false);
    expect(state.lines()).toEqual([LINE]);
  });

  it('clears the refreshing flag on an error', () => {
    const { state, http } = buildState([ACC]);
    state.refresh();
    http
      .expectOne((r) => r.url.endsWith('/statement-lines') && r.method === 'GET')
      .error(new ProgressEvent('err'));
    expect(state.refreshing()).toBe(false);
  });
});
