import { computed, inject, signal, type Signal, type WritableSignal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import type { Observable } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { type FilterSelectOption, liveSearch } from '@stupa-makers/ui-kit';
import type { PublicGremium, PublicProtocolQuery, PublicSemester } from './public-protocols.models';
import { PublicProtocolsService } from './public-protocols.service';
import { semesterLabel } from './public-protocols.util';

/** The size of one page of a public list. */
export const PAGE_SIZE = 20;
/** The time after the last key press until the search runs, in ms. */
export const SEARCH_DEBOUNCE = 300;

/** One page of a public list, as the server gives it. */
interface Page<T> {
  readonly items: readonly T[];
  readonly total: number;
}

/** The filters of a public list, as the server takes them. */
export type PublicListFilters = Required<Pick<PublicProtocolQuery, 'gremium' | 'semester' | 'q' | 'limit'>>;

/** The rows of one semester. */
export interface SemesterRows<T> {
  readonly key: string;
  readonly label: string;
  readonly items: readonly T[];
}

/** The state and the actions of a public list ("Protokolle", "Beschlüsse"). */
export interface PublicList<T> {
  /** The search text of the loaded list. */
  readonly appliedQuery: WritableSignal<string>;
  /** The search field: from the first character, Enter searches at once. */
  readonly search: ReturnType<typeof liveSearch<never>>;
  /** The Gremium of the page (`:committee` of the route), once the Gremien are read. */
  readonly gremium: Signal<PublicGremium | null>;
  /** True when the slug of the page names no public Gremium (spec 002403). */
  readonly unknown: Signal<boolean>;
  readonly semesterFilter: WritableSignal<string>;
  readonly gremien: WritableSignal<readonly PublicGremium[]>;
  readonly semesters: WritableSignal<readonly PublicSemester[]>;
  readonly items: WritableSignal<readonly T[]>;
  readonly total: WritableSignal<number>;
  readonly loading: WritableSignal<boolean>;
  readonly loadingMore: WritableSignal<boolean>;
  readonly error: WritableSignal<boolean>;
  readonly hasFilters: Signal<boolean>;
  readonly hasMore: Signal<boolean>;
  readonly semesterOptions: Signal<readonly FilterSelectOption[]>;
  readonly semesterText: Signal<string | null>;
  /** The loaded rows by semester, in the order of the list. */
  readonly groups: Signal<readonly SemesterRows<T>[]>;
  semesterName(key: string): string;
  onSemester(key: string): void;
  resetFilters(): void;
  loadMore(): void;
}

/**
 * The list logic that the Gremium pages of "Protokolle" and "Beschlüsse" share (specs 002400,
 * 002401): the search, the Semester chip, the pages and the groups by semester. Call it in an
 * injection context. It reads the Gremien first, finds the Gremium of the slug `:committee`
 * of the route and then reads its first page. A slug that names no public Gremium reads no
 * page and sets `unknown`.
 *
 * A newer read wins over an older answer (`newest`).
 *
 * `load` reads one page. `semesterQuery` gives the filters of the semester options.
 */
export function publicList<T extends { readonly semester: string }>(cfg: {
  readonly load: (query: PublicProtocolQuery) => Observable<Page<T>>;
  readonly semesterQuery: (filters: PublicListFilters) => PublicProtocolQuery;
}): PublicList<T> {
  const api = inject(PublicProtocolsService);
  const i18n = inject(I18nService);
  const route = inject(ActivatedRoute);

  const appliedQuery = signal('');
  const slug = route.snapshot.paramMap.get('committee') ?? '';
  const gremium = signal<PublicGremium | null>(null);
  const unknown = signal(false);
  const semesterFilter = signal('');
  const gremien = signal<PublicGremium[]>([]);
  const semesters = signal<PublicSemester[]>([]);
  const items = signal<readonly T[]>([]);
  const total = signal(0);
  const loading = signal(true);
  const loadingMore = signal(false);
  const error = signal(false);
  /** The number of the newest read; an answer of an older read is dropped. */
  const newest = signal(0);

  const filters = (): PublicListFilters => ({
    gremium: [gremium()?.id].filter((id): id is string => id !== undefined),
    semester: semesterFilter(),
    q: appliedQuery(),
    limit: PAGE_SIZE,
  });

  const semesterName = (key: string): string => semesterLabel(key, (k, p) => i18n.translate(k, p));

  /** Load the first page again; `withSemesters` also reloads the semester options. */
  const reload = (withSemesters = true): void => {
    newest.update((n) => n + 1);
    const seq = newest();
    loading.set(true);
    loadingMore.set(false);
    error.set(false);
    const current = filters();
    cfg.load(current).subscribe({
      next: (page) => {
        if (seq !== newest()) return;
        items.set(page.items);
        total.set(page.total);
        loading.set(false);
      },
      error: () => {
        if (seq !== newest()) return;
        items.set([]);
        total.set(0);
        loading.set(false);
        error.set(true);
      },
    });
    if (withSemesters) {
      api.semesters(cfg.semesterQuery(current)).subscribe({
        next: (rows) => {
          if (seq === newest()) semesters.set(rows);
        },
        error: () => {
          if (seq === newest()) semesters.set([]);
        },
      });
    }
  };

  const search = liveSearch<never>({
    minLength: 1,
    debounceMs: SEARCH_DEBOUNCE,
    run: (q) => {
      appliedQuery.set(q);
      reload();
    },
  });

  api.gremien().subscribe({
    next: (rows) => {
      gremien.set(rows);
      const hit = rows.find((g) => g.slug === slug) ?? null;
      gremium.set(hit);
      if (hit) {
        reload();
      } else {
        unknown.set(true);
        loading.set(false);
      }
    },
    error: () => {
      gremien.set([]);
      loading.set(false);
      error.set(true);
    },
  });

  return {
    appliedQuery,
    search,
    gremium,
    unknown,
    semesterFilter,
    gremien,
    semesters,
    items,
    total,
    loading,
    loadingMore,
    error,
    hasFilters: computed(
      () => semesterFilter() !== '' || appliedQuery() !== '',
    ),
    hasMore: computed(() => items().length < total()),
    semesterOptions: computed(() => [
      { value: '', label: i18n.translate('publicProtocols.filter.all') },
      ...semesters().map((s) => ({ value: s.key, label: semesterName(s.key) })),
    ]),
    semesterText: computed(() =>
      semesterFilter()
        ? `${i18n.translate('publicProtocols.filter.semester')}: ${semesterName(semesterFilter())}`
        : null,
    ),
    groups: computed(() => {
      const rows = items();
      return [...new Set(rows.map((row) => row.semester))].map((key) => ({
        key,
        label: semesterName(key),
        items: rows.filter((row) => row.semester === key),
      }));
    }),
    semesterName,
    onSemester: (key) => {
      semesterFilter.set(key);
      reload(false);
    },
    resetFilters: () => {
      search.sync('');
      appliedQuery.set('');
      semesterFilter.set('');
      reload();
    },
    loadMore: () => {
      if (loadingMore()) return;
      const seq = newest();
      loadingMore.set(true);
      error.set(false);
      cfg.load({ ...filters(), offset: items().length }).subscribe({
        next: (page) => {
          if (seq !== newest()) return;
          loadingMore.set(false);
          items.update((rows) => [...rows, ...page.items]);
          total.set(page.total);
        },
        error: () => {
          if (seq !== newest()) return;
          loadingMore.set(false);
          error.set(true);
        },
      });
    },
  };
}
