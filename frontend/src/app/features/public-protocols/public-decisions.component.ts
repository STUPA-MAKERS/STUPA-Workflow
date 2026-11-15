import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  DateBlockComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  HighlightComponent,
  IconComponent,
  liveSearch,
  NoteComponent,
  SearchPillComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import { parseDay, weekdayDate } from '@shared/date-format';
import type {
  PublicDecisionRow,
  PublicGremium,
  PublicSemester,
} from './public-protocols.models';
import { PublicProtocolsService } from './public-protocols.service';
import {
  optionKey,
  orderedCounts,
  resultKey,
  semesterLabel,
  useNoindex,
} from './public-protocols.util';

/** The size of one page of the list. */
export const PAGE_SIZE = 20;
/** The time after the last key press until the search runs, in ms. */
export const SEARCH_DEBOUNCE = 300;

/** The decisions of one semester. */
interface SemesterGroup {
  readonly key: string;
  readonly label: string;
  readonly items: readonly PublicDecisionRow[];
}

/**
 * "Beschlüsse" (`/decisions`, no login, spec 000926): the decisions of the gremien that
 * publish their protocols, newest first and grouped by semester.
 *
 * A motion shows its question, its date, the title of its meeting, its result and the
 * sums of the votes. An election shows its question and its date only. No row names a
 * person. The search (the question), the Gremium chip and the Semester chip filter on
 * the server. The page is `noindex`.
 */
@Component({
  selector: 'app-public-decisions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    HighlightComponent,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    DateBlockComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    NoteComponent,
    SearchPillComponent,
    SkeletonComponent,
  ],
  templateUrl: './public-decisions.component.html',
  styleUrl: './public-decisions.component.scss',
})
export class PublicDecisionsComponent {
  private readonly api = inject(PublicProtocolsService);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);

  /** The search text of the loaded list. */
  protected readonly appliedQuery = signal('');
  protected readonly search = liveSearch<never>({
    minLength: 1,
    debounceMs: SEARCH_DEBOUNCE,
    run: (q) => {
      this.appliedQuery.set(q);
      this.reload();
    },
  });
  protected readonly gremiumFilter = signal<readonly string[]>(
    this.route.snapshot.queryParamMap.getAll('committee'),
  );
  protected readonly semesterFilter = signal('');

  protected readonly gremien = signal<PublicGremium[]>([]);
  protected readonly semesters = signal<PublicSemester[]>([]);
  protected readonly items = signal<readonly PublicDecisionRow[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(true);
  protected readonly loadingMore = signal(false);
  protected readonly error = signal(false);

  private seq = 0;

  protected readonly hasFilters = computed(
    () =>
      this.gremiumFilter().length > 0 || this.semesterFilter() !== '' || this.appliedQuery() !== '',
  );
  protected readonly hasMore = computed(() => this.items().length < this.total());

  protected readonly gremiumOptions = computed<FilterSelectOption[]>(() =>
    this.gremien().map((g) => ({ value: g.id, label: g.name })),
  );
  /** The chip text: "Gremium", the one name, or "2 Gremien". */
  protected readonly gremiumText = computed(() => {
    const ids = this.gremiumFilter();
    if (ids.length === 0) return null;
    const label = this.i18n.translate('publicProtocols.filter.gremium');
    const hit = ids.length === 1 ? this.gremien().find((g) => g.id === ids[0]) : undefined;
    const value = hit
      ? hit.name
      : this.i18n.translate('publicProtocols.filter.gremienN', { n: ids.length });
    return `${label}: ${value}`;
  });
  protected readonly semesterOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('publicProtocols.filter.all') },
    ...this.semesters().map((s) => ({ value: s.key, label: this.semesterName(s.key) })),
  ]);
  protected readonly semesterText = computed(() =>
    this.semesterFilter()
      ? `${this.i18n.translate('publicProtocols.filter.semester')}: ${this.semesterName(this.semesterFilter())}`
      : null,
  );

  /** The loaded decisions by semester, in the order of the list. */
  protected readonly groups = computed<readonly SemesterGroup[]>(() => {
    const items = this.items();
    const keys = [...new Set(items.map((d) => d.semester))];
    return keys.map((key) => ({
      key,
      label: this.semesterName(key),
      items: items.filter((d) => d.semester === key),
    }));
  });

  constructor() {
    useNoindex();
    this.api.gremien().subscribe({
      next: (rows) => this.gremien.set(rows),
      error: () => this.gremien.set([]),
    });
    this.reload();
  }

  protected semesterName(key: string): string {
    return semesterLabel(key, (k, p) => this.i18n.translate(k, p));
  }

  protected onGremien(ids: readonly string[]): void {
    this.gremiumFilter.set(ids);
    this.reload();
  }

  protected onSemester(key: string): void {
    this.semesterFilter.set(key);
    this.reload(false);
  }

  protected resetFilters(): void {
    this.search.sync('');
    this.appliedQuery.set('');
    this.gremiumFilter.set([]);
    this.semesterFilter.set('');
    this.reload();
  }

  protected loadMore(): void {
    if (this.loadingMore()) return;
    const seq = this.seq;
    this.loadingMore.set(true);
    this.api.decisions({ ...this.filters(), offset: this.items().length }).subscribe({
      next: (page) => {
        if (seq !== this.seq) return;
        this.loadingMore.set(false);
        this.items.update((rows) => [...rows, ...page.items]);
        this.total.set(page.total);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.loadingMore.set(false);
        this.error.set(true);
      },
    });
  }

  /** Load the first page again; `withSemesters` also reloads the semester options. */
  private reload(withSemesters = true): void {
    this.seq += 1;
    const seq = this.seq;
    this.loading.set(true);
    this.loadingMore.set(false);
    this.error.set(false);
    const filters = this.filters();
    this.api.decisions(filters).subscribe({
      next: (page) => {
        if (seq !== this.seq) return;
        this.items.set(page.items);
        this.total.set(page.total);
        this.loading.set(false);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.items.set([]);
        this.total.set(0);
        this.loading.set(false);
        this.error.set(true);
      },
    });
    if (withSemesters) {
      this.api.semesters({ gremium: filters.gremium }).subscribe({
        next: (rows) => {
          if (seq === this.seq) this.semesters.set(rows);
        },
        error: () => {
          if (seq === this.seq) this.semesters.set([]);
        },
      });
    }
  }

  private filters() {
    return {
      gremium: this.gremiumFilter(),
      semester: this.semesterFilter(),
      q: this.appliedQuery(),
      limit: PAGE_SIZE,
    };
  }

  protected dateOf(d: PublicDecisionRow): Date | null {
    return parseDay(d.date);
  }

  /** "Studierendenparlament · Di, 29.09.2026 · 34. Sitzung"; an election has no meeting title. */
  protected meta(d: PublicDecisionRow): readonly string[] {
    const when = weekdayDate(d.date, this.i18n.formatLocale());
    return [d.gremium.name, when, ...(d.meetingTitle ? [d.meetingTitle] : [])];
  }

  protected question(d: PublicDecisionRow): string {
    return d.question?.trim() || this.i18n.translate('publicDecisions.noQuestion');
  }

  protected resultLabel(d: PublicDecisionRow): TranslationKey | null {
    return d.result ? resultKey(d.result) : null;
  }

  protected isYes(d: PublicDecisionRow): boolean {
    return d.result === 'passed' || d.result === 'elected';
  }

  /** "Ja 5", "Nein 1", "Enthaltung 0". */
  protected counts(d: PublicDecisionRow): readonly string[] {
    return orderedCounts(d.counts).map(({ option, count }) => {
      const key = optionKey(option);
      return `${key ? this.i18n.translate(key) : option} ${count}`;
    });
  }
}
