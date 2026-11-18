import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { SKIP_LOADING } from '@stupa-makers/ui-kit';
import { ActivityApiService } from './activity.service';
import { USE_MOCK_API } from './api.config';

describe('ActivityApiService', () => {
  let api: ActivityApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    });
    api = TestBed.inject(ActivityApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('reads a step without filters and without the overlay', () => {
    api.list().subscribe();
    const req = http.expectOne((r) => r.url === '/api/activity');
    expect(req.request.params.keys()).toEqual([]);
    expect(req.request.context.get(SKIP_LOADING)).toBe(true);
    req.flush({ entries: [], nextCursor: null, seenAt: null, readAt: '2026-11-17T10:00:00Z' });
  });

  it('sends the kinds, the own choice, the cursor and the language', () => {
    api.list({ kinds: ['todo', 'ticket'], own: true, cursor: 'abc', lang: 'en' }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/activity');
    expect(req.request.params.getAll('kind')).toEqual(['todo', 'ticket']);
    expect(req.request.params.get('own')).toBe('true');
    expect(req.request.params.get('cursor')).toBe('abc');
    expect(req.request.params.get('lang')).toBe('en');
    req.flush({ entries: [], nextCursor: null, seenAt: null, readAt: '2026-11-17T10:00:00Z' });
  });

  it('reads the status and stores the visit mark', () => {
    let out: unknown;
    api.status().subscribe((s) => (out = s));
    const status = http.expectOne('/api/activity/status');
    expect(status.request.context.get(SKIP_LOADING)).toBe(true);
    status.flush({ hasNew: true });
    expect(out).toEqual({ hasNew: true });

    api.markSeen('2026-11-17T10:00:00Z').subscribe();
    const seen = http.expectOne('/api/activity/seen');
    expect(seen.request.method).toBe('POST');
    expect(seen.request.body).toEqual({ at: '2026-11-17T10:00:00Z' });
    seen.flush(null);
  });
});
