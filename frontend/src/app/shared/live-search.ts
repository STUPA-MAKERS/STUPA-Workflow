import { DestroyRef, inject, signal, type Signal } from '@angular/core';
import {
  EMPTY,
  Subject,
  catchError,
  map,
  of,
  switchMap,
  timer,
  type Observable,
} from 'rxjs';

/** How long the search waits after the last key press before it runs. */
export const LIVE_SEARCH_DEBOUNCE_MS = 250;

/** A server-side search runs from this length on. A shorter text counts as empty. */
export const LIVE_SEARCH_MIN_LENGTH = 2;

export interface LiveSearchOptions<T> {
  /**
   * Run the search for the trimmed query. Return the request: a new query cancels the
   * request that is still out (`switchMap`), so a late answer to "ab" never replaces
   * the answer to "abcd". Return nothing for a search without a request, for example a
   * write to the query params of the URL.
   *
   * Without `reset`, a query below `minLength` runs as `''`, without the debounce.
   */
  run: (query: string) => Observable<T> | void;
  /** Receives each answer of `run`. */
  result?: (value: T, query: string) => void;
  /**
   * The query became empty or shorter than `minLength`. It runs at once, without the
   * debounce, and replaces `run('')`.
   */
  reset?: () => void;
  /** The request failed. The next key press searches again. */
  error?: (err: unknown, query: string) => void;
  /** Default {@link LIVE_SEARCH_MIN_LENGTH}. 0 or 1 searches from the first character. */
  minLength?: number;
  /** Default {@link LIVE_SEARCH_DEBOUNCE_MS}. */
  debounceMs?: number;
}

/** The search behind one search field. Make it with {@link liveSearch}. */
export interface LiveSearch {
  /** The text in the field. It runs ahead of `applied` while the debounce waits. */
  readonly text: Signal<string>;
  /**
   * The query of the last result on screen: trimmed, and `''` below `minLength` or
   * after a reset. Pages use it for "Keine Treffer" and for a search mode.
   */
  readonly applied: Signal<string>;
  /** True while the debounce waits or the request is out. Show it subtly, if at all. */
  readonly pending: Signal<boolean>;
  /** The field changed. Bind it to the `valueChange` of the field. */
  set(value: string): void;
  /** Search the current text now, without the debounce (for example on Enter). */
  flush(): void;
  /** Empty the field and reset at once (Escape or ×). */
  clear(): void;
  /**
   * Put a text into the field from outside (the URL, a picked row) without a search.
   * It cancels a search that waits or runs.
   */
  sync(value: string): void;
  /** Run the current text again now, also when it did not change (a filter changed). */
  refresh(): void;
}

type Command =
  | { kind: 'input'; text: string; now: boolean; force: boolean }
  | { kind: 'sync'; text: string };

/**
 * The one mechanism behind every search field of the app: the field searches while
 * the user types, there is no "Suchen" button.
 *
 * - debounce (~250 ms), and a new query cancels the request that is still out;
 * - a query below `minLength` (default 2) counts as empty: an empty field resets at
 *   once, a single character sends no request;
 * - the same query as on screen sends no second request.
 *
 * Call it in an injection context (a field initializer or the constructor). The search
 * stops when the injector is destroyed.
 */
export function liveSearch<T>(options: LiveSearchOptions<T>): LiveSearch {
  const minLength = options.minLength ?? LIVE_SEARCH_MIN_LENGTH;
  const debounceMs = options.debounceMs ?? LIVE_SEARCH_DEBOUNCE_MS;

  const text = signal('');
  const applied = signal('');
  const pending = signal(false);
  const commands = new Subject<Command>();

  /** The query that a text stands for: trimmed, and '' below the minimum. */
  const effective = (value: string): string => {
    const q = value.trim();
    return q.length < minLength ? '' : q;
  };

  const settle = (q: string): void => {
    applied.set(q);
    pending.set(false);
  };

  const sub = commands
    .pipe(
      switchMap((cmd): Observable<{ value: T; q: string }> => {
        if (cmd.kind === 'sync') {
          settle(effective(cmd.text));
          return EMPTY;
        }
        const q = effective(cmd.text);
        if (!cmd.force && q === applied()) {
          // Back to what is on screen: the answer is already there.
          pending.set(false);
          return EMPTY;
        }
        if (q === '' && options.reset) {
          settle('');
          options.reset();
          return EMPTY;
        }
        pending.set(true);
        // An empty query (the full list) does not wait: the reader cleared the field.
        const start = cmd.now || q === '' ? of(0) : timer(debounceMs);
        return start.pipe(
          switchMap(() => {
            const request = options.run(q);
            if (!request) {
              settle(q);
              return EMPTY;
            }
            return request.pipe(
              map((value) => ({ value, q })),
              catchError((err: unknown) => {
                pending.set(false);
                options.error?.(err, q);
                return EMPTY;
              }),
            );
          }),
        );
      }),
    )
    .subscribe(({ value, q }) => {
      settle(q);
      options.result?.(value, q);
    });
  inject(DestroyRef).onDestroy(() => sub.unsubscribe());

  return {
    text: text.asReadonly(),
    applied: applied.asReadonly(),
    pending: pending.asReadonly(),
    set(value: string): void {
      text.set(value);
      commands.next({ kind: 'input', text: value, now: false, force: false });
    },
    flush(): void {
      commands.next({ kind: 'input', text: text(), now: true, force: false });
    },
    clear(): void {
      text.set('');
      commands.next({ kind: 'input', text: '', now: true, force: false });
    },
    sync(value: string): void {
      text.set(value);
      commands.next({ kind: 'sync', text: value });
    },
    refresh(): void {
      commands.next({ kind: 'input', text: text(), now: true, force: true });
    },
  };
}
