/**
 * Meta line contract of the app templates (spec 001961). A line of parts with a middle dot
 * between two of them is an `app-meta-line` of the kit, which draws the dots. This spec reads
 * the HTML and fails on a dot that a template writes itself.
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

/** The line of each hand-written dot of `source`: an element that holds only a middle dot. */
export function handDots(source: string): readonly number[] {
  return Array.from(
    source.matchAll(/<(\w[\w-]*)\b[^>]*>\s*·\s*<\/\1>/g),
    (m) => source.slice(0, m.index).split('\n').length,
  );
}

describe('MetaLineTemplates', () => {
  it('finds an element that holds only a dot and passes a dot inside a text', () => {
    expect(handDots('<span>A</span>\n<span class="x__dot" aria-hidden="true">·</span>')).toEqual([
      2,
    ]);
    expect(handDots('<span aria-hidden="true"> · </span>')).toEqual([1]);
    expect(handDots('<span>A · B</span>')).toEqual([]);
    expect(handDots('<app-meta-line><span>A</span><span>B</span></app-meta-line>')).toEqual([]);
  });

  it('leaves the dots of every meta line to app-meta-line (001961)', () => {
    const offenders = htmlFiles(join(SRC, 'app')).flatMap((path) =>
      handDots(readFileSync(path, 'utf8')).map((line) => `${relative(SRC, path)}:${line}`),
    );
    expect(offenders).toEqual([]);
  });
});
