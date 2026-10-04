/**
 * Contrast of the shared building blocks on surface 3 and on the selected row (WCAG 2.1
 * AA: 1.4.3 text, 1.4.11 focus ring, 2.4.7 visible focus).
 *
 * axe cannot compute contrast in jsdom (see `testing/a11y.ts`), so this spec reads the
 * CD tokens of the ui-kit and the styles of the components. On surface 3 the subtle text
 * (`--color-text-subtle`) is below 4.5:1 in both themes. The small texts on surface 3
 * must use the muted text (`--color-text-muted`) instead.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const TOKENS = readFileSync(
  join(__dirname, '../../../../vendor/ui-kit/src/styles/tokens.scss'),
  'utf8',
);
const scss = (file: string) => readFileSync(join(__dirname, file), 'utf8');

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}
function luminance(hex: string): number {
  const h = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The hex value of a primitive token, for example `--c-light-c3`. */
function primitive(name: string): string {
  const m = TOKENS.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})\\s*;`));
  if (!m) throw new Error(`No primitive ${name}`);
  return m[1];
}

/** The primitive that a semantic token refers to in one theme block. */
function semantic(theme: 'light' | 'dark', name: string): string {
  const light = TOKENS.indexOf("data-theme='light'");
  const dark = TOKENS.indexOf("data-theme='dark'");
  const block = theme === 'light' ? TOKENS.slice(light, dark) : TOKENS.slice(dark);
  const m = block.match(new RegExp(`${name}:\\s*var\\((--c-[\\w-]+)\\)\\s*;`));
  if (!m) throw new Error(`No token ${name} in ${theme}`);
  return primitive(m[1]);
}

describe('text on surface 3', () => {
  for (const theme of ['light', 'dark'] as const) {
    it(`${theme}: muted text passes 4.5:1, subtle text does not`, () => {
      const bg = semantic(theme, '--color-surface-3');
      expect(ratio(semantic(theme, '--color-text-muted'), bg)).toBeGreaterThanOrEqual(4.5);
      // If this changes, the overrides below can go.
      expect(ratio(semantic(theme, '--color-text-subtle'), bg)).toBeLessThan(4.5);
    });
  }

  it('the field label on surface 3 uses the muted text', () => {
    expect(scss('field-group/field-row.component.scss')).toMatch(
      /:host-context\(\.rowgroup--bg3\) \.fld__label \{\s*color: var\(--color-text-muted\);/,
    );
  });

  it('the history meta line on surface 3 uses the muted text', () => {
    expect(scss('history/history.component.scss')).toMatch(
      /\.rowgroup--bg3 \.hist__meta \{\s*color: var\(--color-text-muted\);/,
    );
  });

  it('a muted status in any row group on surface 3 uses the muted text', () => {
    expect(scss('../../../styles.scss')).toMatch(
      /\.rowgroup--bg3 app-status-text\.st--muted \{\s*color: var\(--color-text-muted\);/,
    );
  });

  it('the row menu (on surface 3) gives its section caption the muted text', () => {
    const menu = scss('row-menu/row-menu.component.scss');
    expect(menu).toMatch(/\.rm__menu \{[^}]*background: var\(--color-surface-3\);/);
    const cap = menu.match(/\.rm__cap \{([^}]*)\}/)?.[1] ?? '';
    expect(cap).toContain('color: var(--color-text-muted);');
    expect(menu).not.toContain('--color-text-subtle');
  });

  it('the row menu draws its loading blocks on surface 4, not on its own surface 3', () => {
    const menu = scss('row-menu/row-menu.component.scss');
    expect(menu).toMatch(
      /\.rm__loading ::ng-deep \.skel \{\s*background: var\(--color-surface-4\);/,
    );
    // The skeleton itself defaults to surface 3, which is why the menu needs the override.
    expect(scss('skeleton/skeleton.component.scss')).toMatch(
      /\n\.skel \{\s*background: var\(--color-surface-3\);/,
    );
    for (const theme of ['light', 'dark'] as const) {
      expect(semantic(theme, '--color-surface-4')).not.toBe(semantic(theme, '--color-surface-3'));
    }
  });
});

describe('focus in the row menu (WCAG 2.4.7, 1.4.11)', () => {
  const menu = scss('row-menu/row-menu.component.scss');

  for (const theme of ['light', 'dark'] as const) {
    it(`${theme}: the focus ring shows on the item, the surface change alone does not`, () => {
      const item = semantic(theme, '--color-surface-4');
      expect(ratio(item, semantic(theme, '--color-surface-3'))).toBeLessThan(3);
      expect(ratio(semantic(theme, '--color-focus-ring'), item)).toBeGreaterThanOrEqual(3);
    });
  }

  it('a focused item gets an inset ring in the focus colour', () => {
    expect(menu).toMatch(
      /\.rm__item:focus-visible \{[^}]*box-shadow: inset 0 0 0 2px var\(--color-focus-ring\);/,
    );
  });

  it('a disabled item fades only its content, so its focus ring keeps full contrast', () => {
    const disabled = menu.match(/\.rm__item\[aria-disabled='true'\] \{([^}]*)\}/)?.[1] ?? '';
    expect(disabled).not.toContain('opacity');
    expect(menu).toMatch(/\.rm__item\[aria-disabled='true'\] > \* \{\s*opacity:/);
  });
});

describe('text on the selected row', () => {
  for (const theme of ['light', 'dark'] as const) {
    it(`${theme}: muted text passes 4.5:1, subtle text does not`, () => {
      const bg = semantic(theme, '--color-selected');
      expect(ratio(semantic(theme, '--color-text-muted'), bg)).toBeGreaterThanOrEqual(4.5);
      // If this changes, the override below can go.
      expect(ratio(semantic(theme, '--color-text-subtle'), bg)).toBeLessThan(4.5);
    });
  }

  it('a muted status in the sub line of a selected list item uses the muted text', () => {
    expect(scss('list-item/list-item.component.scss')).toMatch(
      /\.li--on \.li__sub ::ng-deep app-status-text\.st--muted \{\s*color: var\(--color-text-muted\);/,
    );
  });
});
