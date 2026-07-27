import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** A pie slice: label, value in currency units and color.
 *  An `id`, which is a cost center id, makes the slice clickable for a drilldown. */
export interface PieSlice {
  label: string;
  value: number;
  color: string;
  id?: string;
}

interface Arc extends PieSlice {
  d: string;
  midX: number;
  midY: number;
  percent: number;
}

const SIZE = 160;
const R = 70;
const INNER = 38;
const CX = SIZE / 2;
const CY = SIZE / 2;
const GROW = 7; // radial growth on hover

/**
 * Interactive donut chart of the distribution across the pie slices.
 *
 * The short title stands above the chart and there is no box. Hover highlights a
 * slice and grows it radially with an animation. A tooltip shows the label, the
 * amount and the percent. The chart is pure SVG and uses no third-party library.
 */
@Component({
  selector: 'app-budget-pie',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure class="pie">
      <figcaption class="pie__title">{{ title() }}</figcaption>
      @if (total() > 0) {
        <svg [attr.viewBox]="'0 0 ' + SIZE + ' ' + SIZE" class="pie__svg" role="img" [attr.aria-label]="title()">
          @for (a of arcs(); track a.label; let i = $index) {
            <path
              [attr.d]="a.d"
              [attr.fill]="a.color"
              class="pie__slice"
              [class.pie__slice--dim]="hovered() !== null && hovered() !== i"
              [style.transform]="sliceTransform(a, i)"
              (pointerenter)="hovered.set(i)"
              (pointerleave)="hovered.set(null)"
              (click)="onSlice(a)"
            />
          }
        </svg>
        <div class="pie__legend" aria-hidden="true">
          @if (active(); as a) {
            <span class="pie__swatch" [style.background]="a.color"></span>
            <span class="pie__legLabel">{{ a.label }}</span>
            <span class="pie__legVal">{{ money(a.value) }} · {{ a.percent }}%</span>
          } @else {
            <span class="pie__legHint">{{ 'budget.pie.hint' | t }}</span>
          }
        </div>
      } @else {
        <p class="pie__empty">{{ 'budget.pie.empty' | t }}</p>
      }
    </figure>
  `,
  imports: [TranslatePipe],
  styles: [
    `
      .pie {
        margin: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--space-1);
      }
      .pie__title {
        align-self: flex-start;
        font-size: var(--fs-sm);
        font-weight: var(--fw-semibold);
        color: var(--color-text-muted);
      }
      .pie__svg {
        width: 160px;
        height: 160px;
        overflow: visible;
      }
      .pie__slice {
        transform-origin: ${CX}px ${CY}px;
        transition:
          transform 160ms ease,
          opacity 160ms ease;
        cursor: pointer;
      }
      .pie__slice--dim {
        opacity: 0.4;
      }
      .pie__legend {
        display: flex;
        align-items: center;
        gap: var(--space-2);
        min-height: 1.25rem;
        font-size: var(--fs-xs);
      }
      .pie__swatch {
        width: 10px;
        height: 10px;
        border-radius: 2px;
      }
      .pie__legVal {
        color: var(--color-text-muted);
        font-variant-numeric: tabular-nums;
      }
      .pie__legHint,
      .pie__empty {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
      }
    `,
  ],
})
export class BudgetPieComponent {
  private readonly i18n = inject(I18nService);

  readonly title = input<string>('');
  readonly slices = input<PieSlice[]>([]);
  /** Click on a slice with an `id`: emits the cost center id for the drilldown. */
  readonly sliceClick = output<string>();

  protected readonly SIZE = SIZE;
  protected readonly hovered = signal<number | null>(null);

  protected readonly total = computed(() =>
    this.slices().reduce((s, x) => s + Math.max(0, x.value), 0),
  );

  protected readonly arcs = computed<Arc[]>(() => {
    const total = this.total();
    if (total <= 0) return [];
    const out: Arc[] = [];
    let angle = -Math.PI / 2; // 12 o'clock
    for (const s of this.slices()) {
      const frac = Math.max(0, s.value) / total;
      if (frac <= 0) continue;
      const end = angle + frac * Math.PI * 2;
      const mid = (angle + end) / 2;
      out.push({
        ...s,
        percent: Math.round(frac * 100),
        d: donutArc(angle, end),
        midX: Math.cos(mid),
        midY: Math.sin(mid),
      });
      angle = end;
    }
    return out;
  });

  protected readonly active = computed<Arc | null>(() => {
    const h = this.hovered();
    return h === null ? null : (this.arcs()[h] ?? null);
  });

  protected onSlice(a: Arc): void {
    if (a.id) this.sliceClick.emit(a.id);
  }

  protected sliceTransform(a: Arc, i: number): string {
    return this.hovered() === i
      ? `translate(${a.midX * GROW}px, ${a.midY * GROW}px) scale(1.04)`
      : 'none';
  }

  protected money(value: number): string {
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: 'EUR',
      maximumFractionDigits: 0,
    }).format(value);
  }
}

/** SVG path of a donut segment between two angles (radians). */
function donutArc(start: number, end: number): string {
  // Full circle (a single 100% slice): start == end, so one arc draws nothing.
  // Draw the whole ring instead: outer circle CW, hole CCW.
  if (end - start >= Math.PI * 2 - 1e-6) {
    return [
      `M ${CX - R} ${CY}`,
      `A ${R} ${R} 0 1 1 ${CX + R} ${CY}`,
      `A ${R} ${R} 0 1 1 ${CX - R} ${CY}`,
      'Z',
      `M ${CX - INNER} ${CY}`,
      `A ${INNER} ${INNER} 0 1 0 ${CX + INNER} ${CY}`,
      `A ${INNER} ${INNER} 0 1 0 ${CX - INNER} ${CY}`,
      'Z',
    ].join(' ');
  }
  const large = end - start > Math.PI ? 1 : 0;
  const x0 = CX + R * Math.cos(start);
  const y0 = CY + R * Math.sin(start);
  const x1 = CX + R * Math.cos(end);
  const y1 = CY + R * Math.sin(end);
  const ix1 = CX + INNER * Math.cos(end);
  const iy1 = CY + INNER * Math.sin(end);
  const ix0 = CX + INNER * Math.cos(start);
  const iy0 = CY + INNER * Math.sin(start);
  return [
    `M ${x0} ${y0}`,
    `A ${R} ${R} 0 ${large} 1 ${x1} ${y1}`,
    `L ${ix1} ${iy1}`,
    `A ${INNER} ${INNER} 0 ${large} 0 ${ix0} ${iy0}`,
    'Z',
  ].join(' ');
}
