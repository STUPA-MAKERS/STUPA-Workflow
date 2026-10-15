import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SKIP_LOADING } from '@core/loading/loading.interceptor';
import { USE_MOCK_API } from './api.config';
import { GremienApiService } from './gremien.service';

describe('GremienApiService', () => {
  let api: GremienApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    api = TestBed.inject(GremienApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('reads the overview without the global overlay', () => {
    let rows: unknown;
    api.overview().subscribe((r) => (rows = r));
    const req = http.expectOne('/api/gremien/overview');
    expect(req.request.context.get(SKIP_LOADING)).toBe(true);
    req.flush([]);
    expect(rows).toEqual([]);
  });

  it('reads the members, and the former members on request', () => {
    api.members('g-1').subscribe();
    const current = http.expectOne((r) => r.url === '/api/gremien/g-1/members');
    expect(current.request.params.has('former')).toBe(false);
    current.flush([]);

    api.members('g-1', true).subscribe();
    const former = http.expectOne((r) => r.url === '/api/gremien/g-1/members');
    expect(former.request.params.get('former')).toBe('true');
    former.flush([]);
  });

  it('reads the meetings', () => {
    api.meetings('g-1').subscribe();
    http.expectOne('/api/gremien/g-1/meetings').flush([]);
  });

  it('sends only the bounds of the range that are set', () => {
    api.attendance('g-1').subscribe();
    const plain = http.expectOne((r) => r.url === '/api/gremien/g-1/attendance');
    expect(plain.request.params.keys()).toEqual([]);
    plain.flush({});

    api.attendance('g-1', { from: '2026-05', to: '2026-10' }).subscribe();
    const ranged = http.expectOne((r) => r.url === '/api/gremien/g-1/attendance');
    expect(ranged.request.params.get('from')).toBe('2026-05');
    expect(ranged.request.params.get('to')).toBe('2026-10');
    ranged.flush({});
  });

  it('reads the meetings of one person in one month', () => {
    api.memberAttendance('g-1', 'p-1', '2026-09').subscribe();
    const req = http.expectOne((r) => r.url === '/api/gremien/g-1/attendance/p-1');
    expect(req.request.params.get('month')).toBe('2026-09');
    req.flush({});
  });

  it('sends only the decision filters that are set', () => {
    api.decisions('g-1').subscribe();
    const plain = http.expectOne((r) => r.url === '/api/gremien/g-1/decisions');
    expect(plain.request.params.keys()).toEqual([]);
    plain.flush({ items: [], nextCursor: null });

    api
      .decisions('g-1', { cursor: 'c', q: 'rad', result: 'passed', kind: null, since: '2026-01-01' })
      .subscribe();
    const req = http.expectOne((r) => r.url === '/api/gremien/g-1/decisions');
    expect(req.request.params.get('cursor')).toBe('c');
    expect(req.request.params.get('q')).toBe('rad');
    expect(req.request.params.get('result')).toBe('passed');
    expect(req.request.params.has('kind')).toBe(false);
    expect(req.request.params.get('since')).toBe('2026-01-01');
    req.flush({ items: [], nextCursor: null });
  });
});
