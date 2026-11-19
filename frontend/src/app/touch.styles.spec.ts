/**
 * Touch contract of the app styles. jsdom applies no styles, so this spec reads the SCSS.
 * On a touch screen a tap sets `:hover`, and the state stays until the next tap
 * elsewhere: every hover of the app therefore sits behind `@media (hover: hover)`. The
 * same rule for the ui-kit is in its `touch.spec.ts`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..');
const read = (rel: string): string => readFileSync(join(__dirname, rel), 'utf8');

function scssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return scssFiles(path);
    return name.endsWith('.scss') ? [path] : [];
  });
}

/** The selectors with `:hover` that no `@media (hover: hover)` block holds. */
function unguardedHovers(source: string): string[] {
  const text = source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
    .replace(/#\{[^}]*\}/g, 'x');
  const stack: string[] = [];
  const found: string[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '{') {
      const prelude = text.slice(start, i).trim();
      const guarded = stack.some((p) => /^@media\b[^{]*\(\s*hover\s*:\s*hover\s*\)/.test(p));
      if (!prelude.startsWith('@') && prelude.includes(':hover') && !guarded) found.push(prelude);
      stack.push(prelude);
      start = i + 1;
    } else if (c === '}') {
      stack.pop();
      start = i + 1;
    } else if (c === ';') {
      start = i + 1;
    }
  }
  return found;
}

describe('touch styles', () => {
  it('finds a hover outside the hover media query, also nested and in a list', () => {
    expect(unguardedHovers('.a:hover { color: red; }')).toEqual(['.a:hover']);
    expect(unguardedHovers('.a { &:hover { color: red; } }')).toEqual(['&:hover']);
    expect(unguardedHovers('@media (max-width: 767.98px) { .a:hover, .b { x: y; } }')).toEqual([
      '.a:hover, .b',
    ]);
    expect(unguardedHovers('@media (hover: hover) { .a:hover { x: y; } }')).toEqual([]);
    expect(unguardedHovers('.a { @media (hover: hover) { &:hover { x: y; } } }')).toEqual([]);
    expect(unguardedHovers('/* .a:hover { } */ .b { x: y; }')).toEqual([]);
  });

  it('puts every hover of the app behind @media (hover: hover)', () => {
    const offenders = scssFiles(SRC).flatMap((file) =>
      unguardedHovers(readFileSync(file, 'utf8')).map((s) => `${relative(SRC, file)}: ${s}`),
    );
    expect(offenders).toEqual([]);
  });

  /** The panes that scroll inside themselves keep their own overscroll. */
  it('stops the page bounce and the pull-to-refresh only in the installed app', () => {
    const styles = read('../styles.scss');
    expect(styles).toMatch(
      /@media \(display-mode: standalone\), \(display-mode: fullscreen\) \{\s*html,\s*body \{\s*overscroll-behavior-y: none;/,
    );
    expect(read('../../vendor/ui-kit/src/styles/_list-pane.scss')).toMatch(/overscroll-behavior: contain;/);
  });

  it('keeps the Markdown and the chat texts selectable on a touch screen', () => {
    expect(read('../styles.scss')).toMatch(
      /@media \(hover: none\) and \(pointer: coarse\) \{\s*\.mdv,\s*\.chat__text \{\s*@include press\.selectable;/,
    );
  });

  it('fades a tab panel in after a tab change', () => {
    expect(read('../styles.scss')).toMatch(
      /\[role='tabpanel'\]:not\(\[hidden\]\) \{\s*animation: motion-fade-in var\(--motion-base\)/,
    );
  });

  it('hides the bottom bar while a text field outside it has the focus and the keyboard is open', () => {
    const styles = read('../styles.scss');
    const rule = styles.slice(styles.indexOf('@media (pointer: coarse) {'));
    expect(rule).toMatch(/\.frame--phone\.frame--keyboard:has\(/);
    expect(rule).toMatch(/:not\(app-bottom-bar \*\):focus/);
    expect(rule).toMatch(/--app-bottom-inset: 0px;/);
    expect(rule).toMatch(/app-bottom-bar \{\s*display: none;/);
  });

  /** The pill ripples from its centre; the entry is the control. The kit shell draws both bars. */
  it.each([
    ['bottom bar', 'bottom-bar/bottom-bar.component.scss', 'bar-item'],
    ['navigation rail', 'nav-rail/nav-rail.component.scss', 'rail-item'],
  ])('gives the %s entries the ripple and keeps their labels unselectable', (_n, path, mixin) => {
    const kit = '../../vendor/ui-kit/shell/src/';
    const scss = read(kit + path);
    expect(scss).toContain("@use '../../../src/styles/press';");
    expect(scss).toContain("@use '../../../src/styles/nav-items';");
    expect(scss).toContain('@include press.chrome-text;');
    expect(scss).toContain(`@include nav-items.${mixin};`);
    const items = read('../../vendor/ui-kit/src/styles/_nav-items.scss');
    const body = items.slice(items.indexOf(`@mixin ${mixin}(`));
    expect(body).toContain('.#{$b}__item {\n    @include press.host;');
    const pressed = body.slice(body.indexOf('.#{$b}__item:active .#{$b}__ind::after,'));
    expect(pressed).toMatch(/^[\s\S]*?--ripple-r: 32px;\s*@include press\.paint;/);
  });

  /**
   * Nothing shrinks on press (001314). A press state of its own paints the ripple. An `:active` rule
   * that shows the grab cursor is no press: the canvas of the flow editor and the graph.
   */
  it('shrinks no pressed element of the app and paints the ripple in a press state of its own', () => {
    const files = [...scssFiles(SRC)];
    const scaled = files
      .filter((file) => /press-scale|scale var\(--motion-xs\)|\$scale/.test(readFileSync(file, 'utf8')))
      .map((file) => relative(SRC, file));
    expect(scaled).toEqual([]);
    const own = files
      .filter((file) => {
        const text = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
        return /:active\b/.test(text) && !text.includes('@include press.paint');
      })
      .map((file) => relative(SRC, file))
      .sort();
    expect(own).toEqual([
      'app/pages/admin/flow/flow-editor.component.scss',
      'app/pages/graph/graph-canvas.component.scss',
    ]);
  });

  it('gives the app cards and the page header actions the press and the chrome text', () => {
    expect(read('pages/home.component.scss')).toContain('@include press.press;');
    expect(read('features/todos/card-tile/todo-card-tile.component.scss')).toMatch(
      /:host\(:active\),\s*:host\(\[data-press-key\]\) \{\s*@include press\.paint;/,
    );
    expect(read('../styles.scss')).toMatch(/\.sheet-back-link \{[^}]*@include press\.press;/);
    expect(read('../../vendor/ui-kit/src/lib/page-header/page-header.component.scss')).toContain(
      '@include press.chrome-text;',
    );
  });
});
