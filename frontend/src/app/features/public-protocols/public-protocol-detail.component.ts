import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { IconComponent } from '@stupa-makers/ui-kit';
import { formatSize } from '../apply/apply.util';
import type { PublicDecision, PublicProtocolDetail } from './public-protocols.models';
import { electionCaption } from '../voting/election.util';
import { PublicProtocolsService } from './public-protocols.service';
import { longDate, optionKey, orderedCounts, shortDate, useNoindex } from './public-protocols.util';

/**
 * One public protocol (`/protokolle/:id`, no login): the public version of a final
 * protocol. The head names the gremium, the meeting and the dates; the agenda shows the
 * full text of each public item as rendered Markdown with its decisions. A non-public
 * item keeps its number and shows no title, text or decision. The attendance is counts
 * only. The PDF is the public version, streamed by the API. The page is `noindex`.
 */
@Component({
  selector: 'app-public-protocol-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    IconComponent,
    EmptyStateComponent,
    MarkdownViewComponent,
    NoteComponent,
    SkeletonComponent,
  ],
  templateUrl: './public-protocol-detail.component.html',
  styleUrl: './public-protocol-detail.component.scss',
})
export class PublicProtocolDetailComponent {
  private readonly api = inject(PublicProtocolsService);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);

  protected readonly protocol = signal<PublicProtocolDetail | null>(null);
  protected readonly loading = signal(true);
  protected readonly notFound = signal(false);
  protected readonly error = signal(false);

  /** "Di, 29.09.2026". */
  protected when(p: PublicProtocolDetail): string {
    return longDate(p.date, this.i18n.formatLocale());
  }

  /** "02.10.2026", or empty without a date. */
  protected finalized(p: PublicProtocolDetail): string {
    return shortDate(p.finalizedAt, this.i18n.formatLocale());
  }

  /** "212 KB", or empty without a size. */
  protected pdfSize(p: PublicProtocolDetail): string {
    return p.pdfSize === null ? '' : formatSize(p.pdfSize, this.i18n.formatLocale());
  }

  protected pdfUrl(p: PublicProtocolDetail): string {
    return this.api.pdfUrl(p.id);
  }

  constructor() {
    useNoindex();
    const id = String(this.route.snapshot.paramMap.get('id'));
    this.api.detail(id).subscribe({
      next: (p) => {
        this.protocol.set(p);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        // A missing, withheld or non-public protocol is a 404; anything else is an error.
        if (err instanceof HttpErrorResponse && err.status !== 404) {
          this.error.set(true);
        } else {
          this.notFound.set(true);
        }
      },
    });
  }

  protected counts(d: PublicDecision): { label: string; count: number }[] {
    return orderedCounts(d.counts).map(({ option, count }) => {
      const key = optionKey(option);
      return { label: key ? this.i18n.translate(key) : option, count };
    });
  }

  protected resultKey(d: PublicDecision): TranslationKey | null {
    return d.result ? (`vote.result.${d.result}` as TranslationKey) : null;
  }

  /** "Wahl · 2 Posten · geheime Abstimmung" for a personnel election (F2). */
  protected electionLine(d: PublicDecision): string {
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    return [
      electionCaption(d.seats ? { seats: d.seats, candidates: [], secret: d.secret } : null, d.round, t),
      t(d.secret ? 'meetings.vote.secretShort' : 'meetings.vote.publicShort'),
    ].join(' · ');
  }

  /** "Einfache Mehrheit · offene Abstimmung". */
  protected ruleLine(d: PublicDecision): string {
    return [
      this.i18n.translate(`vote.majority.${d.majorityRule}` as TranslationKey),
      this.i18n.translate(d.secret ? 'meetings.vote.secretShort' : 'meetings.vote.publicShort'),
    ].join(' · ');
  }
}
