import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { SegBarComponent } from '@stupa-makers/ui-kit';

/**
 * The turnout of an open vote: "14 von 19 Anwesenden haben abgestimmt", the percent and
 * a bar.
 *
 * Nobody sees an interim tally while the vote runs (no tally for the lead either). No
 * line explains when the counts show: they appear once every present member voted, or
 * after the close for a secret vote.
 *
 * A vote without a meeting has no attendance. Its turnout counts against the eligible
 * voters (`basis="eligible"`).
 *
 * `size="fat"` is the vote card of a meeting: a thicker bar, the line in body text and
 * the percent in the accent.
 */
@Component({
  selector: 'app-vote-progress',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SegBarComponent],
  host: {
    '[class.vp--fat]': "size() === 'fat'",
  },
  templateUrl: './vote-progress.component.html',
  styleUrl: './vote-progress.component.scss',
})
export class VoteProgressComponent {
  private readonly i18n = inject(I18nService);

  /** The ballots cast so far. */
  readonly voted = input.required<number>();
  /** The present members (or the eligible voters for `basis="eligible"`). */
  readonly total = input.required<number>();
  readonly basis = input<'present' | 'eligible'>('present');
  readonly size = input<'normal' | 'fat'>('normal');

  protected readonly percent = computed(() => {
    const total = this.total();
    return total > 0 ? Math.min(100, Math.round((this.voted() / total) * 100)) : 0;
  });

  protected readonly label = computed(() =>
    this.basis() === 'eligible'
      ? this.i18n.translate('voting.progress.eligible', { voted: this.voted(), total: this.total() })
      : this.i18n.translate('meetings.vote.progress', { voted: this.voted(), present: this.total() }),
  );
}
