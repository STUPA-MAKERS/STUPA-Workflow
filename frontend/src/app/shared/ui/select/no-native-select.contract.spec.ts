/**
 * Every dropdown of the app opens the app's own option list (product decision,
 * 2026-10-16): a filter chip uses `app-filter-select`, a form field uses the app's
 * `app-select` (`SelectFieldComponent`). The browser's own list never shows.
 *
 * jsdom applies no styles, so this spec reads the sources. It fails when a template has a
 * native `<select>` or `<datalist>`, or when code imports the ui-kit `SelectComponent`,
 * which renders a native `<select>` under the same selector.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const APP = join(__dirname, '../../..');

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
  );
}

/** The source without comments, so a comment that names a tag does not count. */
function code(path: string): string {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    .replace(/<!--[\s\S]*?-->/g, '');
}

const sources = files(APP).filter(
  (f) => (f.endsWith('.html') || f.endsWith('.ts')) && !f.endsWith('.spec.ts'),
);

describe('no native select list', () => {
  it('finds the sources', () => {
    expect(sources.length).toBeGreaterThan(100);
  });

  it('has no native <select> or <datalist> in a template', () => {
    const hits = sources
      .filter((f) => /<(select|datalist)[\s>]/i.test(code(f)))
      .map((f) => relative(APP, f));
    expect(hits).toEqual([]);
  });

  it('never imports the ui-kit SelectComponent', () => {
    const kitImport = /import\s*\{[^}]*\bSelectComponent\b[^}]*\}\s*from\s*'@stupa-makers\/ui-kit'/;
    const hits = sources.filter((f) => kitImport.test(code(f))).map((f) => relative(APP, f));
    expect(hits).toEqual([]);
  });
});
