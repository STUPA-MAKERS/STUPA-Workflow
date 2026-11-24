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

  it('reads and writes the own tickets of the reporter', () => {
    api.mine().subscribe();
    expect(http.expectOne((r) => r.url === '/api/tickets/mine').request.context.get(SKIP_LOADING)).toBe(true);
    api.getMine('t-1').subscribe();
    http.expectOne('/api/tickets/mine/t-1').flush({});
    api.getMine('t-1', { detail: true }).subscribe();
    http.expectOne('/api/tickets/mine/t-1').flush({});
    api.addMyNote('t-1', 'Hallo').subscribe();
    expect(http.expectOne('/api/tickets/mine/t-1/notes').request.body).toMatchObject({ body: 'Hallo' });
    api.editMyNote('t-1', 'n-1', 'Neu').subscribe();
    expect(http.expectOne('/api/tickets/mine/t-1/notes/n-1').request.method).toBe('PATCH');
    api.deleteMyNote('t-1', 'n-1').subscribe();
    expect(http.expectOne('/api/tickets/mine/t-1/notes/n-1').request.method).toBe('DELETE');
  });

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

  it('works the Bereiche and the Postfach of a Bereich', () => {
    api.areas().subscribe();
    expect(http.expectOne('/api/tickets/areas').request.context.get(SKIP_LOADING)).toBe(true);
    api.adminAreas().subscribe();
    expect(http.expectOne('/api/admin/ticket-areas').request.method).toBe('GET');
    api.reportAreas().subscribe();
    expect(http.expectOne('/api/tickets/report-areas').request.method).toBe('GET');
    api.createArea({ name: 'Büro' } as never).subscribe();
    expect(http.expectOne('/api/admin/ticket-areas').request.body).toEqual({ name: 'Büro' });
    api.updateArea('a-1', { name: 'Neu' }).subscribe();
    expect(http.expectOne('/api/admin/ticket-areas/a-1').request.method).toBe('PATCH');
    api.deleteArea('a-1').subscribe();
    expect(http.expectOne('/api/admin/ticket-areas/a-1').request.method).toBe('DELETE');

    api.adminMailboxes().subscribe();
    expect(http.expectOne('/api/admin/ticket-mailboxes').request.context.get(SKIP_LOADING)).toBe(true);
    api.createMailbox('a-1', { address: 'buero@example.org' } as never).subscribe();
    expect(http.expectOne('/api/admin/ticket-areas/a-1/mailbox').request.method).toBe('POST');
    api.updateMailbox('a-1', { enabled: true }).subscribe();
    expect(http.expectOne('/api/admin/ticket-areas/a-1/mailbox').request.body).toEqual({ enabled: true });
    api.deleteMailbox('a-1').subscribe();
    expect(http.expectOne('/api/admin/ticket-areas/a-1/mailbox').request.method).toBe('DELETE');
    api.testMailbox('a-1').subscribe();
    expect(http.expectOne('/api/admin/ticket-areas/a-1/mailbox/test').request.body).toEqual({});
  });

  it('creates a ticket by hand, sends a mail again and files a file in Paperless', () => {
    api.createManual({ title: 't' } as never).subscribe();
    expect(http.expectOne('/api/tickets/manual').request.body).toEqual({ title: 't' });
    api.resendMail('t-1', 'm-1').subscribe();
    expect(http.expectOne('/api/tickets/t-1/mails/m-1/resend').request.method).toBe('POST');
    api.fileInPaperless('t-1', 'f-1').subscribe();
    expect(http.expectOne('/api/tickets/t-1/files/f-1/paperless').request.body).toEqual({});
    expect(api.mailSourceUrl('t-1', 'm-1')).toBe('/api/tickets/t-1/mails/m-1/source');
  });

  it('sends the receivers, the mentions and the visibility of a note only when it has them', () => {
    api.addNote('t-1', 'Hallo').subscribe();
    expect(http.expectOne('/api/tickets/t-1/notes').request.body).toEqual({ body: 'Hallo' });
    api.addNote('t-1', 'Hallo', {}, 'public', ['p-1'], { to: ['a@example.org'], cc: [] }).subscribe();
    expect(http.expectOne('/api/tickets/t-1/notes').request.body).toEqual({
      body: 'Hallo',
      to: ['a@example.org'],
      cc: [],
      mentions: ['p-1'],
      visibility: 'public',
    });
    api.editNote('t-1', 'n-1', 'Neu', ['p-2']).subscribe();
    expect(http.expectOne('/api/tickets/t-1/notes/n-1').request.body).toEqual({ body: 'Neu', mentions: ['p-2'] });
    api.editNote('t-1', 'n-1', 'Neu').subscribe();
    expect(http.expectOne('/api/tickets/t-1/notes/n-1').request.body).toEqual({ body: 'Neu' });
  });

  it('builds the download url of an attachment', () => {
    expect(api.attachmentUrl('a-1')).toBe('/api/attachments/a-1/download');
  });
});
