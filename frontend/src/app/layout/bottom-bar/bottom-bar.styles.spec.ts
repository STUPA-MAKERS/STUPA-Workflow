/**
 * Style contract of the phone bottom bar. jsdom does no layout, so this spec reads the
 * styles: the bar height, the surface that sets it apart from the cards, and the
 * padding that keeps the page clear of the bar.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const bar = readFileSync(join(__dirname, 'bottom-bar.component.scss'), 'utf8');
const shell = readFileSync(join(__dirname, '../shell.component.scss'), 'utf8');

/** The declarations of the first rule with exactly this selector. */
function rule(css: string, selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|\\n)${esc} \\{([^}]*)\\}`));
  if (!m) throw new Error(`No rule ${selector}`);
  return m[1];
}

describe('bottom bar styles', () => {
  it('is 64px high plus the safe area, from the height the shell sets', () => {
    expect(rule(shell, ':host')).toMatch(/--bottom-bar-height: 64px;/);
    expect(rule(bar, '.bb')).toMatch(
      /height: calc\(var\(--bottom-bar-height, 64px\) \+ env\(safe-area-inset-bottom\)\);/,
    );
    // No vertical padding above the entries: the entries centre in the bar.
    expect(rule(bar, '.bb')).toMatch(/padding: 0 4px env\(safe-area-inset-bottom\);/);
  });

  it('keeps the page and fixed page elements clear of the bar', () => {
    expect(rule(shell, '.frame--phone')).toMatch(
      /--app-bottom-inset: calc\(var\(--bottom-bar-height\) \+ env\(safe-area-inset-bottom\)\);/,
    );
    expect(rule(shell, '.frame--phone .frame__body')).toMatch(
      /padding-bottom: calc\(var\(--app-bottom-inset\)/,
    );
  });

  it('has its own surface and a top border, not the card surface', () => {
    const bb = rule(bar, '.bb');
    expect(bb).toMatch(/background: var\(--color-surface-3\);/);
    expect(bb).toMatch(/border-top: var\(--border-width\) solid var\(--color-border\);/);
    expect(bb).toMatch(/--nav-mark-ring: var\(--color-surface-3\);/);
    expect(bb).not.toMatch(/--color-surface-[12]\b/);
  });

  it('makes every entry fill the bar height, so it is a touch target of at least 44px', () => {
    expect(rule(bar, '.bb')).toMatch(/align-items: stretch;/);
    expect(rule(bar, '.bb__item')).toMatch(/justify-content: center;/);
  });
});
