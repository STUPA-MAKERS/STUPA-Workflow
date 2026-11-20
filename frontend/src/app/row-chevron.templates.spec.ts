/**
 * Row arrow contract of the app templates (spec 001962). The arrow of a row that opens a page,
 * and the arrow of a row that opens in place, is `app-row-chevron`. This spec reads the HTML
 * and fails on an arrow that a template draws itself with `app-icon`: a right arrow at the end
 * of a row, or a down arrow that a class turns while the row is open.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..');

function htmlFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return htmlFiles(path);
    return name.endsWith('.html') ? [path] : [];
  });
}

const ARROW = [
  // An icon with a class `…__chev` and a fixed right arrow.
  /<app-icon\b(?=[^>]*class="[^"]*__chev\b)(?=[^>]*\bname="right")[^>]*>/g,
  // A wrapper `…__chev` around a right arrow.
  /<span\b[^>]*class="[^"]*__chev\b[^"]*"[^>]*>\s*<app-icon\b[^>]*\bname="right"[^>]*>/g,
  // A down arrow that a class `…--open` turns.
  /<app-icon\b(?=[^>]*\bname="down")(?=[^>]*__chev--open)[^>]*>/g,
];

/** The line of each arrow of `source` that a template draws itself. */
export function handArrows(source: string): readonly number[] {
  return ARROW.flatMap((re) =>
    Array.from(source.matchAll(re), (m) => source.slice(0, m.index).split('\n').length),
  ).sort((a, b) => a - b);
}

describe('RowChevronTemplates', () => {
  it('finds a hand-drawn row arrow and passes app-row-chevron', () => {
    expect(
      handArrows('<span>A</span>\n<app-icon class="x__chev" name="right" [size]="17" />'),
    ).toEqual([2]);
    expect(
      handArrows('<span class="x__chev" aria-hidden="true">\n<app-icon name="right" /></span>'),
    ).toEqual([1]);
    expect(
      handArrows('<app-icon class="x__chev" [class.x__chev--open]="o" name="down" />'),
    ).toEqual([1]);
    expect(handArrows('<app-row-chevron [open]="o" />')).toEqual([]);
    // A tree turns its own arrow from right to down; a select keeps its caret.
    expect(handArrows(`<app-icon class="t__chev" [name]="o ? 'down' : 'right'" />`)).toEqual([]);
  });

  it('draws every row arrow with app-row-chevron (001962)', () => {
    const offenders = htmlFiles(join(SRC, 'app')).flatMap((path) =>
      handArrows(readFileSync(path, 'utf8')).map((line) => `${relative(SRC, path)}:${line}`),
    );
    expect(offenders).toEqual([]);
  });
});
