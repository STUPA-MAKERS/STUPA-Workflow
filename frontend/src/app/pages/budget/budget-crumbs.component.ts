import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type ElementRef,
  afterNextRender,
  afterRenderEffect,
  computed,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SimplifyPathPipe } from '@shared/budget-path';
import { RowMenuComponent, type RowMenuSection } from '@shared/ui';
import type { BudgetTreeNode } from './budget-tree.api';

/**
 * What gives way when even "… › current" with the key is too wide: `key` shortens the
 * key (to about eight characters), `name` drops the key and shortens the current name.
 */
export type CrumbSqueeze = 'none' | 'key' | 'name';

/** How the breadcrumb fits its bar: the parents it hides, and what else gives way. */
export interface CrumbFit {
  /**
   * The number of hidden parents. Below the number of parents the levels after the root
   * go into the "…" menu (root › … › parent › current); at the number of parents all of
   * them go (… › current).
   */
  hidden: number;
  squeeze: CrumbSqueeze;
}

/** The widths (px) that `fitCrumbs` adds up. */
export interface CrumbMetrics {
  /** The natural width of each crumb, root first, the current one last. */
  widths: readonly number[];
  /** The width of the whole trail. */
  available: number;
  /** The key of the current cost centre, with the space before it. */
  key: number;
  /** A parent (and a shortened key or current name) keeps at least this width. */
  min: number;
  /** A separator with the gaps on both sides of it. */
  sep: number;
  /** The "…" button. */
  more: number;
}

/**
 * Picks the fewest parents to hide so that each visible parent keeps at least `min` and
 * the current crumb and its key their full width. A parent shows from its natural width
 * down to `min`, so a parent is cut short but stays readable; the levels that do not fit
 * at all go into the "…" menu. Only when "… › current" does not fit either, the key and
 * then the current name give way.
 */
export function fitCrumbs(m: CrumbMetrics): CrumbFit {
  const parents = m.widths.length - 1;
  if (parents < 0) return { hidden: 0, squeeze: 'none' };
  const current = m.widths[parents];
  const need = (hidden: number): number => {
    let total = current + (hidden > 0 ? m.more + m.sep : 0);
    for (const i of visibleParents(parents, hidden)) total += Math.min(m.widths[i], m.min) + m.sep;
    return total;
  };
  for (let hidden = 0; hidden <= parents; hidden++) {
    if (need(hidden) + m.key <= m.available) return { hidden, squeeze: 'none' };
  }
  const squeeze = need(parents) + Math.min(m.key, m.min) <= m.available ? 'key' : 'name';
  return { hidden: parents, squeeze };
}

/** The indices of the parents that stay visible (see `CrumbFit.hidden`). */
export function visibleParents(parents: number, hidden: number): number[] {
  const all = Array.from({ length: parents }, (_, i) => i);
  if (hidden <= 0) return all;
  if (hidden >= parents) return [];
  return [0, ...all.slice(hidden + 1)];
}

/** One item of the drawn breadcrumb. */
type Item =
  | { kind: 'node'; node: BudgetTreeNode; index: number; current: boolean }
  | { kind: 'more'; nodes: BudgetTreeNode[] };

/** px of a separator icon. The gaps beside it come from the flex gap of the trail. */
const SEP_ICON = 13;

/**
 * The cost-centre breadcrumb in the bar of the budget sheet: root › … › current, the key
 * of the current cost centre at the end.
 *
 * It never wraps and never makes the bar taller. A parent shortens with an ellipsis, but
 * not below `--crumb-min` (about eight characters); when the parents do not fit at that
 * width, the levels after the root go into a "…" menu, nearest to the root first. The
 * current cost centre and its key keep their full width while they fit; else the key
 * shortens, and in a very narrow bar the key goes and the name shortens. Every shortened
 * crumb has its full name as a tooltip.
 *
 * The widths come from a hidden copy of the names. A new path, a new width of the bar or
 * of the copy (`ResizeObserver`, for example when the web font arrives) fits the trail
 * again.
 */
@Component({
  selector: 'app-budget-crumbs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, TranslatePipe, SimplifyPathPipe, RowMenuComponent],
  templateUrl: './budget-crumbs.component.html',
  styleUrl: './budget-crumbs.component.scss',
})
export class BudgetCrumbsComponent {
  /** The path from the root to the selected cost centre. */
  readonly nodes = input.required<readonly BudgetTreeNode[]>();
  /** A parent cost centre was chosen (a crumb or an entry of the "…" menu). */
  readonly pick = output<string>();

  private readonly destroyRef = inject(DestroyRef);
  private readonly nav = viewChild.required<ElementRef<HTMLElement>>('nav');
  private readonly measure = viewChild.required<ElementRef<HTMLElement>>('measure');

  protected readonly fit = signal<CrumbFit>({ hidden: 0, squeeze: 'none' });
  /** The natural width of each crumb, for its minimum width (see `--crumb-w`). */
  protected readonly widths = signal<readonly number[]>([]);

  protected readonly items = computed<Item[]>(() => {
    const nodes = this.nodes();
    const parents = nodes.length - 1;
    if (parents < 0) return [];
    const { hidden } = this.fit();
    const visible = visibleParents(parents, hidden);
    const items: Item[] = [];
    for (let i = 0; i < parents; i++) {
      if (visible.includes(i)) items.push({ kind: 'node', node: nodes[i], index: i, current: false });
      // The "…" stands where the first hidden level would be.
      if (hidden > 0 && i === (hidden >= parents ? 0 : 1)) {
        items.push({ kind: 'more', nodes: this.hiddenNodes(nodes, parents, hidden) });
      }
    }
    items.push({ kind: 'node', node: nodes[parents], index: parents, current: true });
    return items;
  });

  constructor() {
    // A new path: fit it after it is drawn.
    afterRenderEffect(() => {
      this.nodes();
      untracked(() => this.refit());
    });
    // A new width of the bar, or new widths of the names (the web font arrives after the
    // first fit, and the hidden copy then changes its size).
    afterNextRender(() => {
      if (typeof ResizeObserver === 'undefined') return;
      const observer = new ResizeObserver(() => this.refit());
      observer.observe(this.nav().nativeElement);
      observer.observe(this.measure().nativeElement);
      this.destroyRef.onDestroy(() => observer.disconnect());
    });
  }

  /** The natural width of a crumb as a CSS length, once it is measured. */
  protected crumbWidth(index: number): string | null {
    const w = this.widths()[index];
    return w === undefined ? null : `${w}px`;
  }

  protected menuSections(nodes: readonly BudgetTreeNode[]): RowMenuSection[] {
    return [{ items: nodes.map((n) => ({ id: n.id, label: n.name })) }];
  }

  private hiddenNodes(nodes: readonly BudgetTreeNode[], parents: number, hidden: number): BudgetTreeNode[] {
    const visible = visibleParents(parents, hidden);
    return nodes.slice(0, parents).filter((_, i) => !visible.includes(i));
  }

  /** Measures the hidden copy and the bar, and fits the trail. */
  private refit(): void {
    const nav = this.nav().nativeElement;
    const box = this.measure().nativeElement;
    const width = (el: Element | null) => (el ? (el as HTMLElement).getBoundingClientRect().width : 0);
    const widths = Array.from(box.querySelectorAll('[data-crumb]'), (el) => Math.ceil(width(el)));
    const gap = parseFloat(getComputedStyle(nav).columnGap) || 0;
    this.widths.set(widths);
    this.fit.set(
      fitCrumbs({
        widths,
        available: nav.clientWidth,
        // The copy of the key holds the space before it as padding.
        key: Math.ceil(width(box.querySelector('[data-key]'))) + gap,
        min: Math.ceil(width(box.querySelector('[data-min]'))),
        sep: SEP_ICON + 2 * gap,
        more: Math.ceil(width(box.querySelector('[data-more]'))),
      }),
    );
  }
}
