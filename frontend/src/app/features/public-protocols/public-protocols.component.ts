import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { DateBlockComponent } from '@shared/ui/date-block/date-block.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { formatSize } from '../apply/apply.util';
import { highlight, type TextPart } from '../search/highlight';
import type {
  PublicGremium,
  PublicProtocolSummary,
  PublicSemester,
  PublicVoteResult,
} from './public-protocols.models';
import { PublicProtocolsService } from './public-protocols.service';
import {
  longDate,
  meetingDate,
  resultKey,
  semesterLabel,
  shortDate,
  topCounts,
  useNoindex,
} from './public-protocols.util';

/** The size of one page of the list. */
export const PAGE_SIZE = 20;
/** The time after the last key press until the search runs, in ms. */
export const SEARCH_DEBOUNCE = 300;

/** The protocols of one semester. */
interface SemesterGroup {
  key: string;
  label: string;
  /** The number of protocols of the semester under the current filters. */
  count: number;
  items: PublicProtocolSummary[];
}

/**
 * "Öffentliche Protokolle" (`/protokolle`, no login): the final protocols of the gremien
 * that publish them, in their public version, newest first and grouped by semester.
 *
 * The search (meeting title and the text of the public agenda items), the Gremium chip
 * (several gremien) and the Semester chip filter on the server. "Weitere Protokolle
 * laden" appends the next page. The page is `noindex`.
 */
@Component({
  selector: 'app-public-protocols',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
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
  templateUrl: './public-protocols.component.html',
  styleUrl: './public-protocols.component.scss',
})
export class PublicProtocolsComponent {
  private readonly api = inject(PublicProtocolsService);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);

  /** The text in the search field. */
  protected readonly query = signal('');
  /** The search text of the loaded list. */
  protected readonly appliedQuery = signal('');
  protected readonly gremiumFilter = signal<readonly string[]>(
    this.route.snapshot.queryParamMap.getAll('gremium'),
  );
  protected readonly semesterFilter = signal('');

  protected readonly gremien = signal<PublicGremium[]>([]);
  protected readonly semesters = signal<PublicSemester[]>([]);
  protected readonly items = signal<PublicProtocolSummary[]>([]);
  protected readonly total = signal(0);
  protected readonly loading = signal(true);
  protected readonly loadingMore = signal(false);
  protected readonly error = signal(false);

  private seq = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  protected readonly hasFilters = computed(
    () =>
      this.gremiumFilter().length > 0 || this.semesterFilter() !== '' || this.appliedQuery() !== '',
  );
  protected readonly hasMore = computed(() => this.items().length < this.total());

  protected readonly countText = computed(() =>
    this.i18n.translate(
      this.appliedQuery() ? 'publicProtocols.list.hits' : 'publicProtocols.list.count',
      { n: this.total() },
    ),
  );

  protected readonly gremiumOptions = computed<FilterSelectOption[]>(() =>
    this.gremien().map((g) => ({ value: g.id, label: g.name })),
  );
  /** The chip text: "Gremium", the one name, or "2 Gremien". */
  protected readonly gremiumText = computed(() => {
    const ids = this.gremiumFilter();
    if (ids.length === 0) return null;
    if (ids.length === 1) {
      const hit = this.gremien().find((g) => g.id === ids[0]);
      if (hit) return `${this.i18n.translate('publicProtocols.filter.gremium')}: ${hit.name}`;
    }
    return `${this.i18n.translate('publicProtocols.filter.gremium')}: ${this.i18n.translate(
      'publicProtocols.filter.gremienN',
      { n: ids.length },
    )}`;
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

  /** The loaded protocols by semester, in the order of the list. */
  protected readonly groups = computed<SemesterGroup[]>(() => {
    const counts = new Map(this.semesters().map((s) => [s.key, s.count]));
    const groups: SemesterGroup[] = [];
    for (const p of this.items()) {
      let group = groups.find((g) => g.key === p.semester);
      if (!group) {
        group = { key: p.semester, label: this.semesterName(p.semester), count: 0, items: [] };
        groups.push(group);
      }
      group.items.push(p);
    }
    for (const g of groups) g.count = counts.get(g.key) ?? g.items.length;
    return groups;
  });

  constructor() {
    useNoindex();
    inject(DestroyRef).onDestroy(() => this.clearTimer());
    this.api.gremien().subscribe({
      next: (rows) => this.gremien.set(rows),
      error: () => this.gremien.set([]),
    });
    this.reload();
  }

  protected semesterName(key: string): string {
    return semesterLabel(key, (k, p) => this.i18n.translate(k, p));
  }

  protected onQuery(value: string): void {
    this.query.set(value);
    this.clearTimer();
    this.timer = setTimeout(() => this.applyQuery(), SEARCH_DEBOUNCE);
  }

  /** Enter in the field: search now. */
  protected applyQuery(): void {
    this.clearTimer();
    const q = this.query().trim();
    if (q === this.appliedQuery()) return;
    this.appliedQuery.set(q);
    this.reload();
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
    this.clearTimer();
    this.query.set('');
    this.appliedQuery.set('');
    this.gremiumFilter.set([]);
    this.semesterFilter.set('');
    this.reload();
  }

  protected loadMore(): void {
    if (this.loadingMore()) return;
    const seq = this.seq;
    this.loadingMore.set(true);
    this.api.list({ ...this.filters(), offset: this.items().length }).subscribe({
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

  /** Load the first page again; `withSemesters` also reloads the semester counts. */
  private reload(withSemesters = true): void {
    const seq = ++this.seq;
    this.loading.set(true);
    this.loadingMore.set(false);
    this.error.set(false);
    const filters = this.filters();
    this.api.list(filters).subscribe({
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
      this.api.semesters(filters).subscribe({
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

  private clearTimer(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  // Template helpers.

  protected parts(text: string): TextPart[] {
    return highlight(text, this.appliedQuery());
  }

  protected dateOf(p: PublicProtocolSummary): Date {
    return meetingDate(p.date);
  }

  protected when(p: PublicProtocolSummary): string {
    return longDate(p.date, this.i18n.formatLocale());
  }

  protected resultLabel(result: PublicVoteResult): TranslationKey {
    return resultKey(result);
  }

  /** "2 Beschlüsse · 1 nicht-öffentlicher TOP ausgelassen". */
  protected countsLine(p: PublicProtocolSummary): string[] {
    const { decisions, nonPublic } = topCounts(p.tops);
    const parts = [
      decisions === 0
        ? this.i18n.translate('publicProtocols.card.noDecision')
        : this.i18n.translate(
            decisions === 1 ? 'publicProtocols.card.decision' : 'publicProtocols.card.decisions',
            { n: decisions },
          ),
    ];
    if (nonPublic > 0) {
      parts.push(
        this.i18n.translate(
          nonPublic === 1 ? 'publicProtocols.card.skippedOne' : 'publicProtocols.card.skipped',
          { n: nonPublic },
        ),
      );
    }
    return parts;
  }

  /** "PDF · 212 KB · finalisiert 02.10.2026". */
  protected pdfMeta(p: PublicProtocolSummary): string {
    const parts = ['PDF'];
    if (p.pdfSize !== null) parts.push(formatSize(p.pdfSize, this.i18n.formatLocale()));
    const finalized = shortDate(p.finalizedAt, this.i18n.formatLocale());
    if (finalized) {
      parts.push(this.i18n.translate('publicProtocols.card.finalized', { date: finalized }));
    }
    return parts.join(' · ');
  }

  protected pdfUrl(p: PublicProtocolSummary): string {
    return this.api.pdfUrl(p.id);
  }
}
