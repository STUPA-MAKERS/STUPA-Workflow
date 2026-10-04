import type { BudgetTreeNode } from './budget-tree.api';
import {
  PALETTE,
  paletteColor,
  resolveNodeColors,
  shadeColor,
  siblingColors,
} from './budget-color.util';

function node(id: string, color: string | null, children: BudgetTreeNode[] = []): BudgetTreeNode {
  return {
    id,
    parentId: null,
    gremiumId: null,
    key: id,
    pathKey: id,
    name: id,
    currency: 'EUR',
    active: true,
    color,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children,
  };
}

describe('resolveNodeColors', () => {
  // root (none) → faculty (blue) → group (none) → leaf (none); root → other (none)
  const tree = [
    node('root', null, [
      node('faculty', '#0075bf', [node('group', null, [node('leaf', null)])]),
      node('other', null),
    ]),
  ];

  it('keeps an own colour and hands it down to every node below without one', () => {
    const colors = resolveNodeColors(tree);
    expect(colors.get('faculty')).toBe('#0075bf');
    expect(colors.get('group')).toBe('#0075bf');
    expect(colors.get('leaf')).toBe('#0075bf');
  });

  it('gives no colour to a node without a coloured ancestor', () => {
    const colors = resolveNodeColors(tree);
    expect(colors.get('root')).toBeNull();
    expect(colors.get('other')).toBeNull();
  });

  it('lets a nearer own colour win over the inherited one', () => {
    const colors = resolveNodeColors([
      node('a', '#111111', [node('b', '#222222', [node('c', null)])]),
    ]);
    expect(colors.get('c')).toBe('#222222');
  });

  it('treats a blank colour as none and starts from the given inherited colour', () => {
    const colors = resolveNodeColors([node('a', '  ', [node('b', null)])], '#abcdef');
    expect(colors.get('a')).toBe('#abcdef');
    expect(colors.get('b')).toBe('#abcdef');
  });
});

describe('paletteColor', () => {
  it('cycles through the palette and wraps a negative index', () => {
    expect(paletteColor(0)).toBe(PALETTE[0]);
    expect(paletteColor(PALETTE.length)).toBe(PALETTE[0]);
    expect(paletteColor(-1)).toBe(PALETTE[PALETTE.length - 1]);
  });
});

describe('shadeColor', () => {
  it('returns the colour itself at step 0', () => {
    expect(shadeColor('#336699', 0)).toBe('#336699');
  });

  it('mixes odd steps towards white and even steps towards black', () => {
    expect(shadeColor('#000000', 1)).toBe('#2e2e2e'); // 18% of 255
    expect(shadeColor('#ffffff', 2)).toBe('#d1d1d1'); // 18% towards 0
    expect(shadeColor('#000000', 3)).toBe('#5c5c5c'); // 36%
  });

  it('expands a short hex and leaves anything else unchanged', () => {
    expect(shadeColor('#000', 1)).toBe('#2e2e2e');
    expect(shadeColor('var(--x)', 1)).toBe('var(--x)');
  });
});

describe('siblingColors', () => {
  it('keeps own colours, shades shared inherited ones and falls back to the palette', () => {
    const parent = node('p', '#0075bf', [node('a', null), node('b', null)]);
    const free = node('f', null);
    const colors = resolveNodeColors([parent, free]);
    expect(siblingColors(parent.children, colors)).toEqual(['#0075bf', shadeColor('#0075bf', 1)]);
    expect(siblingColors([free], colors)).toEqual([PALETTE[0]]);
  });

  it('starts an inherited colour at step 1 when a sibling holds it as its own', () => {
    const children = [node('a', null), node('b', '#0075bf')];
    const colors = resolveNodeColors([node('p', '#0075bf', children)]);
    expect(siblingColors(children, colors)).toEqual([shadeColor('#0075bf', 1), '#0075bf']);
  });
});
