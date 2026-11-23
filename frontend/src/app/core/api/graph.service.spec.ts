import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SKIP_LOADING } from '@stupa-makers/ui-kit';
import { USE_MOCK_API } from './api.config';
import { GRAPH_KINDS, GRAPH_RELATIONS, GraphApiService, type GraphFilters } from './graph.service';

const NONE: GraphFilters = {
  kinds: [],
  from: '',
  to: '',
  relations: 'all',
  q: '',
  depth: 2,
  single: false,
  noAccess: false,
};

describe('GraphApiService', () => {
  let api: GraphApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    api = TestBed.inject(GraphApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('reads the first page without filters and without the overlay', () => {
    api.page(NONE).subscribe();
    const req = http.expectOne((r) => r.url === '/api/graph');
    expect(req.request.params.keys()).toEqual([]);
    expect(req.request.context.get(SKIP_LOADING)).toBe(true);
    req.flush({ nodes: [], edges: [], nextCursor: null });
  });

  /** § F/collaboration/graph/001431: the query of `GET /api/graph`. */
  it('sends every filter, both switches and the cursor', () => {
    api
      .page(
        {
          kinds: ['meeting', 'todo'],
          from: '2026-01-01',
          to: '2026-12-31',
          relations: 'links',
          q: ' Haushalt ',
          depth: 4,
          single: true,
          noAccess: true,
        },
        '60',
      )
      .subscribe();
    const req = http.expectOne((r) => r.url === '/api/graph');
    const params = req.request.params;
    expect(params.getAll('kinds')).toEqual(['meeting', 'todo']);
    expect(params.get('from')).toBe('2026-01-01');
    expect(params.get('to')).toBe('2026-12-31');
    expect(params.get('relations')).toBe('links');
    expect(params.get('q')).toBe('Haushalt');
    expect(params.get('depth')).toBe('4');
    expect(params.get('single')).toBe('true');
    expect(params.get('noAccess')).toBe('true');
    expect(params.get('cursor')).toBe('60');
    req.flush({ nodes: [], edges: [], nextCursor: null });
  });

  it('lists the twelve kinds and the three choices of the relations', () => {
    expect(GRAPH_KINDS).toHaveLength(12);
    expect(GRAPH_RELATIONS).toEqual(['all', 'links', 'builtin']);
  });
});
