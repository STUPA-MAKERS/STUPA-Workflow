import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  ButtonGroupComponent,
  DateBlockComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  HighlightComponent,
  IconComponent,
  NoteComponent,
  SearchPillComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import { parseDay, weekdayDate } from '@shared/date-format';
import type {
  PublicDecisionRow,
} from './public-protocols.models';
import { publicList } from './public-list';
import { PublicProtocolsService } from './public-protocols.service';
import {
  optionKey,
  orderedCounts,
  resultKey,
  useNoindex,
} from './public-protocols.util';

/**
 * The public decisions of one Gremium (`/decisions/<slug>`, no login, specs 000926, 002401),
 * newest first and grouped by semester.
 *
 * A motion shows its question, its date, the title of its meeting, its result and the
 * sums of the votes. An election shows its question and its date only. No row names a
 * person. The search (the question) and the Semester chip filter on the server. The head
 * links the protocols of the same Gremium (spec 002402). A slug of no public Gremium shows
 * the empty state (spec 002403). The page is `noindex`.
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
    ButtonGroupComponent,
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

  /** The list logic that this page shares with "Protokolle". */
  private readonly list = publicList<PublicDecisionRow>({
    load: (query) => this.api.decisions(query),
    semesterQuery: (filters) => ({ gremium: filters.gremium }),
  });
  protected readonly appliedQuery = this.list.appliedQuery;
  protected readonly search = this.list.search;
  protected readonly gremium = this.list.gremium;
  protected readonly unknown = this.list.unknown;
  protected readonly semesterFilter = this.list.semesterFilter;
  protected readonly items = this.list.items;
  protected readonly total = this.list.total;
  protected readonly loading = this.list.loading;
  protected readonly loadingMore = this.list.loadingMore;
  protected readonly error = this.list.error;
  protected readonly hasFilters = this.list.hasFilters;
  protected readonly hasMore = this.list.hasMore;
  protected readonly semesterOptions = this.list.semesterOptions;
  protected readonly semesterText = this.list.semesterText;
  protected readonly groups = this.list.groups;

  constructor() {
    useNoindex();
  }

  /** "12 Beschlüsse", or "3 Treffer" with a search text. */
  protected readonly countText = computed(() => {
    const one = this.total() === 1;
    const key: TranslationKey = this.appliedQuery()
      ? one
        ? 'publicProtocols.list.hitsOne'
        : 'publicProtocols.list.hits'
      : one
        ? 'publicDecisions.list.countOne'
        : 'publicDecisions.list.count';
    return this.i18n.translate(key, { n: this.total() });
  });

  protected onSemester(key: string): void {
    this.list.onSemester(key);
  }

  protected resetFilters(): void {
    this.list.resetFilters();
  }

  protected loadMore(): void {
    this.list.loadMore();
  }

  protected dateOf(d: PublicDecisionRow): Date | null {
    return parseDay(d.date);
  }

  /** "Di, 29.09.2026 · 34. Sitzung"; an election has no meeting title. */
  protected meta(d: PublicDecisionRow): readonly string[] {
    const when = weekdayDate(d.date, this.i18n.formatLocale());
    const where = d.kind === 'circular' ? this.i18n.translate('publicDecisions.circular') : d.meetingTitle;
    return [when, ...(where ? [where] : [])];
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
