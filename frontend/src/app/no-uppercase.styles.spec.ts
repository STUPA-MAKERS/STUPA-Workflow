/**
 * No uppercase text in the app (spec 001964). A caption, a column head or a group label is in
 * sentence case, and a heading uses the title of `app-section` or the `.cap` class of the kit.
 * This spec reads every stylesheet of the app and fails on `text-transform: uppercase`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..');

function scssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return scssFiles(path);
    return name.endsWith('.scss') ? [path] : [];
  });
}

/** The line of each uppercase rule of `source`. */
export function uppercaseRules(source: string): readonly number[] {
  return Array.from(
    source.matchAll(/text-transform\s*:\s*uppercase/g),
    (m) => source.slice(0, m.index).split('\n').length,
  );
}

describe('NoUppercaseStyles', () => {
  it('finds an uppercase rule', () => {
    expect(uppercaseRules('.a {\n  text-transform: uppercase;\n}')).toEqual([2]);
    expect(uppercaseRules('.a { text-transform: none; }')).toEqual([]);
  });

  it('has no uppercase text in any stylesheet of the app (001964)', () => {
    const offenders = scssFiles(SRC).flatMap((path) =>
      uppercaseRules(readFileSync(path, 'utf8')).map((line) => `${relative(SRC, path)}:${line}`),
    );
    expect(offenders).toEqual([]);
  });
});
