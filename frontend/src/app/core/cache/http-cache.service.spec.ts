import { HttpCacheService } from './http-cache.service';

describe('HttpCacheService', () => {
  let cache: HttpCacheService;
  beforeEach(() => (cache = new HttpCacheService()));

  it('serves what it stored', () => {
    cache.set('/api/budgets', [1, 2], 1_000);
    expect(cache.get('/api/budgets', 60_000, 1_500)).toEqual([1, 2]);
  });

  it('misses on an unknown key', () => {
    expect(cache.get('/api/budgets', 60_000)).toBeUndefined();
  });

  it('misses once the entry is older than the ttl, and forgets it', () => {
    // Keeping an entry that will never be served again is just memory, and it makes
    // `size` lie about what the cache holds.
    cache.set('/api/budgets', [1], 0);
    expect(cache.get('/api/budgets', 1_000, 1_001)).toBeUndefined();
    expect(cache.size).toBe(0);
  });

  it('serves an entry that is exactly at the ttl boundary', () => {
    cache.set('/api/budgets', [1], 0);
    expect(cache.get('/api/budgets', 1_000, 1_000)).toEqual([1]);
  });

  describe('invalidate', () => {
    beforeEach(() => {
      cache.set('/api/budgets', 'tree');
      cache.set('/api/budgets?gremium=g1', 'scoped');
      cache.set('/api/budgets/b1/fiscal-years', 'years');
      cache.set('/api/budget-transfers', 'transfers');
      cache.set('/api/applications', 'apps');
    });

    it('drops the collection and everything under it, query strings included', () => {
      cache.invalidate('/api/budgets');
      expect(cache.get('/api/budgets', 60_000)).toBeUndefined();
      expect(cache.get('/api/budgets?gremium=g1', 60_000)).toBeUndefined();
      expect(cache.get('/api/budgets/b1/fiscal-years', 60_000)).toBeUndefined();
    });

    it('stops at a path segment, so one collection cannot clear another', () => {
      // A plain string prefix would take `/api/budget-transfers` with `/api/budgets`
      // out — no, worse: `/api/budget` would take BOTH. The boundary is a segment.
      cache.invalidate('/api/budgets');
      expect(cache.get('/api/budget-transfers', 60_000)).toBe('transfers');
      expect(cache.get('/api/applications', 60_000)).toBe('apps');
    });

    it('does nothing for a collection it holds nothing for', () => {
      cache.invalidate('/api/invoices');
      expect(cache.size).toBe(5);
    });
  });

  it('forgets everything on clear, because the next user is not this one', () => {
    cache.set('/api/budgets', 'tree');
    cache.set('/api/applications', 'apps');
    cache.clear();
    expect(cache.size).toBe(0);
  });
});
