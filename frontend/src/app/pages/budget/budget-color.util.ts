import type { BudgetTreeNode } from './budget-tree.api';

/**
 * The display colours of the cost centres.
 *
 * A cost centre can carry its own colour (`BudgetTreeNode.color`), for example the colour
 * of a faculty. A node without a colour takes the colour of the nearest ancestor that has
 * one (O19), so the sub cost centres of a faculty read as part of it. A node with no
 * coloured ancestor has no colour: the tree and the bars then use the accent, and a chart
 * takes a colour from {@link PALETTE}.
 */

/** Chart colours for nodes without an own or inherited colour. The index keeps them stable. */
export const PALETTE: readonly string[] = [
  '#5fb37a',
  '#4a90d9',
  '#e0a458',
  '#c45c8a',
  '#8a6fc4',
  '#52a8a8',
  '#d97b5c',
  '#7aa84a',
];

/** The palette colour at an index. A negative index counts from the end. */
export function paletteColor(index: number): string {
  const n = PALETTE.length;
  return PALETTE[((index % n) + n) % n];
}

/**
 * The resolved colour of every node in a forest: its own colour, else the colour of the
 * nearest ancestor with one, else `null`.
 *
 * `inherited` is the colour above the given roots. A gremium-scoped tree starts at a sub
 * cost centre whose parent is not in the response, so its roots inherit nothing.
 */
export function resolveNodeColors(
  roots: readonly BudgetTreeNode[],
  inherited: string | null = null,
): Map<string, string | null> {
  const out = new Map<string, string | null>();
  const walk = (nodes: readonly BudgetTreeNode[], above: string | null): void => {
    for (const n of nodes) {
      const own = n.color?.trim() || null;
      const color = own ?? above;
      out.set(n.id, color);
      walk(n.children, color);
    }
  };
  walk(roots, inherited);
  return out;
}

/**
 * A lighter or darker step of a hex colour, so that siblings that share an inherited
 * colour stay apart in a chart.
 *
 * Step 0 is the colour itself. Odd steps mix towards white, even steps towards black, by
 * 18% more for each pair. A value that is not a `#rgb` or `#rrggbb` hex comes back as it is.
 */
export function shadeColor(hex: string, step: number): string {
  if (step <= 0) return hex;
  const rgb = parseHex(hex);
  if (!rgb) return hex;
  const amount = Math.min(0.72, 0.18 * Math.ceil(step / 2));
  const target = step % 2 === 1 ? 255 : 0;
  const mix = (c: number): number => Math.round(c + (target - c) * amount);
  return `#${[rgb.r, rgb.g, rgb.b].map((c) => mix(c).toString(16).padStart(2, '0')).join('')}`;
}

/**
 * The chart colours of a list of sibling nodes.
 *
 * A node with an own colour keeps it. Siblings that share an inherited colour get the
 * steps of {@link shadeColor}, in their order; when a sibling has that colour as its own,
 * the inherited ones start at step 1. A node with no colour at all takes the
 * palette colour of its position.
 */
export function siblingColors(
  nodes: readonly BudgetTreeNode[],
  colors: ReadonlyMap<string, string | null>,
): string[] {
  // An inherited colour that a sibling holds as its own starts at step 1, so the two
  // never look the same.
  const seen = new Map<string, number>();
  for (const n of nodes) {
    const own = n.color?.trim() || null;
    if (own) seen.set(own, 1);
  }
  return nodes.map((n, i) => {
    const own = n.color?.trim() || null;
    if (own) return own;
    const resolved = colors.get(n.id) ?? null;
    if (!resolved) return paletteColor(i);
    const step = seen.get(resolved) ?? 0;
    seen.set(resolved, step + 1);
    return shadeColor(resolved, step);
  });
}

function parseHex(hex: string): { r: number; g: number; b: number } | null {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join('') : m[1];
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}
