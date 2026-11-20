import {
  DestroyRef,
  ElementRef,
  InjectionToken,
  Injector,
  type Provider,
  effect,
  inject,
  runInInjectionContext,
  untracked,
} from '@angular/core';
import { type Observable, type Subscription, finalize } from 'rxjs';
import { quietly } from '@stupa-makers/ui-kit';
import { DETAIL_TTL_MS } from './cache.interceptor';

/** The reads of one list that run at once. */
const READS_AT_ONCE = 4;
/** The rows from the top of a list whose first read runs ahead without a sign of intent. */
const ROWS = 5;

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
  readonly items: () => readonly T[];
  /** The key of a row: one read ahead per key while it is fresh. */
  readonly key: (item: T) => string;
  /**
   * The GETs the detail of a row makes when it opens, as the same service calls. Each one
   * has to use `detailContext()`, else its answer is not kept and the click reads again.
   * The first one paints the head of the detail: it is the one that runs for the top rows
   * without a sign of intent. An empty list reads nothing for that row. It runs in the
   * injection context of the list, so it can `inject()` the services it calls.
   */
  readonly reads: (item: T) => readonly Observable<unknown>[];
  /** Read nothing while this is false (a permission, a phone layout …). */
  readonly when?: () => boolean;
}

/**
 * Read the details of a row ahead when the person shows that they will open it (002000).
 *
 * Call it in the injection context of the list. A sign of intent is a pointer that moves
 * onto the link of a row (mouse), a press on it (finger, pen or mouse) or the focus on it.
 * The link of a row holds the key of the row in its address, so the list needs no extra
 * markup. Then all the reads of that row run, before any other read that waits. Without a
 * sign, only the first read of the top {@link ROWS} rows runs, the one that paints the head
 * of the detail. The reads run {@link READS_AT_ONCE} at a time, quietly (no loading bar), and
 * again when a row comes back after its answer may have gone stale. The answers go into the
 * HTTP cache (`detailContext()`); the detail finds them there and reads again behind them.
 * A failed read is silent: the detail reads on its own when it opens and shows its own error.
 *
 * Reason: a list of 30 rows with 9 reads each sent 270 requests on every open, and they
 * stood in the queue of the one server before the reads of the click.
 *
 * A cached read can end inside `subscribe`, before its subscription is returned.
 */
export function prefetchDetails<T>(spec: DetailPrefetch<T>): void {
  if (!inject(DETAIL_PREFETCH)) return;
  const injector = inject(Injector);
  const host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  const queue: (() => Observable<unknown>)[] = [];
  const running = new Set<Subscription>();
  /** When a row had its first read, and when it had all its reads. */
  const firstAt = new Map<string, number>();
  const allAt = new Map<string, number>();
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

  const fresh = (seen: Map<string, number>, key: string, now: number): boolean => {
    const at = seen.get(key);
    return at !== undefined && now - at < DETAIL_TTL_MS / 2;
  };
  const readsOf = (item: T): readonly Observable<unknown>[] =>
    runInInjectionContext(injector, () => spec.reads(item));

  effect(() => {
    const items = spec.items();
    if (spec.when && !spec.when()) return;
    untracked(() => {
      const now = Date.now();
      items.slice(0, ROWS).forEach((item) => {
        const key = spec.key(item);
        if (fresh(firstAt, key, now) || fresh(allAt, key, now)) return;
        const first = readsOf(item)[0];
        if (!first) return;
        firstAt.set(key, now);
        queue.push(() => first);
      });
      pump();
    });
  });

  const intent = (event: Event): void => {
    if (stopped || (spec.when && !spec.when())) return;
    if (event.type === 'pointerover' && (event as PointerEvent).pointerType !== 'mouse') return;
    const link = (event.target as Element).closest('a[href]');
    if (!link) return;
    const path = (link.getAttribute('href') as string).split(/[?#]/)[0];
    const item = untracked(spec.items).find((i) => path.split('/').includes(spec.key(i)));
    if (item === undefined) return;
    const key = spec.key(item);
    const now = Date.now();
    if (fresh(allAt, key, now)) return;
    allAt.set(key, now);
    const reads = readsOf(item);
    const rest = fresh(firstAt, key, now) ? reads.slice(1) : reads;
    queue.unshift(...rest.map((read) => () => read));
    pump();
  };
  const events = ['pointerover', 'pointerdown', 'focusin'] as const;
  events.forEach((type) => host.addEventListener(type, intent, { passive: true }));

  inject(DestroyRef).onDestroy(() => {
    stopped = true;
    queue.length = 0;
    events.forEach((type) => host.removeEventListener(type, intent));
    for (const sub of running) sub.unsubscribe();
    running.clear();
  });
}
