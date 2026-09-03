import { Injectable } from '@angular/core';

/** One cached response, with the time it arrived. */
interface Entry {
  body: unknown;
  at: number;
}

/**
 * Cache of GET responses for reference data that many pages need.
 *
 * Deliberately small and explicit. It caches only what a call site opts in to, because a
 * cache that guesses is a cache that serves a stale answer to a question nobody thought
 * about. Two rules keep it honest:
 *
 * 1. **A mutation drops what it could have changed.** Any non-GET invalidates every entry
 *    whose key starts with the same collection path. That is coarse on purpose: being too
 *    eager costs one request, being too clever costs a wrong list.
 * 2. **A sign-out clears everything.** Cached data is scoped to whoever asked for it, and
 *    the next person at the same browser must not inherit it.
 */
@Injectable({ providedIn: 'root' })
export class HttpCacheService {
  private readonly entries = new Map<string, Entry>();

  /** Read a fresh entry, or `undefined` when it is missing or older than `ttlMs`. */
  get(key: string, ttlMs: number, now = Date.now()): unknown | undefined {
    const hit = this.entries.get(key);
    if (!hit) return undefined;
    if (now - hit.at > ttlMs) {
      // Drop it rather than keep it around: a stale entry that will never be served is
      // just memory, and leaving it makes `size` lie about what the cache holds.
      this.entries.delete(key);
      return undefined;
    }
    return hit.body;
  }

  set(key: string, body: unknown, now = Date.now()): void {
    this.entries.set(key, { body, at: now });
  }

  /**
   * Drop every entry that a write to `path` could have changed.
   *
   * The match is SYMMETRIC, and it has to be. A write to `/api/budgets` must drop the
   * cached `/api/budgets?gremium=x` below it, and a write to `/api/budgets/b1` must drop
   * the cached `/api/budgets` collection above it — the edited node is in that list. A
   * one-directional prefix check handles only the first case and silently keeps a list
   * that no longer matches the data.
   *
   * The boundary is a path SEGMENT, not a string prefix: `/api/budgets` must not clear
   * `/api/budget-transfers` just because the names start the same way.
   */
  invalidate(path: string): void {
    for (const key of [...this.entries.keys()]) {
      const [keyPath] = key.split('?');
      const related =
        keyPath === path ||
        keyPath.startsWith(`${path}/`) ||
        path.startsWith(`${keyPath}/`);
      if (related) this.entries.delete(key);
    }
  }

  /** Forget everything. Called on sign-out. */
  clear(): void {
    this.entries.clear();
  }

  /** For tests and for a diagnostic; not part of the caching contract. */
  get size(): number {
    return this.entries.size;
  }
}
