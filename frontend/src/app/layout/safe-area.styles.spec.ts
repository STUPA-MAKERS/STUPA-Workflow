/**
 * Safe-area contract of the shell. The installed iOS app has the black-translucent status
 * bar (index.html), so the page reaches under it, and in landscape the notch takes the
 * left and the right edge. jsdom does no layout, so this spec reads the styles: the shell
 * names the insets once, and the top chrome, the rail, the bottom bar and the pages that
 * pull the main padding back keep clear of them.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const read = (rel: string): string => readFileSync(join(__dirname, rel), 'utf8');
const shell = read('shell.component.scss');

/** The declarations of the first rule with exactly this selector. */
function rule(css: string, selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|\\n)${esc} \\{([^}]*)\\}`));
  if (!m) throw new Error(`No rule ${selector}`);
  return m[1];
}

describe('safe-area styles', () => {
  it('names the device insets once in the shell', () => {
    const host = rule(shell, ':host');
    expect(host).toMatch(/--app-top-safe-area: env\(safe-area-inset-top, 0px\);/);
    expect(host).toMatch(/--app-left-safe-area: env\(safe-area-inset-left, 0px\);/);
    expect(host).toMatch(/--app-right-safe-area: env\(safe-area-inset-right, 0px\);/);
  });

  it('lets the iOS status bar show the page colour', () => {
    const index = readFileSync(join(__dirname, '..', '..', 'index.html'), 'utf8');
    expect(index).toContain(
      '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />',
    );
    const strip = rule(shell, '.frame--rail::before,\n.frame--phone::before');
    expect(strip).toMatch(/position: fixed;/);
    expect(strip).toMatch(/height: var\(--app-top-safe-area\);/);
    expect(strip).toMatch(/background: var\(--color-bg\);/);
  });

  it('starts every page below the status bar, in the top padding that pages pull back', () => {
    expect(rule(shell, '.main')).toMatch(
      /--main-pad-top: calc\(var\(--space-8\) \+ var\(--app-top-safe-area\)\);/,
    );
    expect(rule(shell, '.frame--rail .main')).toMatch(
      /--main-pad-top: calc\(var\(--layout-gutter\) \+ var\(--app-top-safe-area\)\);/,
    );
    expect(rule(shell, '.frame--phone .main')).toMatch(
      /--main-pad-top: calc\(var\(--space-4\) \+ var\(--app-top-safe-area\)\);/,
    );
    // An edge-to-edge page pulls the padding back, but not the inset.
    for (const page of [
      '../features/meetings/meeting-page/meeting-page.component.scss',
      '../features/meetings/meeting-follow-view.component.scss',
    ]) {
      expect(read(page)).toMatch(
        /margin-block: calc\(var\(--app-top-safe-area, 0px\) - var\(--main-pad-top, var\(--space-8\)\)\)/,
      );
    }
  });

  it('keeps the rail, the main region and the phone sides clear of the notch', () => {
    expect(rule(shell, '.frame--rail')).toMatch(
      /grid-template-columns: calc\(var\(--rail-width\) \+ var\(--app-left-safe-area\)\) minmax\(0, 1fr\);/,
    );
    expect(rule(shell, '.frame__rail')).toMatch(
      /padding: var\(--app-top-safe-area\) 0 env\(safe-area-inset-bottom, 0px\) var\(--app-left-safe-area\);/,
    );
    expect(rule(shell, '.frame--rail .main')).toMatch(
      /padding-inline-end: max\(var\(--layout-gutter\), var\(--app-right-safe-area\)\);/,
    );
    expect(rule(shell, '.frame--phone .main')).toMatch(
      /padding-inline: max\(var\(--space-4\), var\(--app-left-safe-area\)\)\s+max\(var\(--space-4\), var\(--app-right-safe-area\)\);/,
    );
  });

  it('keeps the top bars and the sticky tops below the status bar', () => {
    expect(read('public-header/public-header.component.scss')).toMatch(
      /height: calc\(72px \+ var\(--app-top-safe-area, 0px\)\);\s+padding: var\(--app-top-safe-area, 0px\)/,
    );
    expect(read('../features/public-meeting/public-meeting.component.scss')).toMatch(
      /height: calc\(64px \+ var\(--app-top-safe-area, 0px\)\);/,
    );
    expect(read('../features/apply/status-timeline.component.scss')).toMatch(
      /top: var\(--app-top-safe-area, 0px\);/,
    );
    expect(read('../features/search/command-palette.component.scss')).toMatch(
      /top: calc\(var\(--space-4\) \+ var\(--app-top-safe-area, 0px\)\);/,
    );
  });
});
