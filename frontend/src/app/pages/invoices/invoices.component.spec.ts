import { BehaviorSubject, of } from 'rxjs';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import * as downloadUtil from '@shared/download.util';
import { InvoicesComponent } from './invoices.component';
import type {
  Invoice,
  InvoiceBooking,
  InvoiceFileResult,
  InvoicePage,
  InvoiceParseResult,
} from '../budget/budget-tree.api';

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

// Fake auth with a switch. The component maps `canManage()` to can('budget.book').
class FakeAuth {
  allowed = true;
  can(_perm: string): boolean {
    return this.allowed;
  }
}

interface SetupOpts {
  /** Payload of the initial GET /invoices. It defaults to one invoice. */
  initial?: Invoice[];
  total?: number;
  /** Fail the initial GET instead of flushing it. */
  error?: boolean;
  canManage?: boolean;
  /** Query params on the page URL, as a global-search hit or a bookmark carries them. */
  queryParams?: Record<string, string>;
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
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { queryParamMap: convertToParamMap(opts.queryParams ?? {}) },
          queryParamMap: of(convertToParamMap(opts.queryParams ?? {})),
        },
      },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  const toast = TestBed.inject(ToastService);

  // The constructor calls reload, which fires GET /api/invoices.
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

describe('InvoicesComponent', () => {
  afterEach(() => {
    if (jest.isMockFunction(setTimeout)) jest.useRealTimers();
    const http = TestBed.inject(HttpTestingController);
    http.verify();
  });

  it('loads the first page on init and clears loading flags', async () => {
    const { c } = await setup({ initial: [inv({ id: 'a' }), inv({ id: 'b' })], total: 5 });
    expect(c.items().length).toBe(2);
    expect(c.total()).toBe(5);
    expect(c.loading()).toBe(false);
    expect(c.loadingMore()).toBe(false);
    expect(c.hasMore()).toBe(true);
  });

  it('opens the invoice the URL names and loads it when the list does not hold it', async () => {
    // Where a global-search hit lands: the list stays whole, the invoice opens beside it.
    const { c, http, fixture } = await setup({ queryParams: { id: 'i-42' } });
    expect(c.selectedId()).toBe('i-42');
    expect(c.activeFilterCount()).toBe(0);
    fixture.detectChanges();
    http.expectOne((r) => r.url.endsWith('/api/invoices/i-42')).flush(inv({ id: 'i-42' }));
    fixture.detectChanges();
    expect(c.selectedInvoice()?.id).toBe('i-42');
    expect(c.detailView()).toBe('invoice');
    expect(c.detailOpen()).toBe(true);
  });

  it('says that the invoice of the URL is not there', async () => {
    const { c, http, fixture } = await setup({ queryParams: { id: 'gone' } });
    fixture.detectChanges();
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/gone'))
      .flush(null, { status: 404, statusText: 'x' });
    expect(c.selectedMissing()).toBe(true);
    expect(c.detailView()).toBe('missing');
  });

  it('opens another invoice when the palette sends it here, without a new list', async () => {
    localStorage.setItem('ap.locale', 'de');
    const params = new BehaviorSubject(convertToParamMap({ id: 'i-1' }));
    const view = await render(InvoicesComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: new FakeAuth() },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: params.value }, queryParamMap: params },
        },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url.endsWith('/api/invoices')).flush(page([inv({ id: 'i-1' }), inv({ id: 'i-9' })], 2));
    view.fixture.detectChanges();
    params.next(convertToParamMap({ id: 'i-9' }));
    view.fixture.detectChanges();
    http.expectNone((r) => r.url.endsWith('/api/invoices'));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((view.fixture.componentInstance as any).selectedInvoice()?.id).toBe('i-9');
    // A filter of the URL reloads the list; one that goes away clears.
    params.next(convertToParamMap({ id: 'i-9', seg: 'paid', q: 'acme' }));
    const again = http.expectOne((r) => r.url.endsWith('/api/invoices'));
    expect(again.request.params.get('status')).toBe('paid');
    expect(again.request.params.get('q')).toBe('acme');
    again.flush(page([inv({ id: 'i-9', status: 'paid' })], 1));
    params.next(convertToParamMap({}));
    const cleared = http.expectOne((r) => r.url.endsWith('/api/invoices'));
    expect(cleared.request.params.has('status')).toBe(false);
    cleared.flush(page([], 0));
    http.verify();
  });

  it('writes the segment and the filters back into the URL', async () => {
    const { c, http, fixture } = await setup();
    const navigate = jest.spyOn(TestBed.inject(Router), 'navigate');
    c.setSegment('inbox');
    fixture.detectChanges();
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: expect.objectContaining({ seg: 'inbox', q: null }),
        replaceUrl: true,
      }),
    );
    http.expectOne((r) => r.url.endsWith('/api/invoices')).flush(page([], 0));
    // The same segment again sends nothing; an unknown one is "all".
    c.setSegment('inbox');
    c.setSegment('nonsense');
    expect(c.segment()).toBe('all');
    http.expectOne((r) => r.url.endsWith('/api/invoices')).flush(page([], 0));
  });

  it('adopts every filter and the segment the URL carries', async () => {
    const { c } = await setup({ queryParams: { grossMin: '10', seg: 'booked' } });
    expect(c.grossMin()).toBe('10');
    expect(c.segment()).toBe('booked');
  });

  it('refuses a value the chips could never produce', async () => {
    const { c } = await setup({ queryParams: { grossMin: 'abc', seg: 'nonsense' } });
    expect(c.grossMin()).toBe('');
    expect(c.segment()).toBe('all');
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

  // These two hold what the shared table brings: the header and the skeleton stay
  // through a filter, a search or a reload, and the pinned actions column survives one.
  it('money() formats in de-DE vs en-GB per locale', async () => {
    const { c } = await setup();
    const de = c.money('119.00');
    expect(de).toContain('119');
    expect(de).toContain('€');
    localStorage.setItem('ap.locale', 'en');
    TestBed.inject(AuthService); // This no-op call keeps the auth reference alive.
    const i18n = c.i18n;
    i18n.setLocale('en');
    const en = c.money('119.00');
    expect(en).toContain('119.00');
    expect(en).toContain('€');
  });

  it('shows the status as coloured text', async () => {
    const { container } = await setup({ initial: [inv({ status: 'paid' })] });
    const status = container.querySelector('app-status-text');
    expect(status?.textContent?.trim()).toBe('Bezahlt');
  });

  it('onSearch debounces and reloads with the q param', async () => {
    const { c, http } = await setup();
    jest.useFakeTimers();
    c.onSearch('acme');
    expect(c.q()).toBe('acme');
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
    c.onSearch('ab');
    jest.advanceTimersByTime(400);
    jest.useRealTimers();
    const reqs = http.match((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');
    expect(reqs.length).toBe(1);
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

  it('asks each segment with its status and booked filter, and keeps the counts', async () => {
    const { c, http } = await setup();
    const cases: [string, Record<string, string | null>][] = [
      ['inbox', { status: 'open', booked: 'false' }],
      ['booked', { status: 'open', booked: 'true' }],
      ['paid', { status: 'paid', booked: null }],
      ['all', { status: null, booked: null }],
    ];
    for (const [seg, want] of cases) {
      c.setSegment(seg);
      const req = lastInvoicesReq(http);
      expect(req.request.params.get('status')).toBe(want['status']);
      expect(req.request.params.get('booked')).toBe(want['booked']);
      req.flush({ ...page([]), counts: { all: 9, inbox: 2, booked: 3, paid: 4 } });
    }
    expect(c.counts()).toEqual({ all: 9, inbox: 2, booked: 3, paid: 4 });
    expect(c.segmentOptions().map((o: { label: string; count: number }) => `${o.label} ${o.count}`)).toEqual([
      'Alle 9',
      'Eingang 2',
      'Verbucht 3',
      'Bezahlt 4',
    ]);
  });

  it('shows no counts from a backend without them', async () => {
    const { c } = await setup();
    expect(c.counts()).toBeNull();
    expect(c.segmentOptions()[0].count).toBeNull();
  });

  it('applies the amount and the two date chips at once', async () => {
    const { c, http } = await setup();
    c.onGrossRange({ from: '10', to: '50' });
    let req = lastInvoicesReq(http);
    expect(req.request.params.get('grossMin')).toBe('10');
    expect(req.request.params.get('grossMax')).toBe('50');
    req.flush(page([]));
    c.onIssueRange({ from: '2026-01-01', to: '2026-02-01' });
    req = lastInvoicesReq(http);
    expect(req.request.params.get('issueFrom')).toBe('2026-01-01');
    expect(req.request.params.get('issueTo')).toBe('2026-02-01');
    req.flush(page([]));
    c.onDueRange({ from: '2026-03-01', to: '2026-04-01' });
    req = lastInvoicesReq(http);
    expect(req.request.params.get('dueFrom')).toBe('2026-03-01');
    expect(req.request.params.get('dueTo')).toBe('2026-04-01');
    req.flush(page([]));
  });

  it('activeFilterCount counts non-empty filters and the search', async () => {
    const { c } = await setup();
    expect(c.activeFilterCount()).toBe(0);
    c.q.set('acme');
    c.grossMin.set(' 5 ');
    c.grossMax.set('   '); // Whitespace does not count as an active filter.
    c.issueFrom.set('2026-01-01');
    expect(c.activeFilterCount()).toBe(3);
  });

  it('resetFilters clears every filter and reloads', async () => {
    const { c, http } = await setup();
    c.q.set('acme');
    c.grossMin.set('1');
    c.grossMax.set('2');
    c.issueFrom.set('a');
    c.issueTo.set('b');
    c.dueFrom.set('x');
    c.dueTo.set('y');
    c.resetFilters();
    expect(c.activeFilterCount()).toBe(0);
    const req = lastInvoicesReq(http);
    expect(req.request.params.keys().length).toBe(2); // Only limit and offset remain.
    req.flush(page([]));
  });

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
    expect(c.items().map((x: Invoice) => x.id)).toEqual(['a']);
    expect(c.loadingMore()).toBe(false);
  });

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
    // dataTransfer is undefined. So `?.types ?? []` stays empty and reports no files.
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
    c.onDragEnter(dragEvent(['Files'])); // Depth 1, active.
    c.onDragEnter(dragEvent(['Files'])); // Depth 2.
    const leave1 = dragEvent(['Files']);
    c.onDragLeave(leave1); // Depth 1, still active.
    expect(c.dragActive()).toBe(true);
    const leave2 = dragEvent(['Files']);
    c.onDragLeave(leave2); // Depth 0, now inactive.
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
    const ev = dragEvent(['Files']); // No file.
    c.onDrop(ev);
    expect(c.dragActive()).toBe(false);
    http.expectNone((r) => r.url.includes('/invoices/parse'));
  });

  it('successful parse prefills the review dialog and says so in it, not in a toast', async () => {
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
    expect(c.importNotice()).toBe('parsed');
    expect(c.importDuplicate()).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });

  it('parse with null fields prefills empty strings', async () => {
    const { c, http } = await setup();
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({
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
    // The type of grossAmount is string, but the server can omit it. This covers the
    // fallback `?? ''` branch.
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ ...PARSE, grossAmount: null });
    expect(c.newGross()).toBe('');
  });

  it('parse flagged as duplicate shows the warning in the review dialog (N31)', async () => {
    const { c, http, fixture } = await setup();
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ ...PARSE, duplicate: true, number: 'DUP' });
    fixture.detectChanges();
    expect(c.importDuplicate()).toBe('DUP');
    const dialog = within(screen.getByRole('form', { name: 'Importierte Rechnung prüfen' }));
    expect(dialog.getByText('Rechnung gelesen — bitte prüfen.')).toBeInTheDocument();
    expect(dialog.getByText(/Mögliche Dublette: Rechnung „DUP“/)).toBeInTheDocument();
    expect(dialog.getByText('parsed.pdf')).toBeInTheDocument();
  });

  it('duplicate warning tolerates a null number', async () => {
    const { c, http } = await setup();
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ ...PARSE, duplicate: true, number: null });
    expect(c.importDuplicate()).toBe('');
  });

  it('a manual add clears the notes of an earlier import', async () => {
    const { c, http } = await setup();
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ ...PARSE, duplicate: true });
    c.createOpen.set(false);
    c.openCreate();
    expect(c.importNotice()).toBeNull();
    expect(c.importDuplicate()).toBeNull();
  });

  it('not-zugferd parse error opens an empty dialog and attaches the file', async () => {
    const { c, http } = await setup();
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/parse'))
      .flush({ code: 'invoice_not_zugferd' }, { status: 422, statusText: 'Unprocessable' });
    expect(c.createOpen()).toBe(true);
    // The openCreate call cleared the fields.
    expect(c.newNumber()).toBe('');
    // The attachFile call started the upload.
    const up = http.expectOne((r) => r.url.endsWith('/api/invoices/file'));
    up.flush(FILE_RES);
    expect(c.importToken()).toBe('tok-upload');
    expect(c.importFileName()).toBe('manual.pdf');
    // The dialog says why the fields are empty.
    expect(c.importNotice()).toBe('manual');
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

  it('canSubmitCreate requires a number, a supplier and a positive gross amount', async () => {
    const { c } = await setup();
    expect(c.canSubmitCreate()).toBe(false);
    c.newNumber.set('R-1');
    c.newSupplier.set('Sup');
    c.newGross.set('0');
    expect(c.canSubmitCreate()).toBe(false);
    c.newGross.set('12.50');
    expect(c.canSubmitCreate()).toBe(true);
    c.newNumber.set('   ');
    expect(c.canSubmitCreate()).toBe(false);
    c.newNumber.set('R-1');
    c.newSupplier.set('');
    expect(c.canSubmitCreate()).toBe(false);
  });

  it('create() is a no-op without a number or a supplier (manual entry)', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newGross.set('5');
    c.newSupplier.set('Sup');
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    c.newNumber.set('R-1');
    c.newSupplier.set(' ');
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
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

    const req = http.expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
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
    // The reload fired a fresh GET.
    lastInvoicesReq(http).flush(page([inv({ id: 'new' })]));
  });

  it('create() sends nulls for blank optional fields and no file handle', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newNumber.set('R-1');
    c.newSupplier.set('Sup');
    c.newGross.set('5');
    // Every optional field stays blank and there is no importToken.
    const ev = { preventDefault: jest.fn() } as unknown as Event;
    c.create(ev);
    const req = http.expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
    expect(req.request.body).toMatchObject({
      number: 'R-1',
      supplier: 'Sup',
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
    c.newNumber.set('R-1');
    c.newSupplier.set('Sup');
    c.newGross.set('5');
    c.importToken.set('tok');
    c.importFileName.set('f.pdf');
    // The importFileMime value stays empty here. This covers the fileMime null branch.
    const ev = { preventDefault: jest.fn() } as unknown as Event;
    c.create(ev);
    const req = http.expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
    expect(req.request.body.fileName).toBe('f.pdf');
    expect(req.request.body.fileMime).toBe(null);
    req.flush(inv());
    lastInvoicesReq(http).flush(page([inv()]));
  });

  it('create() is a no-op when gross is not positive', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newNumber.set('R-1');
    c.newSupplier.set('Sup');
    c.newGross.set('0');
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
  });

  it('create() is a no-op while already saving', async () => {
    const { c, http } = await setup();
    c.openCreate();
    c.newNumber.set('R-1');
    c.newSupplier.set('Sup');
    c.newGross.set('5');
    c.saving.set(true);
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'POST');
  });

  it('create() error toasts the problem detail and keeps the dialog open', async () => {
    const { c, http, toast } = await setup();
    const spy = jest.spyOn(toast, 'error');
    c.openCreate();
    c.newNumber.set('R-1');
    c.newSupplier.set('Sup');
    c.newGross.set('5');
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'POST')
      .flush({ detail: 'nope' }, { status: 400, statusText: 'Bad' });
    expect(spy).toHaveBeenCalledWith('nope');
    expect(c.saving()).toBe(false);
    expect(c.createOpen()).toBe(true);
  });

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
    // A stored invoice without number and supplier saves without them.
    expect(c.editNumberRequired()).toBe(false);
    expect(c.editSupplierRequired()).toBe(false);
    expect(c.canSubmitEdit()).toBe(true);
  });

  it('canSubmitEdit keeps a stored number and supplier from becoming empty', async () => {
    const { c } = await setup();
    c.openEdit(inv({ id: 'e1' }));
    expect(c.editNumberRequired()).toBe(true);
    expect(c.editSupplierRequired()).toBe(true);
    c.editNumber.set('  ');
    expect(c.canSubmitEdit()).toBe(false);
    c.editNumber.set('R-9');
    c.editSupplier.set('');
    expect(c.canSubmitEdit()).toBe(false);
  });

  it('saveEdit marks an invoice without number and supplier as paid', async () => {
    const { c, http } = await setup({
      initial: [inv({ id: 'e1', number: null, supplier: null, status: 'open', grossAmount: '40' })],
    });
    c.openEdit(c.items()[0]);
    c.editStatus.set('paid');
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    const req = http.expectOne((r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH');
    expect(req.request.body).toMatchObject({ number: null, supplier: null, status: 'paid' });
    req.flush(inv({ id: 'e1', number: null, supplier: null, status: 'paid' }));
    expect(c.editing()).toBe(null);
    expect(c.items()[0].status).toBe('paid');
    // The status moves the invoice to another segment: the list loads again.
    lastInvoicesReq(http).flush(page([]));
  });

  it('canSubmitEdit is false for a non-positive gross', async () => {
    const { c } = await setup();
    c.openEdit(inv({ grossAmount: '0' }));
    expect(c.canSubmitEdit()).toBe(false);
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
    const req = http.expectOne((r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH');
    expect(req.request.body.supplier).toBe('New Sup');
    expect(req.request.body.note).toBe(null);
    req.flush(inv({ id: 'e1', supplier: 'New Sup' }));
    expect(c.editing()).toBe(null);
    expect(c.items()[0].supplier).toBe('New Sup');
    expect(spy).toHaveBeenCalled();
  });

  it('saveEdit keeps the line breaks of a note', async () => {
    const { c, http } = await setup({ initial: [inv({ id: 'e1', note: 'Teil 1\nTeil 2' })] });
    c.openEdit(c.items()[0]);
    expect(c.editNote()).toBe('Teil 1\nTeil 2');
    c.editNote.set('Teil 1\nTeil 2\nTeil 3\n');
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    const req = http.expectOne((r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH');
    expect(req.request.body.note).toBe('Teil 1\nTeil 2\nTeil 3');
    req.flush(inv({ id: 'e1', note: 'Teil 1\nTeil 2\nTeil 3' }));
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
    c.editNumber.set(' R-1 ');
    c.editSupplier.set('Sup');
    c.saveEdit({ preventDefault: jest.fn() } as unknown as Event);
    const req = http.expectOne((r) => r.url.endsWith('/api/invoices/e1') && r.method === 'PATCH');
    expect(req.request.body).toMatchObject({
      number: 'R-1',
      supplier: 'Sup',
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

  it('saveEdit is a no-op without a supplier', async () => {
    const { c, http } = await setup();
    c.openEdit(inv({ id: 'e1' }));
    c.editSupplier.set('  ');
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
    http.expectOne((r) => r.url.endsWith('/api/invoices/d1') && r.method === 'DELETE').flush(null);
    expect(c.confirmDelete()).toBe(null);
    expect(c.items().map((x: Invoice) => x.id)).toEqual(['d2']);
    expect(c.total()).toBe(1);
    expect(spy).toHaveBeenCalled();
    // The counts of the segments change: the list loads again.
    lastInvoicesReq(http).flush(page([inv({ id: 'd2' })], 1));
  });

  it('doDelete clamps the total at zero', async () => {
    const { c, http } = await setup({ initial: [inv({ id: 'd1' })], total: 0 });
    c.askDelete(c.items()[0]);
    c.doDelete();
    http.expectOne((r) => r.url.endsWith('/api/invoices/d1') && r.method === 'DELETE').flush(null);
    expect(c.total()).toBe(0);
    lastInvoicesReq(http).flush(page([]));
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

  it('statusOptions builds localized select options', async () => {
    const { c } = await setup();
    const opts = c.statusOptions();
    expect(opts).toEqual([
      { value: 'open', label: 'Offen' },
      { value: 'paid', label: 'Bezahlt' },
    ]);
  });
});

describe('InvoicesComponent infinite-scroll effect', () => {
  class FakeAuth2 {
    can(): boolean {
      return true;
    }
  }

  // Capture the observer to drive its callback manually.
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
      observe(): void {}
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
    // The initial load returns 1 of 2, so more rows remain.
    http
      .expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'GET')
      .flush(page([inv({ id: 'a' })], 2));
    view.fixture.detectChanges();

    expect(lastCb).not.toBeNull();
    // Entries that do not intersect load nothing.
    lastCb?.([{ isIntersecting: false }]);
    http.expectNone((r) => r.url.endsWith('/api/invoices') && r.method === 'GET');

    // An intersecting entry makes loadMore fetch the next page.
    lastCb?.([{ isIntersecting: true }]);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'GET')
      .flush(page([inv({ id: 'b' })], 2, 1));

    view.fixture.destroy();
    expect(disconnected).toBe(true);
  });
});

describe('InvoicesComponent filter declaration', () => {
  /** The component, with the filter machinery this suite walks. */
  interface FilterHost {
    filterSignals: readonly {
      signal: { (): string; set(v: string): void };
      key: string;
    }[];
    filterParams(): Record<string, unknown>;
    resetFilters(): void;
    activeFilterCount(): number;
    segment(): string;
  }

  it('resets every filter it declares and keeps the segment', async () => {
    // The count, the reset and the request each kept their own list. A filter added to
    // one and forgotten in another is invisible: the control moves, and the list does
    // not change. This is what /applications was reported broken for.
    const { c, http } = await setup({ queryParams: { seg: 'paid' } });
    const host = c as unknown as FilterHost;
    for (const f of host.filterSignals) f.signal.set('x');

    host.resetFilters();
    http.expectOne((r) => r.url.endsWith('/api/invoices')).flush(page([], 0));

    for (const f of host.filterSignals) expect(f.signal()).toBe('');
    expect(host.segment()).toBe('paid');
  });

  it('sends every declared filter that has a value', async () => {
    const { c } = await setup();
    const host = c as unknown as FilterHost;
    for (const f of host.filterSignals) f.signal.set('7');

    const params = host.filterParams();
    expect(Object.keys(params).sort()).toEqual(host.filterSignals.map((f) => f.key).sort());
  });

  it('counts every declared filter', async () => {
    const { c } = await setup();
    const host = c as unknown as FilterHost;
    for (const f of host.filterSignals) f.signal.set('7');
    expect(host.activeFilterCount()).toBe(host.filterSignals.length);
  });
});

// --- list/detail (FE10c) ---------------------------------------------------

/** Let `matchMedia` match the queries that contain one of the given parts. */
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
const realMatchMedia = window.matchMedia;

const BOOKING: InvoiceBooking = {
  id: 'b-1',
  budgetId: 'cc-1',
  pathKey: 'VS-220',
  budgetName: 'Maschinenbau',
  fiscalYearId: 'fy',
  kind: 'expense',
  amount: '50.00',
  description: 'Anzahlung',
  paymentDate: '2026-01-05',
  parentExpenseId: null,
  createdAt: '2026-01-05T00:00:00Z',
};

describe('InvoicesComponent (list/detail)', () => {
  afterEach(() => {
    window.matchMedia = realMatchMedia;
    TestBed.inject(HttpTestingController).verify();
  });

  it('lists the invoices by month with status, number and due date', async () => {
    setViewport('min-width: 1200px');
    const { container } = await setup({
      initial: [inv(), inv({ id: 'i-2', status: 'paid', supplier: null, number: 'R-2', issueDate: '2025-12-20' })],
    });
    const months = [...container.querySelectorAll('.inv__month')].map((h) => h.textContent?.trim());
    expect(months).toEqual(['Januar 2026', 'Dezember 2025']);
    expect(screen.getByRole('link', { name: /ACME GmbH/ }).getAttribute('href')).toContain('id=i-1');
    // A row without supplier is named by its number.
    expect(screen.getByRole('link', { name: /^R-2/ })).toBeInTheDocument();
    expect(screen.getByText('fällig 31.01.')).toBeInTheDocument();
    expect(screen.getByText('Keine Rechnung geöffnet')).toBeInTheDocument();
  });

  it('names a row without supplier and number, and shows the empty sheet of an empty list', async () => {
    setViewport('min-width: 1200px');
    const { c, container, fixture, http } = await setup({ initial: [] });
    expect(container.querySelector('.inv__none--skeleton')).not.toBeNull();
    expect(c.titleOf(inv({ supplier: null, number: null }))).toBe('Rechnung ohne Lieferant');
    c.q.set('x');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Filter zurücksetzen' }));
    expect(c.q()).toBe('');
    lastInvoicesReq(http).flush(page([]));
  });

  it('shows the open invoice and its actions; marks it paid and creates a booking', async () => {
    setViewport('min-width: 1200px');
    const { c, http, fixture, toast } = await setup({ initial: [inv({ linkedBookings: [BOOKING] })] });
    const navigate = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectedId.set('i-1');
    fixture.detectChanges();
    // The tree loads once, for the swatches of the bookings.
    http.expectOne((r) => r.url.endsWith('/api/budgets')).flush([]);
    fixture.detectChanges();
    expect(screen.getByRole('heading', { name: 'ACME GmbH' })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole('button', { name: 'Buchung anlegen' })[0]);
    expect(navigate).toHaveBeenCalledWith(['/expenses'], { queryParams: { new: 'booking', invoice: 'i-1' } });

    const success = jest.spyOn(toast, 'success');
    await userEvent.click(screen.getByRole('button', { name: 'Als bezahlt markieren' }));
    expect(c.markingPaid()).toBe('i-1');
    // A second click while it runs sends nothing.
    c.markPaid(c.items()[0]);
    const patch = http.expectOne((r) => r.url.endsWith('/api/invoices/i-1') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({ status: 'paid' });
    patch.flush(inv({ status: 'paid', linkedBookings: [BOOKING] }));
    expect(success).toHaveBeenCalledWith('Rechnung als bezahlt markiert.');
    lastInvoicesReq(http).flush(page([inv({ status: 'paid', linkedBookings: [BOOKING] })]));
    expect(c.items()[0].status).toBe('paid');
    // A paid invoice is not marked again.
    c.markPaid(c.items()[0]);
    navigate.mockRestore();
  });

  it('reports a failed "mark paid"', async () => {
    const { c, http, toast } = await setup();
    const error = jest.spyOn(toast, 'error');
    c.markPaid(c.items()[0]);
    http
      .expectOne((r) => r.url.endsWith('/api/invoices/i-1'))
      .flush({ detail: 'Nein' }, { status: 409, statusText: 'x' });
    expect(error).toHaveBeenCalledWith('Nein');
    expect(c.markingPaid()).toBeNull();
  });

  it('keeps a loaded invoice of a deep link up to date after "mark paid"', async () => {
    const { c, http, fixture } = await setup({ initial: [], queryParams: { id: 'i-7' } });
    fixture.detectChanges();
    http.expectOne((r) => r.url.endsWith('/api/invoices/i-7')).flush(inv({ id: 'i-7' }));
    c.markPaid(c.selectedInvoice());
    http.expectOne((r) => r.url.endsWith('/api/invoices/i-7')).flush(inv({ id: 'i-7', status: 'paid' }));
    lastInvoicesReq(http).flush(page([]));
    expect(c.selectedInvoice().status).toBe('paid');
  });

  it('builds the row menu from the rights and runs every item', async () => {
    const { c, http } = await setup();
    const row = c.items()[0];
    expect(c.rowMenu(row).flatMap((s: { items: { id: string }[] }) => s.items.map((i) => i.id))).toEqual([
      'edit',
      'paid',
      'book',
      'file',
      'delete',
    ]);
    const navigate = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.onRowMenu({ id: 'book', label: '' }, row);
    expect(navigate).toHaveBeenCalledWith(['/expenses'], { queryParams: { new: 'booking', invoice: 'i-1' } });
    c.onRowMenu({ id: 'edit', label: '' }, row);
    expect(c.editing()).toBe(row);
    c.onRowMenu({ id: 'delete', label: '' }, row);
    expect(c.confirmDelete()).toBe(row);
    const blob = jest.spyOn(downloadUtil, 'downloadBlob').mockImplementation(() => undefined);
    c.onRowMenu({ id: 'file', label: '' }, row);
    http.expectOne((r) => r.url.endsWith('/api/invoices/i-1/file')).flush(new Blob(['x']));
    c.onRowMenu({ id: 'paid', label: '' }, row);
    http.expectOne((r) => r.url.endsWith('/api/invoices/i-1') && r.method === 'PATCH').flush(inv({ status: 'paid' }));
    lastInvoicesReq(http).flush(page([inv({ status: 'paid' })]));
    c.onRowMenu({ id: 'other', label: '' }, row);
    expect(c.rowMenuLabel(row)).toBe('Aktionen für Rechnung R-001');
    expect(c.rowMenuLabel(inv({ number: null, supplier: null }))).toBe('Aktionen für Rechnung ');
    blob.mockRestore();
    navigate.mockRestore();
  });

  it('offers a reader only the receipt in the row menu', async () => {
    const { c } = await setup({ canManage: false });
    expect(c.rowMenu(inv({ hasFile: false }))).toEqual([]);
    expect(c.rowMenu(inv()).flatMap((s: { items: { id: string }[] }) => s.items.map((i) => i.id))).toEqual(['file']);
  });

  it('opens and closes a row and a form through the URL', async () => {
    const { c } = await setup();
    const navigate = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.openInvoice('i-3');
    expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { id: 'i-3' } }));
    c.closeDetail();
    expect(navigate).toHaveBeenLastCalledWith([], expect.objectContaining({ queryParams: { id: null } }));
    navigate.mockClear();
    c.openCreate();
    expect(c.formMode()).toBe('create');
    expect(c.detailView()).toBe('form');
    expect(c.formTitle()).toBe('Rechnung hinzufügen');
    c.closeDetail();
    expect(c.formMode()).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
    c.openEdit(c.items()[0]);
    expect(c.formTitle()).toBe('Rechnung bearbeiten');
    navigate.mockRestore();
  });

  it('opens a new invoice after the create', async () => {
    const { c, http } = await setup();
    const navigate = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.openCreate();
    c.newNumber.set('R-9');
    c.newSupplier.set('X');
    c.newGross.set('10');
    c.create({ preventDefault: jest.fn() } as unknown as Event);
    http.expectOne((r) => r.url.endsWith('/api/invoices') && r.method === 'POST').flush(inv({ id: 'new' }));
    lastInvoicesReq(http).flush(page([inv({ id: 'new' })]));
    expect(navigate).toHaveBeenCalledWith([], expect.objectContaining({ queryParams: { id: 'new' } }));
    navigate.mockRestore();
  });

  it('closes the detail of a deleted invoice', async () => {
    const { c, http } = await setup();
    const navigate = jest.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    c.selectedId.set('i-1');
    c.openEdit(c.items()[0]);
    c.askDelete(c.items()[0]);
    c.doDelete();
    http.expectOne((r) => r.method === 'DELETE').flush(null);
    lastInvoicesReq(http).flush(page([]));
    expect(c.editing()).toBeNull();
    expect(navigate).toHaveBeenCalledWith([], expect.objectContaining({ queryParams: { id: null } }));
    navigate.mockRestore();
  });

  it('searches the number of a duplicate in every segment ("Vorhandene öffnen")', async () => {
    const { c, http } = await setup({ queryParams: { seg: 'paid' } });
    c.openDuplicate(); // nothing to open yet
    const file = new File(['x'], 'a.pdf', { type: 'application/pdf' });
    c.onFilePicked({ target: { files: [file], value: 'x' } } as unknown as Event);
    http.expectOne((r) => r.url.endsWith('/api/invoices/parse')).flush({ ...PARSE, duplicate: true, number: 'DUP' });
    expect(c.importFileSize()).toBe(1);
    expect(c.formTitle()).toBe('Importierte Rechnung prüfen');
    c.openDuplicate();
    expect(c.createOpen()).toBe(false);
    expect(c.q()).toBe('DUP');
    expect(c.segment()).toBe('all');
    const req = lastInvoicesReq(http);
    expect(req.request.params.get('q')).toBe('DUP');
    req.flush(page([]));
  });

  it('opens the file picker from the header menu of a phone', async () => {
    setViewport('max-width: 768px');
    const { c, container } = await setup();
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    const click = jest.spyOn(input, 'click').mockImplementation(() => undefined);
    c.onHeaderMenu({ id: 'import', label: '' });
    expect(click).toHaveBeenCalled();
    c.onHeaderMenu({ id: 'other', label: '' });
    expect(click).toHaveBeenCalledTimes(1);
    // The phone has the form in a bottom sheet.
    expect(screen.getByRole('button', { name: 'Rechnung' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Rechnung' }));
    expect(screen.getByRole('dialog', { name: 'Rechnung hinzufügen' }).classList.contains('ss--bottom')).toBe(true);
    expect(c.detailView()).toBe('none');
  });

  it('shows the whole page as the drop target while a PDF is dragged over it', async () => {
    const { c, fixture, container } = await setup();
    c.dragActive.set(true);
    fixture.detectChanges();
    expect(container.querySelector('.inv__dropOverlay')?.textContent).toContain('PDF hier ablegen, um zu importieren');
  });

  it('formats days and loads the tree only once', async () => {
    const { c, http, fixture } = await setup({ initial: [inv({ linkedBookings: [BOOKING] }), inv({ id: 'i-2', linkedBookings: [BOOKING] })] });
    expect(c.day('2026-09-28')).toBe('28.09.');
    c.selectedId.set('i-1');
    fixture.detectChanges();
    http.expectOne((r) => r.url.endsWith('/api/budgets')).error(new ProgressEvent('x'));
    c.selectedId.set('i-2');
    fixture.detectChanges();
    http.expectNone((r) => r.url.endsWith('/api/budgets'));
    expect(c.tree()).toEqual([]);
  });

  it('marks the page as a pane page side by side', async () => {
    setViewport('min-width: 1200px');
    const { fixture } = await setup();
    expect(fixture.nativeElement.classList.contains('pane-page')).toBe(true);
    fixture.destroy();
  });
});
