import {
  DestroyRef,
  InjectionToken,
  Injector,
  type Provider,
  effect,
  inject,
  runInInjectionContext,
  untracked,
} from '@angular/core';
import { type Observable, type Subscription, finalize } from 'rxjs';
import { quietly } from '@core/loading/loading.interceptor';
import { DETAIL_TTL_MS } from './cache.interceptor';

/** The reads of one list that run at once. */
const READS_AT_ONCE = 4;
/** The rows from the top of a list that are read ahead. */
const ROWS = 30;

/**
 * Lists read ahead only where this is true. The app turns it on (`provideDetailPrefetch`
 * in `app.config.ts`); a spec turns it on when it tests the read ahead, so the specs of a
 * page count only the reads of the page.
 */
export const DETAIL_PREFETCH = new InjectionToken<boolean>('DETAIL_PREFETCH', { factory: () => false });

export function provideDetailPrefetch(): Provider {
  return { provide: DETAIL_PREFETCH, useValue: true };
}

/** What a list reads ahead for the rows it shows. */
export interface DetailPrefetch<T> {
  /** The rows the list shows, in order. */
  items: () => readonly T[];
  /** The key of a row: one read ahead per key while it is fresh. */
  key: (item: T) => string;
  /**
   * The GETs the detail of a row makes when it opens, as the same service calls. Each one
   * has to use `detailContext()`, else its answer is not kept and the click reads again.
   * An empty list reads nothing for that row. It runs in the injection context of the
   * list, so it can `inject()` the services it calls.
   */
  reads: (item: T) => readonly Observable<unknown>[];
  /** Read nothing while this is false (a permission, a phone layout …). */
  when?: () => boolean;
}

/**
 * Read the details of the rows a list shows ahead, so a click paints the detail at once.
 *
 * Call it in the injection context of the list. It reads the top {@link ROWS} rows,
 * {@link READS_AT_ONCE} reads at a time, quietly (no loading bar), and again when a row
 * comes back after its answer may have gone stale. The answers go into the HTTP cache
 * (`detailContext()`); the detail finds them there and reads again behind them. A failed
 * read is silent: the detail reads on its own when it opens and shows its own error.
 *
 * A cached read can end inside `subscribe`, before its subscription is returned.
 */
export function prefetchDetails<T>(spec: DetailPrefetch<T>): void {
  if (!inject(DETAIL_PREFETCH)) return;
  const injector = inject(Injector);
  const queue: (() => Observable<unknown>)[] = [];
  const running = new Set<Subscription>();
  const readAt = new Map<string, number>();
  let stopped = false;

  const pump = (): void => {
    while (!stopped && running.size < READS_AT_ONCE && queue.length) {
      const read = (queue.shift() as () => Observable<unknown>)();
      const slot: { sub?: Subscription; done?: boolean } = {};
      slot.sub = quietly(() =>
        read
          .pipe(
            finalize(() => {
              slot.done = true;
              if (slot.sub) running.delete(slot.sub);
              queueMicrotask(pump);
            }),
          )
          .subscribe({ error: () => undefined }),
      );
      if (!slot.done) running.add(slot.sub);
    }
  };

  effect(() => {
    const items = spec.items();
    if (spec.when && !spec.when()) return;
    untracked(() => {
      const now = Date.now();
      for (const item of items.slice(0, ROWS)) {
        const key = spec.key(item);
        const at = readAt.get(key);
        if (at !== undefined && now - at < DETAIL_TTL_MS / 2) continue;
        readAt.set(key, now);
        for (const read of runInInjectionContext(injector, () => spec.reads(item))) queue.push(() => read);
      }
      pump();
    });
  });

  inject(DestroyRef).onDestroy(() => {
    stopped = true;
    queue.length = 0;
    for (const sub of running) sub.unsubscribe();
    running.clear();
  });
}
