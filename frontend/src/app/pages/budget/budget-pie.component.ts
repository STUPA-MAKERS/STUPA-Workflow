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

/** A pie slice: label, value in currency units and colour (any CSS colour).
 *  An `id`, which is a cost centre id, makes the slice clickable for a drilldown. */
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

const SIZE = 200;
const R = 87;
const INNER = 65;
const CX = SIZE / 2;
const CY = SIZE / 2;
const GROW = 5; // radial growth on hover

/**
 * Donut chart of a distribution with its legend ("Verteilung").
 *
 * The ring shows the slices; the hole shows the metric and the total. The legend beside
 * it lists every slice with its colour, name and amount. A legend entry and a slice with
 * an `id` are clickable for the drilldown; the legend entries are the keyboard path.
 * Hover on a slice or an entry highlights both. Pure SVG, no third-party library.
 *
 * Without an amount (all slices 0) the chart keeps its size and shows one neutral ring
 * with 0 in the hole, so the layout does not jump when the metric changes.
 */
@Component({
  selector: 'app-budget-pie',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  templateUrl: './budget-pie.component.html',
  styleUrl: './budget-pie.component.scss',
})
export class BudgetPieComponent {
  private readonly i18n = inject(I18nService);

  /** The metric, shown in the hole above the total ("Zuteilung"). */
  readonly label = input<string>('');
  /** The accessible name of the chart. Defaults to the label. */
  readonly ariaLabel = input<string | null>(null);
  readonly slices = input<PieSlice[]>([]);
  /** The currency of the amounts. */
  readonly currency = input<string>('EUR');
  /** Click on a slice or an entry with an `id`: emits the cost centre id. */
  readonly sliceClick = output<string>();

  protected readonly SIZE = SIZE;
  /** The full ring that shows when there is no amount. */
  protected readonly EMPTY_RING = donutArc(0, Math.PI * 2);
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

  /** True when no slice has an amount. */
  protected readonly empty = computed(() => this.total() <= 0);

  /** The accessible name. Without an amount it also says that there is no amount. */
  protected readonly name = computed(() => {
    const name = this.ariaLabel() ?? this.label();
    return this.empty() ? this.i18n.translate('budget.pie.emptyLabel', { name }) : name;
  });

  protected onSlice(a: Arc): void {
    if (a.id) this.sliceClick.emit(a.id);
  }

  protected sliceTransform(a: Arc, i: number): string {
    return this.hovered() === i
      ? `translate(${a.midX * GROW}px, ${a.midY * GROW}px) scale(1.03)`
      : 'none';
  }

  protected money(value: number): string {
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: this.currency() || 'EUR',
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
