import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * § 000637: a stylesheet of Verwaltung takes its container widths from `_widths.scss`. It
 * writes no `@container` rule by itself.
 */
const ROOT = __dirname;
const SHARED = '_widths.scss';

function stylesheets(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return stylesheets(path);
    return name.endsWith('.scss') && name !== SHARED ? [path] : [];
  });
}

describe('AdminContainerWidths', () => {
  it('the shared module holds the three widths', () => {
    const shared = readFileSync(join(ROOT, SHARED), 'utf8');
    expect(shared.match(/^\$\w+: [\d.]+rem;$/gm)).toEqual(['$fields: 34rem;', '$columns: 44rem;', '$wide: 56rem;']);
  });

  it('no admin stylesheet writes a container query by itself', () => {
    const own = stylesheets(ROOT).filter((path) => readFileSync(path, 'utf8').includes('@container'));
    expect(own.map((path) => relative(ROOT, path))).toEqual([]);
  });
});
