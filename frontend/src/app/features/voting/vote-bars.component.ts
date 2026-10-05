import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { VoteResult } from '@core/api/models';
import { SegBarComponent, type SegTone } from '@shared/ui/seg-bar/seg-bar.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { voteResultStatus, type StatusView } from '@shared/status-kind.util';
import { voteOptionLabel } from '../meetings/meetings-display.util';

interface BarRow {
  option: string;
  label: string;
  count: number;
  /** Share of the cast ballots, rounded to whole percent. */
  pct: number;
  tone: SegTone;
}

/** Ja in the accent, Nein in the error colour, Enthaltung grey (board Beamer). */
const TONES: Record<string, SegTone> = { yes: 'filled', no: 'error', abstain: 'muted' };

/**
 * The result of a vote: one row per option with the count, the share of the cast
 * ballots and a bar, and above them the result as status text.
 *
 * "Angenommen" takes the accent, "Abgelehnt" the error colour. A tie is a rejection
 * (O18): the server has no tie break, so `tie` shows as "Abgelehnt". A missed quorum
 * adds "Quorum nicht erreicht".
 *
 * The vote page, the live page and the beamer share this component. It shows
 * aggregated counts only, never a name. Pass counts only when the server revealed them.
 */
@Component({
  selector: 'app-vote-bars',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SegBarComponent, StatusTextComponent, TranslatePipe],
  host: {
    '[class.bars--beamer]': "variant() === 'beamer'",
  },
  templateUrl: './vote-bars.component.html',
  styleUrl: './vote-bars.component.scss',
})
export class VoteBarsComponent {
  private readonly i18n = inject(I18nService);

  readonly options = input.required<readonly string[]>();
  readonly counts = input.required<Readonly<Record<string, number>>>();
  /** The result of a closed vote. Without it the component shows no status line. */
  readonly result = input<VoteResult | string | null>(null);
  /** Why a closed vote failed. `quorum` adds "Quorum nicht erreicht". */
  readonly failedReason = input<'quorum' | 'majority' | null | undefined>(null);
  readonly variant = input<'compact' | 'beamer'>('compact');

  /** All cast ballots: the base of the shares. */
  protected readonly cast = computed(() =>
    this.options().reduce((sum, o) => sum + (this.counts()[o] ?? 0), 0),
  );

  protected readonly rows = computed<BarRow[]>(() => {
    const counts = this.counts();
    const cast = this.cast();
    return this.options().map((option) => {
      const count = counts[option] ?? 0;
      return {
        option,
        label: voteOptionLabel(option, (key) => this.i18n.translate(key)),
        count,
        pct: cast > 0 ? Math.round((count / cast) * 100) : 0,
        tone: TONES[option] ?? 'filled',
      };
    });
  });

  /** The status line. Every result that is not `passed` is a rejection (O18). */
  protected readonly status = computed<StatusView | null>(() => {
    const result = this.result();
    if (!result) return null;
    return voteResultStatus(result === 'passed' ? 'passed' : 'rejected');
  });

  protected rowLabel(row: BarRow): string {
    return this.i18n.translate('voting.bars.row', {
      option: row.label,
      count: row.count,
      pct: row.pct,
    });
  }
}
