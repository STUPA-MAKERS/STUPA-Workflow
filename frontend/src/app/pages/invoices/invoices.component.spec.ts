import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import * as downloadUtil from '@shared/download.util';
import { InvoicesComponent } from './invoices.component';
import type {
  Invoice,
  InvoiceFileResult,
  InvoicePage,
  InvoiceParseResult,
} from '../budget/budget-tree.api';

// ---------------------------------------------------------------- fixtures
function inv(over: Partial<Invoice> = {}): Invoice {
  return {
    id: 'i-1',
    number: 'R-001',
    issueDate: '2026-01-01',
    dueDate: '2026-01-31',
    supplier: 'ACME GmbH',
    netAmount: '100.00',
    taxAmount: '19.00',
    grossAmount: '119.00',
    currency: 'EUR',
    note: 'hello',
    status: 'open',
    fileName: 'beleg.pdf',
    hasFile: true,
    actor: null,
    createdAt: '2026-01-02T10:00:00Z',
    ...over,
  };
}

function page(items: Invoice[], total = items.length, offset = 0): InvoicePage {
  return { items, total, limit: 20, offset };
}

const PARSE: InvoiceParseResult = {
  number: 'R-777',
  issueDate: '2026-03-03',
  dueDate: '2026-04-03',
  supplier: 'Parsed Supplier',
  netAmount: '200.00',
  taxAmount: '38.00',
  grossAmount: '238.00',
  currency: 'EUR',
  fileToken: 'tok-parse',
  fileName: 'parsed.pdf',
  fileMime: 'application/pdf',
  duplicate: false,
};

const FILE_RES: InvoiceFileResult = {
  fileToken: 'tok-upload',
  fileName: 'manual.pdf',
  fileMime: 'application/pdf',
};

// Controllable fake auth — `canManage()` = can('budget.book').
class FakeAuth {
  allowed = true;
  can(_perm: string): boolean {
    return this.allowed;
  }
}

interface SetupOpts {
  /** initial GET /invoices payload (default: one invoice). */
  initial?: Invoice[];
  total?: number;
  /** fail the initial GET instead of flushing. */
  error?: boolean;
  canManage?: boolean;
}

async function setup(opts: SetupOpts = {}) {
  localStorage.setItem('ap.locale', 'de');
  const auth = new FakeAuth();
  auth.allowed = opts.canManage ?? true;

  const view = await render(InvoicesComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: auth },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const toast = TestBed.inject(ToastService);

  // Constructor calls reload() → GET /api/invoices.
  const req = http.expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
  if (opts.error) {
    req.flush(null, { status: 500, statusText: 'Server Error' });
  } else {
    const items = opts.initial ?? [inv()];
    req.flush(page(items, opts.total ?? items.length));
  }
  view.fixture.detectChanges();

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, http, toast, c, auth };
}

function lastInvoicesReq(http: HttpTestingController) {
  const reqs = http.match((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
  return reqs[reqs.length - 1];
}

describe('InvoicesComponent (#invoices)', () => {
  afterEach(() => {
    if (jest.isMockFunction(setTimeout)) jest.useRealTimers();
    const http = TestBed.inject(HttpTestingController);
    http.verify();
  });

  // ------------------------------------------------------------- loading
  it('loads the first page on init and clears loading flags', async () => {
    const { c } = await setup({ initial: [inv({ id: 'a' }), inv({ id: 'b' })], total: 5 });
    expect(c.items().length).toBe(2);
    expect(c.total()).toBe(5);
    expect(c.loading()).toBe(false);
    expect(c.loadingMore()).toBe(false);
    expect(c.hasMore()).toBe(true); // 2 < 5
  });

  it('clears items/total on an initial load error', async () => {
    const { c } = await setup({ error: true });
    expect(c.items()).toEqual([]);
    expect(c.total()).toBe(0);
    expect(c.loading()).toBe(false);
  });

  it('hasMore is false once everything is loaded', async () => {
    const { c } = await setup({ initial: [inv()], total: 1 });
    expect(c.hasMore()).toBe(false);
  });

  // ------------------------------------------------------------- formatting
  it('money() formats in de-DE vs en-US per locale', async () => {
    const { c } = await setup();
    const de = c.money('119.00');
    expect(de).toContain('119');
    expect(de).toContain('€'); // €
    localStorage.setItem('ap.locale', 'en');
    TestBed.inject(AuthService); // noop, keep ref
    const i18n = c.i18n;
    i18n.setLocale('en');
    const en = c.money('119.00');
    expect(en).toContain('119.00');
    expect(en).toContain('€');
  });

  it('statusLabel() maps both statuses', async () => {
    const { c } = await setup();
    expect(c.statusLabel('paid')).toBe('Bezahlt');
    expect(c.statusLabel('open')).toBe('Offen');
  });

  // ------------------------------------------------------------- search
  it('onSearch debounces and reloads with the q param', async () => {
    const { c, http } = await setup();
    jest.useFakeTimers();
    c.onSearch('acme');
    expect(c.q()).toBe('acme');
    // not yet fired
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
    jest.advanceTimersByTime(400);
    jest.useRealTimers();
    const req = lastInvoicesReq(http);
    expect(req.request.params.get('q')).toBe('acme');
    req.flush(page([inv()]));
  });

  it('debounce clears a pending timer when called twice quickly', async () => {
    const { c, http } = await setup();
    jest.useFakeTimers();
    c.onSearch('a');
    c.onSearch('ab'); // clears the previous timer
    jest.advanceTimersByTime(400);
    jest.useRealTimers();
    const reqs = http.match((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
    expect(reqs.length).toBe(1); // only one reload
    reqs[0].flush(page([inv()]));
  });

  it('blank search omits the q param', async () => {
    const { c, http } = await setup();
    jest.useFakeTimers();
    c.onSearch('   ');
    jest.advanceTimersByTime(400);
    jest.useRealTimers();
    const req = lastInvoicesReq(http);
    expect(req.request.params.has('q')).toBe(false);
    req.flush(page([]));
  });

  // ------------------------------------------------------------- filters
  it('setStatus filters immediately (no debounce)', async () => {
    const { c, http } = await setup();
    c.setStatus('paid');
    expect(c.statusFilter()).toBe('paid');
    const req = lastInvoicesReq(http);
    expect(req.request.params.get('status')).toBe('paid');
    req.flush(page([inv({ status: 'paid' })]));
  });

  it('onGrossFilter sets min and max and passes numeric params', async () => {
    const { c, http } = await setup();
    jest.useFakeTimers();
    c.onGrossFilter('min', '10');
    c.onGrossFilter('max', '50');
    expect(c.grossMin()).toBe('10');
    expect(c.grossMax()).toBe('50');
    jest.advanceTimersByTime(400);
    jest.useRealTimers();
    const req = lastInvoicesReq(http);
    expect(req.request.params.get('grossMin')).toBe('10');
    expect(req.request.params.get('grossMax')).toBe('50');
    req.flush(page([]));
  });

  it('onDateFilter sets each of the four date fields', async () => {
    const { c, http } = await setup();
    jest.useFakeTimers();
    c.onDateFilter('issueFrom', '2026-01-01');
    c.onDateFilter('issueTo', '2026-02-01');
    c.onDateFilter('dueFrom', '2026-03-01');
    c.onDateFilter('dueTo', '2026-04-01');
    expect(c.issueFrom()).toBe('2026-01-01');
    expect(c.issueTo()).toBe('2026-02-01');
    expect(c.dueFrom()).toBe('2026-03-01');
    expect(c.dueTo()).toBe('2026-04-01');
    jest.advanceTimersByTime(400);
    jest.useRealTimers();
    const req = lastInvoicesReq(http);
    expect(req.request.params.get('issueFrom')).toBe('2026-01-01');
    expect(req.request.params.get('issueTo')).toBe('2026-02-01');
    expect(req.request.params.get('dueFrom')).toBe('2026-03-01');
    expect(req.request.params.get('dueTo')).toBe('2026-04-01');
    req.flush(page([]));
  });

  it('activeFilterCount counts non-empty filters (search excluded)', async () => {
    const { c } = await setup();
    expect(c.activeFilterCount()).toBe(0);
    c.statusFilter.set('open');
    c.grossMin.set(' 5 ');
    c.grossMax.set('   '); // whitespace → not counted
    c.issueFrom.set('2026-01-01');
    expect(c.activeFilterCount()).toBe(3);
  });

  it('resetFilters clears every filter and reloads', async () => {
    const { c, http } = await setup();
    c.statusFilter.set('open');
    c.grossMin.set('1');
    c.grossMax.set('2');
    c.issueFrom.set('a');
    c.issueTo.set('b');
    c.dueFrom.set('x');
    c.dueTo.set('y');
    c.resetFilters();
    expect(c.activeFilterCount()).toBe(0);
    const req = lastInvoicesReq(http);
    expect(req.request.params.keys().length).toBe(2); // only limit + offset
    req.flush(page([]));
  });

  // ------------------------------------------------------------- loadMore
  it('loadMore appends the next page and advances the offset', async () => {
    const { c, http } = await setup({ initial: [inv({ id: 'a' })], total: 2 });
    c.loadMore();
    expect(c.loadingMore()).toBe(true);
    const req = lastInvoicesReq(http);
    expect(req.request.params.get('offset')).toBe('1');
    req.flush(page([inv({ id: 'b' })], 2, 1));
    expect(c.items().map((x: Invoice) => x.id)).toEqual(['a', 'b']);
    expect(c.loadingMore()).toBe(false);
  });

  it('loadMore is a no-op when already loadingMore', async () => {
    const { c, http } = await setup({ initial: [inv()], total: 5 });
    c.loadingMore.set(true);
    c.loadMore();
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
  });

  it('loadMore is a no-op while still loading', async () => {
    const { c, http } = await setup({ initial: [inv()], total: 5 });
    c.loading.set(true);
    c.loadMore();
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
    c.loading.set(false);
  });

  it('loadMore is a no-op when there is no more', async () => {
    const { c, http } = await setup({ initial: [inv()], total: 1 });
    c.loadMore();
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
  });

  it('loadMore error keeps existing items (non-initial branch)', async () => {
    const { c, http } = await setup({ initial: [inv({ id: 'a' })], total: 2 });
    c.loadMore();
    lastInvoicesReq(http).flush(null, { status: 500, statusText: 'err' });
    expect(c.items().map((x: Invoice) => x.id)).toEqual(['a']); // unchanged
    expect(c.loadingMore()).toBe(false);
  });

  // ------------------------------------------------------------- drag&drop
  function dragEvent(types: string[], file?: File): DragEvent {
    return {
      preventDefault: jest.fn(),
      dataTransfer: {
        types,
        files: file ? ([file] as unknown as FileList) : ([] as unknown as FileList),
      },
    } as unknown as DragEvent;
  }

  it('onDragEnter activates the overlay when files are dragged and user can manage', async () => {
    const { c } = await setup();
    const ev = dragEvent(['Files']);
    c.onDragEnter(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    expect(c.dragActive()).toBe(true);
  });

  it('onDragEnter ignores when user cannot manage', async () => {
    const { c } = await setup({ canManage: false });
    const ev = dragEvent(['Files']);
    c.onDragEnter(ev);
    expect(c.dragActive()).toBe(false);
    expect(ev.preventDefault).not.toHaveBeenCalled();
  });

  it('onDragEnter ignores when no files in the drag', async () => {
    const { c } = await setup();
    const ev = dragEvent(['text/plain']);
    c.onDragEnter(ev);
    expect(c.dragActive()).toBe(false);
  });

  it('hasFiles tolerates a missing dataTransfer (no types)', async () => {
    const { c } = await setup();
    // dataTransfer undefined → `?.types ?? []` → empty → no files
    const ev = { preventDefault: jest.fn(), dataTransfer: undefined } as unknown as DragEvent;
    c.onDragEnter(ev);
    expect(c.dragActive()).toBe(false);
    expect(ev.preventDefault).not.toHaveBeenCalled();
  });

  it('onDragOver preventDefault only for file drags by a manager', async () => {
    const { c } = await setup();
    const ok = dragEvent(['Files']);
    c.onDragOver(ok);
    expect(ok.preventDefault).toHaveBeenCalled();
    const noFiles = dragEvent([]);
    c.onDragOver(noFiles);
    expect(noFiles.preventDefault).not.toHaveBeenCalled();
  });

  it('onDragOver ignored without manage rights', async () => {
    const { c } = await setup({ canManage: false });
    const ev = dragEvent(['Files']);
    c.onDragOver(ev);
    expect(ev.preventDefault).not.toHaveBeenCalled();
  });

  it('onDragLeave decrements depth and deactivates at zero', async () => {
    const { c } = await setup();
    c.onDragEnter(dragEvent(['Files'])); // depth 1, active
    c.onDragEnter(dragEvent(['Files'])); // depth 2
    const leave1 = dragEvent(['Files']);
    c.onDragLeave(leave1); // depth 1, still active
    expect(c.dragActive()).toBe(true);
    const leave2 = dragEvent(['Files']);
    c.onDragLeave(leave2); // depth 0 → inactive
    expect(c.dragActive()).toBe(false);
  });

  it('onDragLeave is a no-op when not active', async () => {
    const { c } = await setup();
    const ev = dragEvent(['Files']);
    c.onDragLeave(ev);
    expect(ev.preventDefault).not.toHaveBeenCalled();
    expect(c.dragActive()).toBe(false);
  });

  it('onDrop ignored without manage rights', async () => {
    const { c, http } = await setup({ canManage: false });
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    const ev = dragEvent(['Files'], file);
    c.onDrop(ev);
    expect(ev.preventDefault).not.toHaveBeenCalled();
    http.expectNone((r) => r.url.includes('/invoices/parse'));
  });

  it('onDrop with a file triggers an import (parse)', async () => {
    const { c, http } = await setup();
    c.onDragEnter(dragEvent(['Files']));
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    const ev = dragEvent(['Files'], file);
    c.onDrop(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    expect(c.dragActive()).toBe(false);
    const req = http.expectOne((r) => r.url.endsWith('/api/invoices/parse'));
    expect(c.importing()).toBe(true);
    req.flush(PARSE);
    expect(c.importing()).toBe(false);
  });

  it('onDrop without a file just resets the overlay', async () => {
    const { c, http } = await setup();
    c.onDragEnter(dragEvent(['Files']));
    const ev = dragEvent(['Files']); // no file
    c.onDrop(ev);
    expect(c.dragActive()).toBe(false);
    http.expectNone((r) => r.url.includes('/invoices/parse'));
  });

  // ------------------------------------------------------------- import / parse
  it('successful parse prefills the create dialog + success toast', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'success');
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http.expectOne((r) => r.url.endsWith('/api/invoices/parse')).flush(PARSE);
    expect(c.createOpen()).toBe(true);
    expect(c.newNumber()).toBe('R-777');
    expect(c.newSupplier()).toBe('Parsed Supplier');
    expect(c.newGross()).toBe('238.00');
    expect(c.importToken()).toBe('tok-parse');
    expect(c.importFileName()).toBe('parsed.pdf');
    expect(spy).toHaveBeenCalled();
  });

  it('parse with null fields prefills empty strings', async () => {
    const { c, http } = await setup();
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http.expectOne((r) => r.url.endsWith('/api/invoices/parse')).flush({
      ...PARSE,
      number: null,
      issueDate: null,
      dueDate: null,
      supplier: null,
      netAmount: null,
      taxAmount: null,
    });
    expect(c.newNumber()).toBe('');
    expect(c.newSupplier()).toBe('');
    expect(c.newIssueDate()).toBe('');
    expect(c.newNet()).toBe('');
  });

  it('parse without a gross amount defaults it to empty', async () => {
    const { c, http } = await setup();
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    // grossAmount typed string but server may omit → `?? ''` defensive branch
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ ...PARSE, grossAmount: null });
    expect(c.newGross()).toBe('');
  });

  it('parse flagged as duplicate shows a warning toast', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'show');
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ ...PARSE, duplicate: true, number: 'DUP' });
    expect(spy).toHaveBeenCalledWith(expect.any(String), 'warning');
  });

  it('duplicate warning tolerates a null number', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'show');
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ ...PARSE, duplicate: true, number: null });
    expect(spy).toHaveBeenCalledWith(expect.any(String), 'warning');
  });

  it('not-zugferd parse error opens an empty dialog and attaches the file', async () => {
    const { c, http, toast } = await setup();
    const showSpy = jest.spyOn(toast, 'show');
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ code: 'invoice_not_zugferd' }, { status: 422, statusText: 'Unprocessable' });
    expect(c.createOpen()).toBe(true);
    // openCreate cleared the fields
    expect(c.newNumber()).toBe('');
    // attachFile fired upload
    const up = http.expectOne((r) => r.url.endsWith('/api/invoices/file'));
    up.flush(FILE_RES);
    expect(c.importToken()).toBe('tok-upload');
    expect(c.importFileName()).toBe('manual.pdf');
    expect(showSpy).toHaveBeenCalledWith(expect.any(String), 'info');
  });

  it('other parse errors surface a problem-detail error toast', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ detail: 'kaputt' }, { status: 500, statusText: 'err' });
    expect(spy).toHaveBeenCalledWith('kaputt');
    expect(c.importing()).toBe(false);
  });

  it('parse error without detail falls back to the generic message', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(spy).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  it('importFile is a no-op while a previous import is still running', async () => {
    const { c, http } = await setup();
    c.importing.set(true);
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http.expectNone((r) => r.url.includes('/invoices/parse'));
  });

  it('onFilePicked with no file does nothing but clears the input', async () => {
    const { c, http } = await setup();
    const input = { files: [], value: 'keep' } as unknown as { files: never[]; value: string };
    c.onFilePicked({ target: input } as unknown as Event);
    expect(input.value).toBe('');
    http.expectNone((r) => r.url.includes('/invoices/parse'));
  });

  // ------------------------------------------------------------- attach (create dialog)
  it('onCreateFilePicked uploads the chosen file', async () => {
    const { c, http } = await setup();
    const file = new File(['x'], 'm.pdf', { type: 'application/pdf' });
    const input = { files: [file], value: 'k' } as unknown as { files: File[]; value: string };
    c.onCreateFilePicked({ target: input } as unknown as Event);
    expect(input.value).toBe('');
    expect(c.attaching()).toBe(true);
    http.expectOne((r) => r.url.endsWith('/api/invoices/file')).flush(FILE_RES);
    expect(c.attaching()).toBe(false);
    expect(c.importToken()).toBe('tok-upload');
  });

  it('onCreateFilePicked without a file does nothing', async () => {
    const { c, http } = await setup();
    const input = { files: [], value: 'k' } as unknown as { files: never[]; value: string };
    c.onCreateFilePicked({ target: input } as unknown as Event);
    http.expectNone((r) => r.url.endsWith('/api/invoices/file'));
  });

  it('attachFile is a no-op while already attaching', async () => {
    const { c, http } = await setup();
    c.attaching.set(true);
    const file = new File(['x'], 'm.pdf', { type: 'application/pdf' });
    c.onCreateFilePicked({
      target: { files: [file], value: '' },
    } as unknown as Event);
    http.expectNone((r) => r.url.endsWith('/api/invoices/file'));
  });

  it('attachFile error toasts the problem detail', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    const file = new File(['x'], 'm.pdf', { type: 'application/pdf' });
    c.onCreateFilePicked({
      target: { files: [file], value: '' },
    } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/file'))
      .flush({ detail: 'upload failed' }, { status: 500, statusText: 'err' });
    expect(spy).toHaveBeenCalledWith('upload failed');
    expect(c.attaching()).toBe(false);
  });

  it('clearAttachment resets the file handle signals', async () => {
    const { c } = await setup();
    c.importToken.set('tok');
    c.importFileName.set('f.pdf');
    c.clearAttachment();
    expect(c.importToken()).toBe('');
    expect(c.importFileName()).toBe('');
  });

  // ------------------------------------------------------------- create
  it('openCreate resets every dialog field and opens it', async () => {
    const { c } = await setup();
    c.newNumber.set('x');
    c.importToken.set('y');
    c.openCreate();
    expect(c.createOpen()).toBe(true);
    expect(c.newNumber()).toBe('');
    expect(c.newStatus()).toBe('open');
    expect(c.importToken()).toBe('');
  });

  it('canSubmitCreate requires a positive gross amount', async () => {
    const { c } = await setup();
    expect(c.canSubmitCreate()).toBe(false);
    c.newGross.set('0');
    expect(c.canSubmitCreate()).toBe(false);
    c.newGross.set('12.50');
    expect(c.canSubmitCreate()).toBe(true);
  });

  it('create() submits trimmed fields, includes the file handle, toasts and reloads', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'success');
    c.openCreate();
    c.newNumber.set('  R-9 ');
    c.newSupplier.set(' Sup ');
    c.newIssueDate.set('2026-05-01');
    c.newNet.set(' 10 ');
    c.newTax.set(' 2 ');
    c.newGross.set('12');
    c.newNote.set('  note ');
    c.importToken.set('tok-9');
    c.importFileName.set('f.pdf');

    const ev = { preventDefault: jest.fn() } as unknown as Event;
    c.create(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    expect(c.saving()).toBe(true);

    const req = http.expectOne(
      (r) => r.url.endsWith('/api/invoices') && r.method === 'POST',
    );
    expect(req.request.body).toMatchObject({
      number: 'R-9',
      supplier: 'Sup',
      issueDate: '2026-05-01',
      netAmount: '10',
      taxAmount: '2',
      grossAmount: '12',
      note: 'note',
      fileToken: 'tok-9',
      fileName: 'f.pdf',
      fileMime: null,
    });
    req.flush(inv({ id: 'new' }));
    expect(c.saving()).toBe(false);
    expect(c.createOpen()).toBe(false);
    expect(spy).toHaveBeenCalled();
    // reload() fired a fresh GET
    lastInvoicesReq(http).flush(page([inv({ id: 'new' })]));
  });

  it('create() sends nulls for blank optional fields and no file handle', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newGross.set('5');
    // everything else blank, no importToken
    const ev = { preventDefault: jest.fn() } as unknown as Event;
    c.create(ev);
    const req = http.expectOne(
      (r) => r.url.endsWith('/api/invoices') && r.method === 'POST',
    );
    expect(req.request.body).toMatchObject({
      number: null,
      supplier: null,
      issueDate: null,
      dueDate: null,
      netAmount: null,
      taxAmount: null,
      grossAmount: '5',
      note: null,
      fileToken: null,
      fileName: null,
      fileMime: null,
    });
    req.flush(inv());
    lastInvoicesReq(http).flush(page([inv()]));
  });

  it('create() with a file handle but no mime sends fileMime null', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newGross.set('5');
    c.importToken.set('tok');
    c.importFileName.set('f.pdf');
    // importFileMime stays '' → fileMime: null branch
    const ev = { preventDefault: jest.fn() } as unknown as Event;
    c.create(ev);
    const req = http.expectOne(
      (r) => r.url.endsWith('/api/invoices') && r.method === 'POST',
    );
    expect(req.request.body.fileName).toBe('f.pdf');
    expect(req.request.body.fileMime).toBe(null);
    req.flush(inv());
    lastInvoicesReq(http).flush(page([inv()]));
  });

  it('create() is a no-op when gross is not positive', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newGross.set('0');
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
  });

  it('create() is a no-op while already saving', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newGross.set('5');
    c.saving.set(true);
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
  });

  it('create() error toasts the problem detail and keeps the dialog open', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    c.openCreate();
    c.newGross.set('5');
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'POST')
      .flush({ detail: 'nope' }, { status: 400, statusText: 'Bad' });
    expect(spy).toHaveBeenCalledWith('nope');
    expect(c.saving()).toBe(false);
    expect(c.createOpen()).toBe(true);
  });

  // ------------------------------------------------------------- edit
  it('openEdit loads the invoice into the edit signals (with nulls → empty)', async () => {
    const { c } = await setup();
    const target = inv({
      id: 'e1',
      number: null,
      supplier: null,
      issueDate: null,
      dueDate: null,
      netAmount: null,
      taxAmount: null,
      note: null,
      status: 'paid',
      grossAmount: '99',
    });
    c.openEdit(target);
    expect(c.editing()).toBe(target);
    expect(c.editNumber()).toBe('');
    expect(c.editSupplier()).toBe('');
    expect(c.editGross()).toBe('99');
    expect(c.editStatus()).toBe('paid');
    expect(c.editGrossValid()).toBe(true);
  });

  it('editGrossValid is false for a non-positive gross', async () => {
    const { c } = await setup();
    c.openEdit(inv({ grossAmount: '0' }));
    expect(c.editGrossValid()).toBe(false);
  });

  it('saveEdit patches the invoice and replaces it in the list', async () => {
    const { c, http, toast } = await setup({ initial: [inv({ id: 'e1', supplier: 'old' })] });
    const spy = jest.spyOn(toast, 'success');
    c.openEdit(c.items()[0]);
    c.editSupplier.set('  New Sup  ');
    c.editNote.set('   ');
    const ev = { preventDefault: jest.fn() } as unknown as Event;
    c.saveEdit(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    const req = http.expectOne(
      (r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH',
    );
    expect(req.request.body.supplier).toBe('New Sup');
    expect(req.request.body.note).toBe(null);
    req.flush(inv({ id: 'e1', supplier: 'New Sup' }));
    expect(c.editing()).toBe(null);
    expect(c.items()[0].supplier).toBe('New Sup');
    expect(spy).toHaveBeenCalled();
  });

  it('saveEdit leaves untouched list entries alone', async () => {
    const { c, http } = await setup({
      initial: [inv({ id: 'e1' }), inv({ id: 'e2', supplier: 'keep' })],
    });
    c.openEdit(c.items()[0]);
    c.editGross.set('50');
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH')
      .flush(inv({ id: 'e1', supplier: 'changed' }));
    expect(c.items().find((x: Invoice) => x.id === 'e2').supplier).toBe('keep');
  });

  it('saveEdit sends nulls for every blank optional field', async () => {
    const { c, http } = await setup({
      initial: [
        inv({
          id: 'e1',
          number: null,
          supplier: null,
          issueDate: null,
          dueDate: null,
          netAmount: null,
          taxAmount: null,
          note: null,
          grossAmount: '40',
        }),
      ],
    });
    c.openEdit(c.items()[0]);
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    const req = http.expectOne(
      (r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH',
    );
    expect(req.request.body).toMatchObject({
      number: null,
      supplier: null,
      issueDate: null,
      dueDate: null,
      netAmount: null,
      taxAmount: null,
      grossAmount: '40',
      note: null,
    });
    req.flush(inv({ id: 'e1' }));
  });

  it('saveEdit is a no-op without an editing target', async () => {
    const { c, http } = await setup();
    c.editing.set(null);
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.method === 'PATCH');
  });

  it('saveEdit is a no-op when gross is invalid', async () => {
    const { c, http } = await setup();
    c.openEdit(inv({ id: 'e1' }));
    c.editGross.set('0');
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.method === 'PATCH');
  });

  it('saveEdit is a no-op while saving', async () => {
    const { c, http } = await setup();
    c.openEdit(inv({ id: 'e1' }));
    c.saving.set(true);
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.method === 'PATCH');
  });

  it('saveEdit error toasts the problem detail and keeps editing open', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    c.openEdit(inv({ id: 'e1' }));
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH')
      .flush(null, { status: 500, statusText: 'err' });
    expect(spy).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
    expect(c.editing()).not.toBe(null);
    expect(c.saving()).toBe(false);
  });

  // ------------------------------------------------------------- delete
  it('askDelete sets the confirm target', async () => {
    const { c } = await setup();
    const target = inv({ id: 'd1' });
    c.askDelete(target);
    expect(c.confirmDelete()).toBe(target);
  });

  it('doDelete removes the row, decrements the total and toasts', async () => {
    const { c, http, toast } = await setup({
      initial: [inv({ id: 'd1' }), inv({ id: 'd2' })],
      total: 2,
    });
    const spy = jest.spyOn(toast, 'success');
    c.askDelete(c.items()[0]);
    c.doDelete();
    expect(c.saving()).toBe(true);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/d1') && r.method === 'DELETE')
      .flush(null);
    expect(c.confirmDelete()).toBe(null);
    expect(c.items().map((x: Invoice) => x.id)).toEqual(['d2']);
    expect(c.total()).toBe(1);
    expect(spy).toHaveBeenCalled();
  });

  it('doDelete clamps the total at zero', async () => {
    const { c, http } = await setup({ initial: [inv({ id: 'd1' })], total: 0 });
    c.askDelete(c.items()[0]);
    c.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/d1') && r.method === 'DELETE')
      .flush(null);
    expect(c.total()).toBe(0);
  });

  it('doDelete is a no-op without a confirm target', async () => {
    const { c, http } = await setup();
    c.confirmDelete.set(null);
    c.doDelete();
    http.expectNone((r) => r.method === 'DELETE');
  });

  it('doDelete is a no-op while saving', async () => {
    const { c, http } = await setup();
    c.askDelete(inv({ id: 'd1' }));
    c.saving.set(true);
    c.doDelete();
    http.expectNone((r) => r.method === 'DELETE');
  });

  it('doDelete error toasts the generic failure', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    c.askDelete(inv({ id: 'd1' }));
    c.doDelete();
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/d1') && r.method === 'DELETE')
      .flush(null, { status: 500, statusText: 'err' });
    expect(spy).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
    expect(c.saving()).toBe(false);
  });

  // ------------------------------------------------------------- openFile
  it('openFile downloads the streamed blob with the invoice file name', async () => {
    const { c, http } = await setup();
    const dl = jest.spyOn(downloadUtil, 'downloadBlob').mockImplementation(() => undefined);
    c.openFile(inv({ id: 'f1', fileName: 'rechnung.pdf' }));
    const blob = new Blob(['pdf']);
    http.expectOne((r) => r.url.endsWith('/api/invoices/f1/file')).flush(blob);
    expect(dl).toHaveBeenCalledWith(expect.any(Blob), 'rechnung.pdf');
    dl.mockRestore();
  });

  it('openFile falls back to beleg.pdf when no file name', async () => {
    const { c, http } = await setup();
    const dl = jest.spyOn(downloadUtil, 'downloadBlob').mockImplementation(() => undefined);
    c.openFile(inv({ id: 'f1', fileName: null }));
    http.expectOne((r) => r.url.endsWith('/api/invoices/f1/file')).flush(new Blob(['x']));
    expect(dl).toHaveBeenCalledWith(expect.any(Blob), 'beleg.pdf');
    dl.mockRestore();
  });

  it('openFile error toasts the generic failure', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    c.openFile(inv({ id: 'f1' }));
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/f1/file'))
      .flush(null, { status: 500, statusText: 'err' });
    expect(spy).toHaveBeenCalledWith('Aktion fehlgeschlagen.');
  });

  // ------------------------------------------------------------- options
  it('statusOptions builds localized select options', async () => {
    const { c } = await setup();
    const opts = c.statusOptions();
    expect(opts).toEqual([
      { value: 'open', label: 'Offen' },
      { value: 'paid', label: 'Bezahlt' },
    ]);
  });
});

// ----------------------------------------------------------- IntersectionObserver
describe('InvoicesComponent infinite-scroll effect', () => {
  class FakeAuth2 {
    can(): boolean {
      return true;
    }
  }

  // Capture the observer so we can drive its callback manually.
  let lastCb: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
  let disconnected = false;

  beforeEach(() => {
    lastCb = null;
    disconnected = false;
    // @ts-expect-error test shim
    global.IntersectionObserver = class {
      constructor(cb: (e: { isIntersecting: boolean }[]) => void) {
        lastCb = cb;
      }
      observe(): void {
        /* noop */
      }
      disconnect(): void {
        disconnected = true;
      }
    };
  });

  afterEach(() => {
    // @ts-expect-error remove shim
    delete global.IntersectionObserver;
    TestBed.inject(HttpTestingController).verify();
  });

  it('observes the sentinel and calls loadMore when it intersects', async () => {
    const view = await render(InvoicesComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: new FakeAuth2() },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    // initial load → still has more (1 of 2)
    http
      .expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'GET')
      .flush(page([inv({ id: 'a' })], 2));
    view.fixture.detectChanges();

    expect(lastCb).not.toBeNull();
    // entries not intersecting → no load
    lastCb?.([{ isIntersecting: false }]);
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');

    // intersecting → loadMore fires the next page
    lastCb?.([{ isIntersecting: true }]);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'GET')
      .flush(page([inv({ id: 'b' })], 2, 1));

    // teardown disconnects the observer
    view.fixture.destroy();
    expect(disconnected).toBe(true);
  });
});
