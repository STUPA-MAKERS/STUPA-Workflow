/**
 * No page may answer a pending load with a bare sentence.
 *
 * This has been reported four times, each time for a different page, because each fix
 * covered the pages that were named and the next one to be noticed was a page nobody had
 * looked at yet. The check is on the source, so it catches the next one at review time
 * rather than in production.
 *
 * A page loading is not a message. It is a shape, and either `app-skeleton` or
 * `app-data-table` (which draws its own skeleton rows) has to draw it.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join } from 'node:path';

const PAGES_ROOT = join(__dirname, '..', '..', '..', 'pages');
const FEATURES_ROOT = join(__dirname, '..', '..', '..', 'features');

/**
 * Templates that answer a load with text on purpose.
 *
 * The palette is the only one: it is a 400px-tall overlay whose result list is the whole
 * body, and a skeleton there flashes on every keystroke.
 */
const ALLOWED = ['command-palette.component.html'];

function templates(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...templates(full));
    else if (extname(entry) === '.html') out.push(full);
  }
  return out;
}

/** A template that reads `loading()` and draws no placeholder of any kind. */
function withoutPlaceholder(): string[] {
  return [...templates(PAGES_ROOT), ...templates(FEATURES_ROOT)].filter((file) => {
    if (ALLOWED.some((a) => file.endsWith(a))) return false;
    const src = readFileSync(file, 'utf8');
    if (!/\bloading\w*\(\)/.test(src)) return false;
    return !/app-skeleton|app-data-table|skel/.test(src);
  });
}

/** A table that never says it is loading shows its empty text while the request is out. */
function tablesWithoutLoading(): string[] {
  return [...templates(PAGES_ROOT), ...templates(FEATURES_ROOT)].filter((file) => {
    const src = readFileSync(file, 'utf8');
    return src.includes('<app-data-table') && !/\[loading\]/.test(src);
  });
}

describe('loading placeholders', () => {
  it('every page that loads draws a shape rather than a sentence', () => {
    expect(withoutPlaceholder()).toEqual([]);
  });

  it('every table says when it is loading', () => {
    // Without `[loading]` the table renders its empty text — "no roles", "no results" —
    // while the request is still out, which asserts there is nothing when nothing has
    // arrived yet. Seven pages had this and none of them was reported; they were simply
    // fast enough that nobody caught the flash.
    expect(tablesWithoutLoading()).toEqual([]);
  });
});
