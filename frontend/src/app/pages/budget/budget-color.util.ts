import type { BudgetTreeNode } from './budget-tree.api';

/**
 * The display colours of the cost centres (O19, gaps D6).
 *
 * A cost centre can carry its own colour (`BudgetTreeNode.color`), for example the colour
 * of a faculty. {@link nodeColors} gives every node one display colour, and every view of
 * the budget page uses it: the tree rows, the "Auslastung je Budget" bars, the
 * "Verteilung" chart and the overview. The pickers use it for their roots. So a cost
 * centre has the same colour in each place.
 *
 * The rule, in this order:
 *
 * 1. A node with its own colour shows that colour.
 * 2. A node without one takes the colour of the nearest ancestor that has one. Siblings
 *    that share that colour get lighter and darker steps of it ({@link shadeColor}).
 * 3. A node with no colour above it takes the {@link PALETTE} colour of its position
 *    among its siblings. Below the top level, the node hands this colour down as if it
 *    were its own, so a branch keeps one hue. A top-level node does not hand it down:
 *    the first split of a budget then shows different colours.
 *
 * {@link resolveNodeColors} gives only the set colours (steps 1 and 2 without shading).
 * The tree uses it to show a swatch only at a node with a set colour.
 */

/** Fallback colours for nodes without an own or inherited colour. The index keeps them stable. */
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
      const color = ownColor(n) ?? above;
      out.set(n.id, color);
      walk(n.children, color);
    }
  };
  walk(roots, inherited);
  return out;
}

/**
 * A lighter or darker step of a hex colour, so that siblings that share an inherited
 * colour stay apart.
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
 * The display colour of every node in a forest, by the rule at the top of this file.
 *
 * `inherited` is the colour above the given roots. A gremium-scoped tree starts at a sub
 * cost centre whose parent is not in the response, so its roots inherit nothing.
 */
export function nodeColors(
  roots: readonly BudgetTreeNode[],
  inherited: string | null = null,
): Map<string, string> {
  const out = new Map<string, string>();
  const walk = (nodes: readonly BudgetTreeNode[], above: string | null, top: boolean): void => {
    // An inherited colour that a sibling holds as its own starts at step 1, so the two
    // never look the same.
    const steps = new Map<string, number>();
    for (const n of nodes) {
      const own = ownColor(n);
      if (own) steps.set(own, 1);
    }
    nodes.forEach((n, i) => {
      const own = ownColor(n);
      let color: string;
      if (own) {
        color = own;
      } else if (above) {
        const step = steps.get(above) ?? 0;
        steps.set(above, step + 1);
        color = shadeColor(above, step);
      } else {
        color = paletteColor(i);
      }
      out.set(n.id, color);
      walk(n.children, own ?? above ?? (top ? null : color), false);
    });
  };
  walk(roots, inherited?.trim() || null, true);
  return out;
}

function ownColor(node: BudgetTreeNode): string | null {
  return node.color?.trim() || null;
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
