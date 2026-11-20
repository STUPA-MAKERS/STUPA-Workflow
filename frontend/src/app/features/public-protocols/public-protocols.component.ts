import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
} from '@angular/core';
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
  formatBytes,
  HighlightComponent,
  IconComponent,
  NoteComponent,
  SearchPillComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import type {
  PublicProtocolSummary,
  PublicVoteResult,
} from './public-protocols.models';
import { publicList } from './public-list';
import { FileOpenService } from '@shared/viewer/file-open.service';
import { PublicProtocolsService } from './public-protocols.service';
import {
  resultKey,
  topCounts,
  useNoindex,
} from './public-protocols.util';
import { dayMonthYear, parseDay, weekdayDate } from '@shared/date-format';

/**
 * "Öffentliche Protokolle" (`/protocols`, no login): the final protocols of the gremien
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
  templateUrl: './public-protocols.component.html',
  styleUrl: './public-protocols.component.scss',
})
export class PublicProtocolsComponent {
  private readonly api = inject(PublicProtocolsService);
  private readonly files = inject(FileOpenService);
  private readonly i18n = inject(I18nService);

  /** The list logic that this page shares with "Beschlüsse". */
  private readonly list = publicList<PublicProtocolSummary>({
    load: (query) => this.api.list(query),
    semesterQuery: (filters) => filters,
    checkCommittee: false,
  });
  protected readonly appliedQuery = this.list.appliedQuery;
  protected readonly search = this.list.search;
  protected readonly gremiumFilter = this.list.gremiumFilter;
  protected readonly semesterFilter = this.list.semesterFilter;
  protected readonly items = this.list.items;
  protected readonly total = this.list.total;
  protected readonly loading = this.list.loading;
  protected readonly loadingMore = this.list.loadingMore;
  protected readonly error = this.list.error;
  protected readonly hasFilters = this.list.hasFilters;
  protected readonly hasMore = this.list.hasMore;
  protected readonly gremiumOptions = this.list.gremiumOptions;
  protected readonly gremiumText = this.list.gremiumText;
  protected readonly semesterOptions = this.list.semesterOptions;
  protected readonly semesterText = this.list.semesterText;
  protected readonly groups = this.list.groups;

  constructor() {
    useNoindex();
  }

  protected readonly countText = computed(() =>
    this.i18n.translate(
      this.total() === 1
        ? this.appliedQuery()
          ? 'publicProtocols.list.hitsOne'
          : 'publicProtocols.list.countOne'
        : this.appliedQuery()
          ? 'publicProtocols.list.hits'
          : 'publicProtocols.list.count',
      { n: this.total() },
    ),
  );

  protected onGremien(ids: readonly string[]): void {
    this.list.onGremien(ids);
  }

  protected onSemester(key: string): void {
    this.list.onSemester(key);
  }

  protected resetFilters(): void {
    this.list.resetFilters();
  }

  protected loadMore(): void {
    this.list.loadMore();
  }

  protected dateOf(p: PublicProtocolSummary): Date | null {
    return parseDay(p.date);
  }

  protected when(p: PublicProtocolSummary): string {
    return weekdayDate(p.date, this.i18n.formatLocale());
  }

  protected resultLabel(result: PublicVoteResult): TranslationKey {
    return resultKey(result);
  }

  /** "2 Beschlüsse · 1 nicht-öffentlicher TOP ausgelassen". */
  protected countsLine(p: PublicProtocolSummary): readonly string[] {
    const { decisions, nonPublic } = topCounts(p.tops);
    const decided =
      decisions === 0
        ? this.i18n.translate('publicProtocols.card.noDecision')
        : this.i18n.translate(
            decisions === 1 ? 'publicProtocols.card.decision' : 'publicProtocols.card.decisions',
            { n: decisions },
          );
    const skipped =
      nonPublic > 0
        ? [
            this.i18n.translate(
              nonPublic === 1 ? 'publicProtocols.card.skippedOne' : 'publicProtocols.card.skipped',
              { n: nonPublic },
            ),
          ]
        : [];
    return [decided, ...skipped];
  }

  /** "PDF · 212 KB · finalisiert 02.10.2026". */
  protected pdfMeta(p: PublicProtocolSummary): string {
    const locale = this.i18n.formatLocale();
    const size = p.pdfSize !== null ? [formatBytes(p.pdfSize, locale, 'file')] : [];
    const finalized = dayMonthYear(p.finalizedAt, this.i18n.formatLocale());
    const date = finalized
      ? [this.i18n.translate('publicProtocols.card.finalized', { date: finalized })]
      : [];
    return ['PDF', ...size, ...date].join(' · ');
  }

  protected pdfUrl(p: PublicProtocolSummary): string {
    return this.api.pdfUrl(p.id);
  }

  /** The PDF opens in the file viewer (spec 001080); a click with a modifier keeps the link. */
  protected openPdf(event: MouseEvent, p: PublicProtocolSummary): void {
    this.files.click(event, { name: `${p.title}.pdf`, url: this.pdfUrl(p), kind: 'pdf' });
  }
}
