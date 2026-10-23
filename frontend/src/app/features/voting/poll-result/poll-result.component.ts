import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { PollConfig, PollResult } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate } from '@core/i18n/translations';
import { SegBarComponent, type SegTone, StatusTextComponent } from '@stupa-makers/ui-kit';
import { POLL_ABSTAIN, type PollBar, pollBars, pollTopLine } from '../poll.util';

/**
 * The result of a poll ("Umfrage"): the options by votes, highest first. Every tied
 * top option gets the tag "meiste Stimmen". A date poll counts Ja and Vielleicht per
 * date ("3 (+2)", sorted by Ja, then by Ja plus Vielleicht), tags "bester Termin" and
 * explains the numbers ("Zahl = Ja, (+n) = Vielleicht"). The footer counts the answers:
 * "n von m haben geantwortet". A poll lists counts only,
 * never a name.
 */
@Component({
  selector: 'app-poll-result',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SegBarComponent, StatusTextComponent, TranslatePipe],
  host: {
    '[class.bars--beamer]': "variant() === 'beamer'",
  },
  templateUrl: './poll-result.component.html',
  styleUrls: ['../vote-bars.component.scss', './poll-result.component.scss'],
})
export class PollResultComponent {
  private readonly i18n = inject(I18nService);

  readonly poll = input.required<PollConfig>();
  /** The counts of the server: stored at the close, live once revealed. */
  readonly result = input<PollResult | null>(null);
  /** The revealed counts of the tally, as a fallback without `result`. */
  readonly counts = input<Readonly<Record<string, number>>>({});
  /** The answers and the eligible persons of the footer. */
  readonly answered = input(0);
  readonly total = input(0);
  readonly variant = input<'compact' | 'beamer'>('compact');

  private readonly t: Translate = (key, params) => this.i18n.translate(key, params);

  protected readonly date = computed(() => this.poll().mode === 'date');
  protected readonly bars = computed<PollBar[]>(() =>
    pollBars(this.poll(), this.result(), this.counts(), this.i18n.formatLocale(), this.t),
  );
  /** "Meiste Stimmen: A, B" or "Bester Termin: …", or `null` without a vote. */
  protected readonly topLine = computed(() => pollTopLine(this.poll(), this.bars(), this.t));
  /** The base of the bars: the ballots of a date poll, else every vote and abstention. */
  protected readonly base = computed(() => {
    if (this.date()) return Math.max(this.result()?.ballots ?? 0, this.answered());
    return this.bars().reduce((sum, b) => sum + b.count, 0);
  });
  protected readonly footer = computed(() =>
    this.t('poll.result.footer', { n: this.answered(), m: this.total() }),
  );

  protected pct(bar: PollBar): number {
    const base = this.base();
    return base > 0 ? Math.round((bar.count / base) * 100) : 0;
  }

  protected tone(bar: PollBar): SegTone {
    if (bar.id === POLL_ABSTAIN) return 'muted';
    return bar.top ? 'filled' : 'second';
  }

  protected barLabel(bar: PollBar): string {
    if (bar.maybe !== null) {
      return this.t('poll.result.dateRow', { option: bar.label, yes: bar.count, maybe: bar.maybe });
    }
    return this.t('voting.bars.row', { option: bar.label, count: bar.count, pct: this.pct(bar) });
  }
}
