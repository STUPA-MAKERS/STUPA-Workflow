import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * The colour of a part of the bar.
 *
 * - `filled`: the main share (spent, yes votes, done) in the accent.
 * - `second`: a second share beside it (reserved, abstentions) in a pale accent.
 * - `error`: a share that went wrong (over budget, no votes).
 * - `muted`: a share that does not count (absent).
 */
export type SegTone = 'filled' | 'second' | 'error' | 'muted';

/** One part of the bar. Values are in the unit of `total` (euro, votes, items). */
export interface Seg {
  value: number;
  tone: SegTone;
}

/** The height of the bar: 4px, 6px or 10px. */
export type SegBarSize = 'thin' | 'normal' | 'fat';

/**
 * A bar of shares: budget spent and reserved, votes for and against, progress through an
 * agenda.
 *
 * Each part takes its share of `total`, and the rest of the bar stays grey. When the
 * parts add up to more than `total` (an overdrawn budget), the bar scales to their sum,
 * so it never overflows.
 *
 * The bar is a picture for a screen reader: `label` is required and must say the numbers,
 * for example "1.250 € von 4.000 € ausgegeben".
 */
@Component({
  selector: 'app-seg-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    role: 'img',
    '[attr.aria-label]': 'label()',
    '[class]': "'bar--' + size()",
  },
  templateUrl: './seg-bar.component.html',
  styleUrl: './seg-bar.component.scss',
})
export class SegBarComponent {
  readonly segments = input.required<readonly Seg[]>();
  /** The full length of the bar. Without it the parts fill the bar together. */
  readonly total = input<number | null>(null);
  readonly size = input<SegBarSize>('normal');
  /** What the bar shows, with the numbers. */
  readonly label = input.required<string>();

  /** The visible parts with their width in percent, and the width of the grey rest. */
  protected readonly parts = computed(() => {
    const segs = this.segments().filter((s) => s.value > 0);
    const sum = segs.reduce((acc, s) => acc + s.value, 0);
    const scale = Math.max(sum, this.total() ?? 0);
    if (scale <= 0) return { segs: [], rest: true };
    return {
      segs: segs.map((s) => ({ tone: s.tone, width: (s.value / scale) * 100 })),
      rest: sum < scale,
    };
  });
}
