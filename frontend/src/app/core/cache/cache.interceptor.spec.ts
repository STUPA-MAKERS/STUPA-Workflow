import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { cacheInterceptor, cached, freshly, listContext } from './cache.interceptor';
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
    /**
     * A page switch shows the list at once, and the list corrects itself a moment later, instead of
     * a loading state for a round trip.
     */
    it('paints page one from the cache before the request answers', () => {
      http.get('/api/expenses', { context: listContext(0) }).subscribe();
      mock.expectOne('/api/expenses').flush({ items: ['a'], total: 1, offset: 0 });

      const seen: unknown[] = [];
      http.get('/api/expenses', { context: listContext(0) }).subscribe((b) => seen.push(b));
      expect(seen).toEqual([{ items: ['a'], total: 1, offset: 0 }]);

      mock.expectOne('/api/expenses').flush({ items: ['a', 'b'], total: 2, offset: 0 });
      expect(seen).toHaveLength(2);
    });

    /** A read ahead in flight is not joined either. The detail that the list read ahead stays. */
    it('skips the stored page and a read in flight inside freshly(), and stores the answer', () => {
      http.get('/api/expenses', { context: listContext(0) }).subscribe();
      mock.expectOne('/api/expenses').flush({ items: ['a'] });
      cache.set('/api/expenses/e1', { id: 'e1' });
      http.get('/api/invoices', { context: listContext(0) }).subscribe();

      const seen: unknown[] = [];
      freshly(() => http.get('/api/expenses', { context: listContext(0) }).subscribe((b) => seen.push(b)));
      freshly(() => http.get('/api/invoices', { context: listContext(0) }).subscribe());
      expect(seen).toEqual([]);
      mock.expectOne('/api/expenses').flush({ items: ['a', 'b'] });
      expect(seen).toEqual([{ items: ['a', 'b'] }]);
      const both = mock.match('/api/invoices');
      expect(both).toHaveLength(2);
      both.forEach((r) => r.flush({ items: [] }));
      expect(cache.get('/api/expenses/e1', 60_000)).toEqual({ id: 'e1' });
      expect(cache.get('/api/expenses', 60_000)).toEqual({ items: ['a', 'b'] });
    });

    /**
     * A cached GET emits twice, and a load-more subscriber appends what it gets. Two emissions
     * there mean that every row of that page arrives a second time.
     */
    it('never caches a load-more page, which would append the same rows twice', () => {
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

    /** The list APIs leave `offset` off the first request instead of sending 0. */
    it('treats a missing offset as page one', () => {
      http.get('/api/invoices', { context: listContext(undefined) }).subscribe();
      mock.expectOne('/api/invoices').flush({ items: [], total: 0, offset: 0 });
      expect(cache.size).toBe(1);
    });

    /** A booking that was just created must not be missing from the list that follows it. */
    it('drops the cached page when something is written to the collection', () => {
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

  /**
   * The page paints from the cache and then corrects itself. A caller that takes only the first
   * emission keeps the old answer, which is why this is opt-in per call site.
   */
  it('stores a cached GET and serves it again, then the fresh answer', () => {
    http.get('/api/budgets', { context: cached() }).subscribe();
    mock.expectOne('/api/budgets').flush(['old']);

    const seen: unknown[] = [];
    http.get('/api/budgets', { context: cached() }).subscribe((b) => seen.push(b));
    expect(seen).toEqual([['old']]);

    mock.expectOne('/api/budgets').flush(['new']);
    expect(seen).toEqual([['old'], ['new']]);
  });

  /**
   * The stream uses `concat`, not `merge`, because the subscriber must have something to paint
   * before anything else happens, whatever the network does.
   */
  it('serves the cached value BEFORE the request goes out', () => {
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

  /** A ttl of zero is never served, so there is one emission and it is the fresh one. */
  it('refetches once the entry is past its ttl', () => {
    http.get('/api/budgets', { context: cached(0) }).subscribe();
    mock.expectOne('/api/budgets').flush(['old']);

    const seen: unknown[] = [];
    http.get('/api/budgets', { context: cached(0) }).subscribe((b) => seen.push(b));
    mock.expectOne('/api/budgets').flush(['new']);
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

    /** A cost centre that was just created must not be missing from the list that follows. */
    it('a mutation under the same collection drops it', () => {
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

    /**
     * A request that errors may still have changed something. A stale list after a half-failed
     * write is worse than one extra fetch.
     */
    it('invalidates even when the mutation fails', () => {
      http.post('/api/budgets', {}).subscribe({ error: () => undefined });
      expect(cache.size).toBe(0);
      mock.expectOne('/api/budgets').flush(null, { status: 500, statusText: 'x' });
    });
  });
});
