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
import { SimplifyPathPipe } from '@shared/budget-path';
import type { BudgetTreeNode } from './budget-tree.api';
import { PALETTE } from './budget-year-tree.component';

/** Metriken der Übersicht (Tab-Selector im Overlay, #budget-sunburst). */
export type SunburstMetric = 'allocated' | 'available' | 'expended';

/** Ein annulares Segment (eine Kostenstelle auf ihrer Tiefe). */
interface SunSeg {
  id: string;
  name: string;
  pathKey: string;
  depth: number;
  d: string;
  color: string;
  opacity: number;
  value: number;
  percent: number;
}

const SIZE = 480;
const CX = SIZE / 2;
const CY = SIZE / 2;
const R_CENTER = 64;
const R_MAX = SIZE / 2 - 8;

/**
 * Interaktiver Sunburst (#budget-sunburst): radiale Ringe über den ganzen
 * Kostenstellen-Unterbaum — je weiter außen, desto tiefer die Ebene. Das
 * Zentrum zeigt die Wurzel (gewählte Kostenstelle) mit Gesamtwert; Hover
 * zeigt einen Tooltip (Name, Betrag, Anteil), Klick meldet die Kostenstelle
 * (Drilldown im Tab). Rein SVG, keine Fremd-Lib.
 */
@Component({
  selector: 'app-budget-sunburst',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './budget-sunburst.component.html',
  imports: [TranslatePipe, SimplifyPathPipe],
  styleUrl: './budget-sunburst.component.scss',
})
export class BudgetSunburstComponent {
  private readonly i18n = inject(I18nService);

  readonly root = input<BudgetTreeNode | null>(null);
  readonly fyId = input<string>('');
  readonly metric = input<SunburstMetric>('allocated');
  /** Klick auf ein Segment (oder das Zentrum) → Kostenstellen-Id. */
  readonly nodeClick = output<string>();

  protected readonly SIZE = SIZE;
  protected readonly CX = CX;
  protected readonly CY = CY;
  protected readonly R_CENTER = R_CENTER;

  protected readonly hovered = signal<SunSeg | null>(null);
  protected readonly tip = signal<{ x: number; y: number }>({ x: 0, y: 0 });

  private metricOf(node: BudgetTreeNode): number {
    const a = node.byFiscalYear.find((x) => x.fiscalYearId === this.fyId());
    return a ? Number(a[this.metric()]) : 0;
  }

  /** Unterbaum-Wert: eigener (nicht weiterverteilter) Anteil + Σ Kinder —
   *  robust auch wenn die Metrik mal nicht sauber zum Parent aufsummiert. */
  private subtree(node: BudgetTreeNode): number {
    const children = node.children.reduce((s, c) => s + this.subtree(c), 0);
    const own = Math.max(0, this.metricOf(node) - node.children.reduce((s, c) => s + this.metricOf(c), 0));
    return own + children;
  }

  protected readonly total = computed(() => {
    const r = this.root();
    return r ? this.subtree(r) : 0;
  });

  private maxDepth(node: BudgetTreeNode): number {
    return node.children.length ? 1 + Math.max(...node.children.map((c) => this.maxDepth(c))) : 0;
  }

  protected readonly segments = computed<SunSeg[]>(() => {
    const r = this.root();
    const total = this.total();
    if (!r || total <= 0) return [];
    const depthMax = Math.max(1, this.maxDepth(r));
    const ringW = (R_MAX - R_CENTER) / depthMax;
    const out: SunSeg[] = [];
    const layout = (
      node: BudgetTreeNode,
      start: number,
      span: number,
      depth: number,
      color: string | null,
    ): void => {
      const nodeVal = this.subtree(node);
      if (nodeVal <= 0) return;
      let angle = start;
      node.children.forEach((c, i) => {
        const v = this.subtree(c);
        if (v <= 0) return;
        const childSpan = span * (v / nodeVal);
        // Gesetzte Farbe der Kostenstelle gewinnt (wie bei den kleinen Pies);
        // ohne eigene Farbe erbt das Segment die des Eltern-Zweigs.
        const childColor = c.color ?? color ?? PALETTE[i % PALETTE.length];
        const r0 = R_CENTER + (depth - 1) * ringW;
        out.push({
          id: c.id,
          name: c.name,
          pathKey: c.pathKey,
          depth,
          d: annular(angle, angle + childSpan, r0, r0 + ringW - 2),
          color: childColor,
          opacity: Math.max(0.35, 1 - 0.16 * (depth - 1)),
          value: v,
          percent: Math.round((v / total) * 100),
        });
        layout(c, angle, childSpan, depth + 1, childColor);
        angle += childSpan;
      });
    };
    layout(r, -Math.PI / 2, Math.PI * 2, 1, null);
    return out;
  });

  protected rootClick(): void {
    const r = this.root();
    if (r) this.nodeClick.emit(r.id);
  }

  protected onMove(event: PointerEvent): void {
    const host = (event.currentTarget as HTMLElement).getBoundingClientRect();
    this.tip.set({ x: event.clientX - host.left + 14, y: event.clientY - host.top + 14 });
  }

  protected money(value: number): string {
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: 'EUR',
      maximumFractionDigits: 0,
    }).format(value);
  }
}

/** SVG-Pfad eines annularen Segments zwischen zwei Winkeln und zwei Radien. */
function annular(start: number, end: number, r0: number, r1: number): string {
  if (end - start >= Math.PI * 2 - 1e-6) {
    return [
      `M ${CX - r1} ${CY}`,
      `A ${r1} ${r1} 0 1 1 ${CX + r1} ${CY}`,
      `A ${r1} ${r1} 0 1 1 ${CX - r1} ${CY}`,
      'Z',
      `M ${CX - r0} ${CY}`,
      `A ${r0} ${r0} 0 1 0 ${CX + r0} ${CY}`,
      `A ${r0} ${r0} 0 1 0 ${CX - r0} ${CY}`,
      'Z',
    ].join(' ');
  }
  const large = end - start > Math.PI ? 1 : 0;
  const x0 = CX + r1 * Math.cos(start);
  const y0 = CY + r1 * Math.sin(start);
  const x1 = CX + r1 * Math.cos(end);
  const y1 = CY + r1 * Math.sin(end);
  const ix1 = CX + r0 * Math.cos(end);
  const iy1 = CY + r0 * Math.sin(end);
  const ix0 = CX + r0 * Math.cos(start);
  const iy0 = CY + r0 * Math.sin(start);
  return [
    `M ${x0} ${y0}`,
    `A ${r1} ${r1} 0 ${large} 1 ${x1} ${y1}`,
    `L ${ix1} ${iy1}`,
    `A ${r0} ${r0} 0 ${large} 0 ${ix0} ${iy0}`,
    'Z',
  ].join(' ');
}
