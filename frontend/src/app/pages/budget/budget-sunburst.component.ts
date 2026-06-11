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
  template: `
    <div class="sb" (pointermove)="onMove($event)" (pointerleave)="hovered.set(null)">
      @if (total() > 0) {
        <svg [attr.viewBox]="'0 0 ' + SIZE + ' ' + SIZE" class="sb__svg" role="img" [attr.aria-label]="root()?.name ?? ''">
          @for (s of segments(); track s.id + ':' + s.depth) {
            <path
              [attr.d]="s.d"
              [attr.fill]="s.color"
              [attr.fill-opacity]="s.opacity"
              class="sb__seg"
              [class.sb__seg--dim]="hovered() !== null && hovered()?.id !== s.id"
              (pointerenter)="hovered.set(s)"
              (click)="nodeClick.emit(s.id)"
            />
          }
          <circle [attr.cx]="CX" [attr.cy]="CY" [attr.r]="R_CENTER - 6" class="sb__center" (click)="rootClick()" />
          <text [attr.x]="CX" [attr.y]="CY - 6" text-anchor="middle" class="sb__center-name">{{ root()?.name }}</text>
          <text [attr.x]="CX" [attr.y]="CY + 14" text-anchor="middle" class="sb__center-val">{{ money(total()) }}</text>
        </svg>
        @if (hovered(); as h) {
          <div class="sb__tip" [style.left.px]="tip().x" [style.top.px]="tip().y" role="status">
            <strong>{{ h.name }}</strong>
            <span class="sb__tip-path">{{ h.pathKey }}</span>
            <span>{{ money(h.value) }} · {{ h.percent }}%</span>
          </div>
        }
        <p class="sb__hint" aria-hidden="true">{{ 'budget.overview.hint' | t }}</p>
      } @else {
        <p class="sb__empty">{{ 'budget.pie.empty' | t }}</p>
      }
    </div>
  `,
  imports: [TranslatePipe],
  styles: [
    `
      .sb {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--space-3);
        padding: var(--space-2) var(--space-2) var(--space-5);
      }
      .sb__svg {
        width: min(480px, 100%);
        height: auto;
      }
      .sb__seg {
        cursor: pointer;
        stroke: var(--color-bg-elevated);
        stroke-width: 1.5;
        transition: opacity 140ms ease;
      }
      .sb__seg--dim {
        opacity: 0.45;
      }
      .sb__center {
        fill: var(--color-surface-sunken);
        stroke: var(--color-border);
        cursor: pointer;
      }
      .sb__center-name {
        fill: var(--color-text);
        font-size: 14px;
        font-weight: 600;
        pointer-events: none;
      }
      .sb__center-val {
        fill: var(--color-text-muted);
        font-size: 12px;
        font-variant-numeric: tabular-nums;
        pointer-events: none;
      }
      .sb__tip {
        position: absolute;
        display: flex;
        flex-direction: column;
        gap: 0.1rem;
        padding: var(--space-2) var(--space-3);
        background: var(--color-bg-elevated);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-sm);
        box-shadow: var(--shadow-lg);
        font-size: var(--fs-xs);
        pointer-events: none;
        z-index: 1;
        max-width: 16rem;
      }
      .sb__tip-path {
        color: var(--color-text-muted);
      }
      .sb__hint,
      .sb__empty {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
        text-align: center;
      }
    `,
  ],
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
