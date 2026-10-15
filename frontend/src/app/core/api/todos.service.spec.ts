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
});
