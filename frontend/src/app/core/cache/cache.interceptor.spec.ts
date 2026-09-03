import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { cacheInterceptor, cached, listContext } from './cache.interceptor';
import { HttpCacheService } from './http-cache.service';

describe('cacheInterceptor', () => {
  let http: HttpClient;
  let mock: HttpTestingController;
  let cache: HttpCacheService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([cacheInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    mock = TestBed.inject(HttpTestingController);
    cache = TestBed.inject(HttpCacheService);
  });

  afterEach(() => mock.verify());

  describe('listContext', () => {
    it('paints page one from the cache before the request answers', () => {
      // What a page switch is supposed to feel like: the list is there, and corrects
      // itself a moment later rather than showing a loading state for a round trip.
      http.get('/api/expenses', { context: listContext(0) }).subscribe();
      mock.expectOne('/api/expenses').flush({ items: ['a'], total: 1, offset: 0 });

      const seen: unknown[] = [];
      http.get('/api/expenses', { context: listContext(0) }).subscribe((b) => seen.push(b));
      // Before the request is answered — the cached page is already delivered.
      expect(seen).toEqual([{ items: ['a'], total: 1, offset: 0 }]);

      mock.expectOne('/api/expenses').flush({ items: ['a', 'b'], total: 2, offset: 0 });
      expect(seen).toHaveLength(2);
    });

    it('never caches a load-more page, which would append the same rows twice', () => {
      // A cached GET emits twice, and a load-more subscriber appends what it is given.
      // Two emissions there means every row of that page arriving a second time.
      http.get('/api/expenses?offset=20', { context: listContext(20) }).subscribe();
      mock.expectOne('/api/expenses?offset=20').flush({ items: ['c'], total: 40, offset: 20 });
      expect(cache.size).toBe(0);

      const seen: unknown[] = [];
      http
        .get('/api/expenses?offset=20', { context: listContext(20) })
        .subscribe((b) => seen.push(b));
      expect(seen).toEqual([]);
      mock.expectOne('/api/expenses?offset=20').flush({ items: ['c'], total: 40, offset: 20 });
      expect(seen).toHaveLength(1);
    });

    it('treats a missing offset as page one', () => {
      // The list APIs leave `offset` off the first request rather than sending 0.
      http.get('/api/invoices', { context: listContext(undefined) }).subscribe();
      mock.expectOne('/api/invoices').flush({ items: [], total: 0, offset: 0 });
      expect(cache.size).toBe(1);
    });

    it('drops the cached page when something is written to the collection', () => {
      // A booking that was just created cannot be missing from the list that follows it.
      http.get('/api/expenses', { context: listContext(0) }).subscribe();
      mock.expectOne('/api/expenses').flush({ items: ['a'], total: 1, offset: 0 });
      expect(cache.size).toBe(1);

      http.post('/api/expenses', {}).subscribe();
      mock.expectOne('/api/expenses').flush({});
      expect(cache.size).toBe(0);
    });
  });

  it('does not cache a request that did not ask to be cached', () => {
    http.get('/api/budgets').subscribe();
    mock.expectOne('/api/budgets').flush(['a']);
    expect(cache.size).toBe(0);
  });

  it('stores a cached GET and serves it again, then the fresh answer', () => {
    // The whole point: the page paints from the cache and then corrects itself. A caller
    // that took only the first emission would keep the old answer, which is exactly why
    // this is opt-in per call site.
    http.get('/api/budgets', { context: cached() }).subscribe();
    mock.expectOne('/api/budgets').flush(['old']);

    const seen: unknown[] = [];
    http.get('/api/budgets', { context: cached() }).subscribe((b) => seen.push(b));
    expect(seen).toEqual([['old']]);

    mock.expectOne('/api/budgets').flush(['new']);
    expect(seen).toEqual([['old'], ['new']]);
  });

  it('serves the cached value BEFORE the request goes out', () => {
    // `concat`, not `merge`: the subscriber must have something to paint before anything
    // else happens, whatever the network does.
    http.get('/api/budgets', { context: cached() }).subscribe();
    mock.expectOne('/api/budgets').flush(['old']);

    let first: unknown;
    http.get('/api/budgets', { context: cached() }).subscribe((b) => (first ??= b));
    expect(first).toEqual(['old']);
    mock.expectOne('/api/budgets').flush(['new']);
  });

  it('emits once when nothing is cached yet', () => {
    const seen: unknown[] = [];
    http.get('/api/budgets', { context: cached() }).subscribe((b) => seen.push(b));
    mock.expectOne('/api/budgets').flush(['a']);
    expect(seen).toEqual([['a']]);
  });

  it('refetches once the entry is past its ttl', () => {
    http.get('/api/budgets', { context: cached(0) }).subscribe();
    mock.expectOne('/api/budgets').flush(['old']);

    const seen: unknown[] = [];
    http.get('/api/budgets', { context: cached(0) }).subscribe((b) => seen.push(b));
    mock.expectOne('/api/budgets').flush(['new']);
    // A ttl of zero can never be served, so there is one emission and it is the fresh one.
    expect(seen).toEqual([['new']]);
  });

  it('keeps the query string apart, because it is a different answer', () => {
    http.get('/api/budgets', { context: cached() }).subscribe();
    mock.expectOne('/api/budgets').flush(['all']);

    const seen: unknown[] = [];
    http
      .get('/api/budgets', { params: { gremium: 'g1' }, context: cached() })
      .subscribe((b) => seen.push(b));
    mock.expectOne('/api/budgets?gremium=g1').flush(['scoped']);
    expect(seen).toEqual([['scoped']]);
  });

  it('does not store a response that was not a 200', () => {
    http.get('/api/budgets', { context: cached() }).subscribe({ error: () => undefined });
    mock.expectOne('/api/budgets').flush(null, { status: 500, statusText: 'Server Error' });
    expect(cache.size).toBe(0);
  });

  describe('invalidation', () => {
    beforeEach(() => {
      http.get('/api/budgets', { context: cached() }).subscribe();
      mock.expectOne('/api/budgets').flush(['old']);
      expect(cache.size).toBe(1);
    });

    it('a mutation under the same collection drops it', () => {
      // A cost centre that was just created cannot be missing from the list that follows.
      http.post('/api/budgets', {}).subscribe();
      expect(cache.size).toBe(0);
      mock.expectOne('/api/budgets').flush({});
    });

    it('a mutation deeper in the collection drops it too', () => {
      http.patch('/api/budgets/b1', {}).subscribe();
      expect(cache.size).toBe(0);
      mock.expectOne('/api/budgets/b1').flush({});
    });

    it('a mutation elsewhere leaves it alone', () => {
      http.post('/api/applications', {}).subscribe();
      expect(cache.size).toBe(1);
      mock.expectOne('/api/applications').flush({});
    });

    it('invalidates even when the mutation fails', () => {
      // A request that errors may still have changed something. Serving a stale list
      // after a half-failed write is worse than one extra fetch.
      http.post('/api/budgets', {}).subscribe({ error: () => undefined });
      expect(cache.size).toBe(0);
      mock.expectOne('/api/budgets').flush(null, { status: 500, statusText: 'x' });
    });
  });
});
