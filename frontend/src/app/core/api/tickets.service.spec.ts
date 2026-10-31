import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SKIP_LOADING } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from './api.config';
import { TicketsApiService } from './tickets.service';

describe('TicketsApiService', () => {
  let api: TicketsApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    api = TestBed.inject(TicketsApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('sends a ticket', () => {
    let out: unknown;
    api.create({ kind: 'bug', title: 't', body: 'b', context: {} }).subscribe((r) => (out = r));
    const req = http.expectOne('/api/tickets');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ kind: 'bug', title: 't', body: 'b', context: {} });
    req.flush({ number: 'T-0001' });
    expect(out).toEqual({ number: 'T-0001' });
  });

  it('lists without filters and without the overlay', () => {
    api.list().subscribe();
    const req = http.expectOne((r) => r.url === '/api/tickets');
    expect(req.request.params.keys()).toEqual([]);
    expect(req.request.context.get(SKIP_LOADING)).toBe(true);
    req.flush({ items: [], total: 0, limit: 50, offset: 0 });
  });

  it('repeats the state and kind filters and trims the search', () => {
    api
      .list({ status: ['new', 'in_progress'], kind: ['bug'], assignee: 'me', q: '  pdf ', limit: 200, offset: 0 })
      .subscribe();
    const req = http.expectOne((r) => r.url === '/api/tickets');
    expect(req.request.params.getAll('status')).toEqual(['new', 'in_progress']);
    expect(req.request.params.getAll('kind')).toEqual(['bug']);
    expect(req.request.params.get('assignee')).toBe('me');
    expect(req.request.params.get('q')).toBe('pdf');
    expect(req.request.params.get('limit')).toBe('200');
    expect(req.request.params.get('offset')).toBe('0');
    req.flush({ items: [], total: 0, limit: 200, offset: 0 });
  });

  it('leaves out an empty search', () => {
    api.list({ q: '   ' }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/tickets');
    expect(req.request.params.has('q')).toBe(false);
    req.flush({ items: [], total: 0, limit: 50, offset: 0 });
  });

  it('reads the counts, the assignees and one ticket quietly', () => {
    api.counts().subscribe();
    const counts = http.expectOne('/api/tickets/counts');
    expect(counts.request.context.get(SKIP_LOADING)).toBe(true);
    counts.flush({ new: 1, inProgress: 0, done: 0, rejected: 0 });

    api.assignees().subscribe();
    http.expectOne('/api/tickets/assignees').flush([]);

    api.get('t-1').subscribe();
    const one = http.expectOne('/api/tickets/t-1');
    expect(one.request.context.get(SKIP_LOADING)).toBe(true);
    one.flush({});
  });

  it('patches a ticket and works the notes', () => {
    api.patch('t-1', { status: 'done', completeTodos: true }).subscribe();
    const patch = http.expectOne('/api/tickets/t-1');
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ status: 'done', completeTodos: true });
    patch.flush({});

    api.addNote('t-1', 'hi').subscribe();
    const add = http.expectOne('/api/tickets/t-1/notes');
    expect(add.request.method).toBe('POST');
    expect(add.request.body).toEqual({ body: 'hi' });
    add.flush({});

    api.editNote('t-1', 'n-1', 'ho').subscribe();
    const edit = http.expectOne('/api/tickets/t-1/notes/n-1');
    expect(edit.request.method).toBe('PATCH');
    expect(edit.request.body).toEqual({ body: 'ho' });
    edit.flush({});

    api.deleteNote('t-1', 'n-1').subscribe();
    const del = http.expectOne('/api/tickets/t-1/notes/n-1');
    expect(del.request.method).toBe('DELETE');
    del.flush(null);

    api.addNote('t-1', '', { attachmentIds: ['d1'], draftToken: 'tok' }).subscribe();
    const files = http.expectOne('/api/tickets/t-1/notes');
    expect(files.request.body).toEqual({ body: '', attachmentIds: ['d1'], draftToken: 'tok' });
    files.flush({});
  });

  it('blocks and unblocks the sender and works the block list', () => {
    api.blockSender('t-1').subscribe();
    const block = http.expectOne('/api/tickets/t-1/block-sender');
    expect(block.request.method).toBe('POST');
    block.flush({});

    api.unblockSender('t-1').subscribe();
    const unblock = http.expectOne('/api/tickets/t-1/block-sender');
    expect(unblock.request.method).toBe('DELETE');
    unblock.flush({});

    api.blockedSenders().subscribe();
    const list = http.expectOne('/api/tickets/blocked-senders');
    expect(list.request.method).toBe('GET');
    list.flush([]);

    api.deleteBlockedSender('b-1').subscribe();
    const lift = http.expectOne('/api/tickets/blocked-senders/b-1');
    expect(lift.request.method).toBe('DELETE');
    lift.flush(null);
  });

  it('builds the download url of an attachment', () => {
    expect(api.attachmentUrl('a-1')).toBe('/api/attachments/a-1/download');
  });
});
