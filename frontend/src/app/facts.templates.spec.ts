/**
 * Fact list contract of the app templates (spec 001965). A list of label and value pairs is a
 * `<dl appFacts>` of the kit. This spec reads the HTML and fails on a `<dl>` that styles
 * itself, except the tallies and figures that 001965 leaves out.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..');

/** The classes of the number blocks that are not fact lists (vote tallies, money figures). */
const NOT_FACTS = ['vc__counts', 'mtg__tally', 'bd__figs', 'fd__figs', 'id__amounts', 'tcd__fields'];

function htmlFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return htmlFiles(path);
    return name.endsWith('.html') ? [path] : [];
  });
}

/** The line of each `<dl>` of `source` that is neither `appFacts` nor a number block. */
export function handLists(source: string): readonly number[] {
  return Array.from(source.matchAll(/<dl\b[^>]*>/g))
    .filter((m) => !/\bappFacts\b/.test(m[0]) && !NOT_FACTS.some((c) => new RegExp(`\\b${c}\\b`).test(m[0])))
    .map((m) => source.slice(0, m.index).split('\n').length);
}

describe('FactsTemplates', () => {
  it('finds a dl with its own style and passes appFacts and the number blocks', () => {
    expect(handLists('<div>\n<dl class="x__facts"><dt>A</dt><dd>B</dd></dl>')).toEqual([2]);
    expect(handLists('<dl appFacts layout="rows"><dt>A</dt><dd>B</dd></dl>')).toEqual([]);
    expect(handLists('<dl class="bd__figs"></dl>')).toEqual([]);
  });

  it('draws every fact list with appFacts (001965)', () => {
    const offenders = htmlFiles(join(SRC, 'app')).flatMap((path) =>
      handLists(readFileSync(path, 'utf8')).map((line) => `${relative(SRC, path)}:${line}`),
    );
    expect(offenders).toEqual([]);
  });
});
