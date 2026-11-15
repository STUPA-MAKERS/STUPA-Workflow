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

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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
  readonly gremiumFilter: WritableSignal<readonly string[]>;
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
  readonly gremiumOptions: Signal<readonly FilterSelectOption[]>;
  /** The chip text: "Gremium", the one name, or "2 Gremien". */
  readonly gremiumText: Signal<string | null>;
  readonly semesterOptions: Signal<readonly FilterSelectOption[]>;
  readonly semesterText: Signal<string | null>;
  /** The loaded rows by semester, in the order of the list. */
  readonly groups: Signal<readonly SemesterRows<T>[]>;
  semesterName(key: string): string;
  onGremien(ids: readonly string[]): void;
  onSemester(key: string): void;
  resetFilters(): void;
  loadMore(): void;
}

/**
 * The list logic that "Protokolle" and "Beschlüsse" share: the search, the Gremium chip
 * (`?committee=`), the Semester chip, the pages and the groups by semester. Call it in an
 * injection context; it reads the Gremien and the first page at once.
 *
 * - With `checkCommittee`, a value of `?committee=` that is no id is dropped, so it gives no
 *   error of the server, and a Gremium of the filter that is not public is dropped too: it gives
 *   no row. Without it the filter keeps each value of the link, and the chip counts it.
 * - A newer read wins over an older answer (`newest`).
 *
 * `load` reads one page. `semesterQuery` gives the filters of the semester options.
 */
export function publicList<T extends { readonly semester: string }>(cfg: {
  readonly load: (query: PublicProtocolQuery) => Observable<Page<T>>;
  readonly semesterQuery: (filters: PublicListFilters) => PublicProtocolQuery;
  readonly checkCommittee: boolean;
}): PublicList<T> {
  const api = inject(PublicProtocolsService);
  const i18n = inject(I18nService);
  const route = inject(ActivatedRoute);

  const appliedQuery = signal('');
  const gremiumFilter = signal<readonly string[]>(
    route.snapshot.queryParamMap.getAll('committee').filter((id) => !cfg.checkCommittee || UUID.test(id)),
  );
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
    gremium: gremiumFilter(),
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

  const onGremien = (ids: readonly string[]): void => {
    gremiumFilter.set(ids);
    reload();
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
      const kept = gremiumFilter().filter((id) => rows.some((g) => g.id === id));
      if (cfg.checkCommittee && kept.length !== gremiumFilter().length) onGremien(kept);
    },
    error: () => gremien.set([]),
  });
  reload();

  return {
    appliedQuery,
    search,
    gremiumFilter,
    semesterFilter,
    gremien,
    semesters,
    items,
    total,
    loading,
    loadingMore,
    error,
    hasFilters: computed(
      () => gremiumFilter().length > 0 || semesterFilter() !== '' || appliedQuery() !== '',
    ),
    hasMore: computed(() => items().length < total()),
    gremiumOptions: computed(() => gremien().map((g) => ({ value: g.id, label: g.name }))),
    gremiumText: computed(() => {
      const ids = gremiumFilter();
      if (ids.length === 0) return null;
      const label = i18n.translate('publicProtocols.filter.gremium');
      const hit = ids.length === 1 ? gremien().find((g) => g.id === ids[0]) : undefined;
      const value = hit ? hit.name : i18n.translate('publicProtocols.filter.gremienN', { n: ids.length });
      return `${label}: ${value}`;
    }),
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
    onGremien,
    onSemester: (key) => {
      semesterFilter.set(key);
      reload(false);
    },
    resetFilters: () => {
      search.sync('');
      appliedQuery.set('');
      gremiumFilter.set([]);
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
