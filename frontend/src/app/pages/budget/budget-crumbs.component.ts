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
 * What gives way when the trail does not fit at full width, in this order: `key` shortens
 * the key at its start ("…200-230-2"), `parents` also shortens the visible parents, and
 * `name` also shortens the current name. Each one goes down to about eight characters.
 */
export type CrumbSqueeze = 'none' | 'key' | 'parents' | 'name';

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
  /** The key of the current cost centre, with the space before it (gap and margin). */
  key: number;
  /** The text of the key alone, without the space before it. Only the text shortens. */
  keyText: number;
  /** A shortened crumb or key keeps at least this width. */
  min: number;
  /** A separator with the gaps on both sides of it. */
  sep: number;
  /** The "…" button. */
  more: number;
  /**
   * How far the "…" moves to the start when it leads the trail (its negative margin, so
   * that its text lines up with the title). The trail gets this width back.
   */
  lead: number;
}

/**
 * Fits the trail into its bar. The steps, each one only when the one before does not fit:
 *
 * 1. The whole path at full width.
 * 2. The first level, the direct parent and the current crumb at full width; the levels
 *    between them go into the "…" menu.
 * 3. As 2, and the key shortens at its start.
 * 4. As 3, and the first level and the direct parent shorten.
 * 5. Only "… › current": all parents go into the menu, the key at full width, then short.
 * 6. As 5, and the current name shortens too.
 *
 * So the current name gives way last. A shortened crumb or key keeps at least `min`, or
 * its own width when that is less.
 */
export function fitCrumbs(m: CrumbMetrics): CrumbFit {
  const parents = m.widths.length - 1;
  if (parents < 0) return { hidden: 0, squeeze: 'none' };
  const short = (w: number) => Math.min(w, m.min);
  const current = m.widths[parents];
  const need = (hidden: number, squeeze: CrumbSqueeze): number => {
    let total = squeeze === 'name' ? short(current) : current;
    // A short key keeps the space before it; only its text shortens.
    total += squeeze === 'none' ? m.key : m.key - m.keyText + short(m.keyText);
    if (hidden > 0) total += m.more + m.sep;
    if (hidden >= parents && parents > 0) total -= m.lead;
    const shortParents = squeeze === 'parents' || squeeze === 'name';
    for (const i of visibleParents(parents, hidden)) total += (shortParents ? short(m.widths[i]) : m.widths[i]) + m.sep;
    return total;
  };
  // The levels between the first one and the direct parent.
  const between = Math.max(0, parents - 2);
  const steps: CrumbFit[] = [
    { hidden: 0, squeeze: 'none' },
    { hidden: between, squeeze: 'none' },
    { hidden: between, squeeze: 'key' },
    { hidden: between, squeeze: 'parents' },
    { hidden: parents, squeeze: 'none' },
    { hidden: parents, squeeze: 'key' },
  ];
  return steps.find((s) => need(s.hidden, s.squeeze) <= m.available) ?? { hidden: parents, squeeze: 'name' };
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

/**
 * px of a separator icon. The template draws the icons at this size and the fit counts
 * it, so the two cannot differ. The gaps beside it come from the flex gap of the trail.
 */
const SEP_ICON = 13;

/**
 * The cost-centre breadcrumb in the bar of the budget sheet: root › … › current, the key
 * of the current cost centre at the end.
 *
 * It never wraps and never makes the bar taller. When the whole path does not fit, the
 * first level, the direct parent and the current cost centre stay at full width and the
 * levels between them go into a "…" menu. Only when that does not fit either, the key
 * shortens at its start ("…200-230-2"), then the first level and the parent, then all
 * parents go into the menu, and at last the current name shortens (see `fitCrumbs`).
 * Nothing shortens below `--crumb-min` (about eight characters). Every shortened crumb
 * and the key have their full text as a tooltip.
 *
 * After a pick (a parent or an entry of the "…" menu) the focus moves to the current
 * crumb of the new path, because the control that had it is gone.
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
  private readonly current = viewChild<ElementRef<HTMLElement>>('current');

  protected readonly fit = signal<CrumbFit>({ hidden: 0, squeeze: 'none' });
  protected readonly sepIcon = SEP_ICON;
  /** The picked cost centre: its crumb takes the focus once the new path is drawn. */
  private focusId: string | null = null;
  /** The natural width of each crumb, for its minimum width (see `--crumb-w`). */
  protected readonly widths = signal<readonly number[]>([]);
  /** The natural width of the key, for its minimum width (see `--key-w`). */
  protected readonly keyWidth = signal<string | null>(null);

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
      const current = this.nodes().at(-1)?.id;
      untracked(() => {
        // A path that does not end at the picked cost centre ends the pending focus.
        if (this.focusId !== null && current !== this.focusId) this.focusId = null;
        this.refit();
      });
    });
    // After a pick: the current crumb of the new path takes the focus. The query changes
    // only when the new crumb is drawn, so the crumb of the old path never gets it.
    afterRenderEffect(() => {
      const el = this.current()?.nativeElement;
      if (el && this.focusId !== null && el.dataset['node'] === this.focusId) {
        this.focusId = null;
        el.focus();
      }
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

  /** A parent was chosen: tell the page, and keep the focus in the trail. */
  protected choose(id: string): void {
    this.focusId = id;
    this.pick.emit(id);
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
    const style = getComputedStyle(nav);
    const gap = parseFloat(style.columnGap) || 0;
    // The padding is the room for hover and focus (`--crumb-bleed`), not for the items.
    const padding = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
    // The copy of the key holds the space before it as padding; the key on screen has it
    // as a margin. Only the text shortens (`--key-w` is the text width).
    const keyEl = box.querySelector<HTMLElement>('[data-key]');
    const key = Math.ceil(width(keyEl));
    const keyPad = keyEl ? parseFloat(getComputedStyle(keyEl).paddingLeft) || 0 : 0;
    const keyText = Math.max(0, key - keyPad);
    // The leading "…" moves to the start by the padding of its button.
    const moreEl = box.querySelector<HTMLElement>('[data-more]');
    const lead = moreEl ? parseFloat(getComputedStyle(moreEl).paddingLeft) || 0 : 0;
    this.widths.set(widths);
    this.keyWidth.set(`${keyText}px`);
    this.fit.set(
      fitCrumbs({
        widths,
        available: nav.clientWidth - padding,
        key: key + gap,
        keyText,
        min: Math.ceil(width(box.querySelector('[data-min]'))),
        sep: SEP_ICON + 2 * gap,
        more: Math.ceil(width(moreEl)),
        lead,
      }),
    );
  }
}
