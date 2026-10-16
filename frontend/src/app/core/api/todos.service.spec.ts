import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SKIP_LOADING } from '@core/loading/loading.interceptor';
import { USE_MOCK_API } from './api.config';
import { TodosApiService } from './todos.service';

describe('TodosApiService', () => {
  let api: TodosApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    api = TestBed.inject(TodosApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('lists the boards, with the gremium filter only when given', () => {
    api.boards().subscribe();
    const all = http.expectOne((r) => r.url === '/api/todos/boards');
    expect(all.request.params.keys()).toEqual([]);
    expect(all.request.context.get(SKIP_LOADING)).toBe(true);
    all.flush([]);

    api.boards('g-1').subscribe();
    const one = http.expectOne((r) => r.url === '/api/todos/boards');
    expect(one.request.params.get('gremiumId')).toBe('g-1');
    one.flush([]);
  });

  it('reads a board and its members', () => {
    api.board('b-1').subscribe();
    http.expectOne('/api/todos/boards/b-1').flush({});
    api.members('b-1').subscribe();
    http.expectOne('/api/todos/boards/b-1/members').flush([]);
  });

  it('creates a card', () => {
    api.createCard({ boardId: 'b-1', title: 'x', links: [{ kind: 'ticket', targetId: 't-1' }] }).subscribe();
    const req = http.expectOne('/api/todos/cards');
    expect(req.request.method).toBe('POST');
    expect(req.request.body.links).toEqual([{ kind: 'ticket', targetId: 't-1' }]);
    req.flush({});
  });

  it('reads the cards linked to a target', () => {
    api.linked('ticket', 't-1').subscribe();
    const req = http.expectOne((r) => r.url === '/api/todos/linked');
    expect(req.request.params.get('kind')).toBe('ticket');
    expect(req.request.params.get('targetId')).toBe('t-1');
    req.flush([]);
  });

  it('polls a board with If-None-Match and keeps the state on a 304', () => {
    const got: unknown[] = [];
    api.pollBoard('b-1', null).subscribe((r) => got.push(r));
    const first = http.expectOne('/api/todos/boards/b-1');
    expect(first.request.headers.has('If-None-Match')).toBe(false);
    first.flush({ id: 'b-1' }, { headers: { ETag: 'W/"1"' } });
    expect(got[0]).toEqual({ board: { id: 'b-1' }, etag: 'W/"1"' });

    api.pollBoard('b-1', 'W/"1"').subscribe((r) => got.push(r));
    const second = http.expectOne('/api/todos/boards/b-1');
    expect(second.request.headers.get('If-None-Match')).toBe('W/"1"');
    second.flush(null, { status: 304, statusText: 'Not Modified' });
    expect(got[1]).toEqual({ board: null, etag: 'W/"1"' });
  });

  it('polls the assigned boards with If-None-Match and keeps the state on a 304', () => {
    const got: unknown[] = [];
    api.pollMineBoards(null).subscribe((r) => got.push(r));
    const first = http.expectOne('/api/todos/mine/boards');
    expect(first.request.headers.has('If-None-Match')).toBe(false);
    expect(first.request.context.get(SKIP_LOADING)).toBe(true);
    first.flush([{ id: 'b-1' }], { headers: { ETag: 'W/"2"' } });
    expect(got[0]).toEqual({ boards: [{ id: 'b-1' }], etag: 'W/"2"' });

    api.pollMineBoards('W/"2"').subscribe((r) => got.push(r));
    const second = http.expectOne('/api/todos/mine/boards');
    expect(second.request.headers.get('If-None-Match')).toBe('W/"2"');
    second.flush(null, { status: 304, statusText: 'Not Modified' });
    expect(got[1]).toEqual({ boards: null, etag: 'W/"2"' });

    const errors: unknown[] = [];
    api.pollMineBoards(null).subscribe({ error: (e: unknown) => errors.push(e) });
    http.expectOne('/api/todos/mine/boards').flush(null, { status: 403, statusText: 'Forbidden' });
    expect(errors).toHaveLength(1);
  });

  it('polls every board for "Alle" with If-None-Match', () => {
    const got: unknown[] = [];
    api.pollAllBoards(null).subscribe((r) => got.push(r));
    const first = http.expectOne('/api/todos/all/boards');
    expect(first.request.headers.has('If-None-Match')).toBe(false);
    first.flush([{ id: 'b-0' }], { headers: { ETag: 'W/"3"' } });
    expect(got[0]).toEqual({ boards: [{ id: 'b-0' }], etag: 'W/"3"' });
    api.pollAllBoards('W/"3"').subscribe((r) => got.push(r));
    const second = http.expectOne('/api/todos/all/boards');
    expect(second.request.headers.get('If-None-Match')).toBe('W/"3"');
    second.flush(null, { status: 304, statusText: 'Not Modified' });
    expect(got[1]).toEqual({ boards: null, etag: 'W/"3"' });
  });

  it('passes any other error of a poll on', () => {
    const errors: unknown[] = [];
    api.pollBoard('b-1', null).subscribe({ error: (e: unknown) => errors.push(e) });
    http.expectOne('/api/todos/boards/b-1').flush(null, { status: 404, statusText: 'Not Found' });
    expect(errors).toHaveLength(1);
  });

  it('changes the board, its columns and its labels', () => {
    const cases: [() => unknown, string, string, unknown][] = [
      [() => api.patchBoard('b', { name: 'N' }).subscribe(), 'PATCH', '/api/todos/boards/b', { name: 'N' }],
      [() => api.addColumn('b', 'C').subscribe(), 'POST', '/api/todos/boards/b/columns', { name: 'C' }],
      [() => api.patchColumn('b', 'c', { isDone: true }).subscribe(), 'PATCH', '/api/todos/boards/b/columns/c', { isDone: true }],
      [() => api.orderColumns('b', ['c2', 'c1']).subscribe(), 'PUT', '/api/todos/boards/b/columns/order', { columnIds: ['c2', 'c1'] }],
      [() => api.addLabel('b', { name: 'L', color: 'red' }).subscribe(), 'POST', '/api/todos/boards/b/labels', { name: 'L', color: 'red' }],
      [() => api.patchLabel('b', 'l', { color: 'blue' }).subscribe(), 'PATCH', '/api/todos/boards/b/labels/l', { color: 'blue' }],
      [() => api.deleteLabel('b', 'l').subscribe(), 'DELETE', '/api/todos/boards/b/labels/l', null],
    ];
    for (const [call, method, url, body] of cases) {
      call();
      const req = http.expectOne(url);
      expect(req.request.method).toBe(method);
      expect(req.request.body).toEqual(body);
      expect(req.request.context.get(SKIP_LOADING)).toBe(true);
      req.flush({});
    }
  });

  it('deletes a column, with moveTo only when given', () => {
    api.deleteColumn('b', 'c').subscribe();
    const plain = http.expectOne((r) => r.url === '/api/todos/boards/b/columns/c');
    expect(plain.request.method).toBe('DELETE');
    expect(plain.request.params.has('moveTo')).toBe(false);
    plain.flush({});
    api.deleteColumn('b', 'c', 'c2').subscribe();
    const moved = http.expectOne((r) => r.url === '/api/todos/boards/b/columns/c');
    expect(moved.request.params.get('moveTo')).toBe('c2');
    moved.flush({});
  });

  it('pages the archive, with the search only when given', () => {
    api.archive('b').subscribe();
    const first = http.expectOne((r) => r.url === '/api/todos/boards/b/archive');
    expect(first.request.params.get('limit')).toBe('50');
    expect(first.request.params.get('offset')).toBe('0');
    expect(first.request.params.has('q')).toBe(false);
    first.flush({ items: [], total: 0 });
    api.archive('b', 'Haus', 50, 10).subscribe();
    const next = http.expectOne((r) => r.url === '/api/todos/boards/b/archive');
    expect(next.request.params.get('q')).toBe('Haus');
    expect(next.request.params.get('offset')).toBe('50');
    expect(next.request.params.get('limit')).toBe('10');
    next.flush({ items: [], total: 0 });
  });

  it('reads and changes a card and its parts', () => {
    const cases: [() => unknown, string, string, unknown][] = [
      [() => api.card('k').subscribe(), 'GET', '/api/todos/cards/k', null],
      [() => api.patchCard('k', { version: 2, title: 'T' }).subscribe(), 'PATCH', '/api/todos/cards/k', { version: 2, title: 'T' }],
      [() => api.moveCard('k', { columnId: 'c', afterId: 'x' }).subscribe(), 'POST', '/api/todos/cards/k/move', { columnId: 'c', afterId: 'x' }],
      [() => api.transferCard('k', { boardId: 'b' }).subscribe(), 'POST', '/api/todos/cards/k/transfer', { boardId: 'b' }],
      [() => api.archiveCard('k').subscribe(), 'DELETE', '/api/todos/cards/k', null],
      [() => api.restoreCard('k').subscribe(), 'POST', '/api/todos/cards/k/restore', null],
      [() => api.addAssignee('k', 'p').subscribe(), 'POST', '/api/todos/cards/k/assignees', { principalId: 'p' }],
      [() => api.removeAssignee('k', 'p').subscribe(), 'DELETE', '/api/todos/cards/k/assignees/p', null],
      [() => api.addCardLabel('k', 'l').subscribe(), 'POST', '/api/todos/cards/k/labels', { labelId: 'l' }],
      [() => api.removeCardLabel('k', 'l').subscribe(), 'DELETE', '/api/todos/cards/k/labels/l', null],
      [() => api.addCheckItem('k', 'Punkt').subscribe(), 'POST', '/api/todos/cards/k/checklist', { text: 'Punkt' }],
      [() => api.patchCheckItem('k', 'i', { done: true }).subscribe(), 'PATCH', '/api/todos/cards/k/checklist/i', { done: true }],
      [() => api.deleteCheckItem('k', 'i').subscribe(), 'DELETE', '/api/todos/cards/k/checklist/i', null],
      [() => api.addLink('k', 'ticket', 't').subscribe(), 'POST', '/api/todos/cards/k/links', { kind: 'ticket', targetId: 't' }],
      [() => api.removeLink('k', 'li').subscribe(), 'DELETE', '/api/todos/cards/k/links/li', null],
      [() => api.addComment('k', 'Hallo', ['p']).subscribe(), 'POST', '/api/todos/cards/k/comments', { body: 'Hallo', mentions: ['p'] }],
      [() => api.addComment('k', 'Hallo').subscribe(), 'POST', '/api/todos/cards/k/comments', { body: 'Hallo', mentions: [] }],
      [
        () => api.addComment('k', '', [], { attachmentIds: ['d'], draftToken: 't' }).subscribe(),
        'POST',
        '/api/todos/cards/k/comments',
        { body: '', mentions: [], attachmentIds: ['d'], draftToken: 't' },
      ],
      [() => api.editComment('k', 'm', 'Neu').subscribe(), 'PATCH', '/api/todos/cards/k/comments/m', { body: 'Neu', mentions: [] }],
      [() => api.editComment('k', 'm', 'Neu', ['p']).subscribe(), 'PATCH', '/api/todos/cards/k/comments/m', { body: 'Neu', mentions: ['p'] }],
      [() => api.deleteComment('k', 'm').subscribe(), 'DELETE', '/api/todos/cards/k/comments/m', null],
      [() => api.mine().subscribe(), 'GET', '/api/todos/mine', null],
    ];
    for (const [call, method, url, body] of cases) {
      call();
      const req = http.expectOne(url);
      expect(req.request.method).toBe(method);
      expect(req.request.body).toEqual(body);
      expect(req.request.context.get(SKIP_LOADING)).toBe(true);
      req.flush({});
    }
  });

  it('searches the link targets, without the card only when none is given', () => {
    api.linkTargets('Haus', 'all').subscribe();
    const all = http.expectOne((r) => r.url === '/api/todos/link-targets');
    expect(all.request.params.get('q')).toBe('Haus');
    expect(all.request.params.get('kind')).toBe('all');
    expect(all.request.params.has('excludeCardId')).toBe(false);
    all.flush([]);
    api.linkTargets('Haus', 'todo', 'k').subscribe();
    const own = http.expectOne((r) => r.url === '/api/todos/link-targets');
    expect(own.request.params.get('excludeCardId')).toBe('k');
    own.flush([]);
  });
});

