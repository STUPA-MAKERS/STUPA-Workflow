import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import {
  EmptyStateComponent,
  formatBytes,
  IconComponent,
  NoteComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import type { PublicDecision, PublicProtocolDetail, PublicTop } from './public-protocols.models';
import { electionCaption } from '../voting/election.util';
import { PublicProtocolsService } from './public-protocols.service';
import { optionKey, orderedCounts, topParts, useNoindex, type TopPart } from './public-protocols.util';
import { dayMonthYear, weekdayDate } from '@shared/date-format';
import { secrecyLabel, voteRulesParts } from '../meetings/meetings-display.util';

/**
 * One public protocol (`/protokolle/:id`, no login): the public version of a final
 * protocol. The head names the gremium, the meeting and the dates; the agenda shows the
 * full text of each public item as rendered Markdown with its decisions. A vote callout
 * in the text shows as the same decision box as a decision outside it. A non-public
 * item keeps its number and shows no title, text or decision. The attendance is counts
 * only. The PDF is the public version, streamed by the API. The page is `noindex`.
 */
@Component({
  selector: 'app-public-protocol-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
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
  /** The images of the protocol stream through its public route, so no login is needed. */
  protected readonly imageSrc = computed(() => {
    const id = this.protocol()?.id;
    return id ? (image: string) => this.api.imageUrl(id, image) : null;
  });

  /** The text of each agenda item, split at the vote callouts of its decisions. */
  private readonly parts = computed(
    () =>
      new Map(
        (this.protocol()?.tops ?? []).map((top) => [
          top.number,
          top.markdown ? topParts(top.markdown, top.decisions) : [],
        ]),
      ),
  );

  protected partsOf(top: PublicTop): TopPart[] {
    return this.parts().get(top.number) ?? [];
  }

  /** "Di, 29.09.2026". */
  protected when(p: PublicProtocolDetail): string {
    return weekdayDate(p.date, this.i18n.formatLocale());
  }

  /** "02.10.2026", or empty without a date. */
  protected finalized(p: PublicProtocolDetail): string {
    return dayMonthYear(p.finalizedAt, this.i18n.formatLocale());
  }

  /** "212 KB", or empty without a size. */
  protected pdfSize(p: PublicProtocolDetail): string {
    return p.pdfSize === null ? '' : formatBytes(p.pdfSize, this.i18n.formatLocale(), 'file');
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

  /** "Wahl · 2 Posten · geheime Abstimmung" for a personnel election. */
  protected electionLine(d: PublicDecision): string {
    const t: Translate = (key, params) => this.i18n.translate(key, params);
    return [
      electionCaption(d.seats ? { seats: d.seats, candidates: [], secret: d.secret } : null, d.round, t),
      secrecyLabel(d.secret, t),
    ].join(' · ');
  }

  /** "Einfache Mehrheit · offene Abstimmung". */
  protected ruleLine(d: PublicDecision): string {
    const t: Translate = (key, params) => this.i18n.translate(key, params);
    return voteRulesParts({ majorityRule: d.majorityRule, secret: d.secret }, t).join(' · ');
  }
}
