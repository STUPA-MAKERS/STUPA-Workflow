/**
 * Reflow contract (spec 000503): at 320 CSS px no view scrolls in two directions. jsdom
 * lays out nothing, so this spec reads the SCSS of the app and the ui-kit. A grid that
 * fills its row with `repeat(auto-fit | auto-fill, minmax(<length>, …))` keeps its minimum
 * column even when the container is narrower, and the page then scrolls sideways. The
 * minimum must therefore be `min(100%, <length>)`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOTS = [join(__dirname, '..'), join(__dirname, '../../vendor/ui-kit')];

function scssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    if (name === 'node_modules' || name === 'dist') return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return scssFiles(path);
    return name.endsWith('.scss') ? [path] : [];
  });
}

/** The auto-fit and auto-fill tracks of a stylesheet whose minimum is a bare length. */
function fixedMinimums(source: string): string[] {
  return [...source.matchAll(/repeat\(\s*auto-(?:fit|fill)\s*,\s*minmax\(\s*([^,]+?)\s*,/g)]
    .map((m) => m[1])
    .filter((min) => /^[\d.]+(rem|px|em|ch)$/.test(min));
}

describe('ReflowStyles', () => {
  it('clamps every auto-fit or auto-fill column minimum to the container width', () => {
    const found = ROOTS.flatMap(scssFiles).flatMap((file) =>
      fixedMinimums(readFileSync(file, 'utf8')).map((min) => `${relative(join(__dirname, '..'), file)}: ${min}`),
    );
    expect(found).toEqual([]);
  });

  it('finds a bare minimum and passes a clamped one', () => {
    expect(fixedMinimums('a { grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr)); }')).toEqual(['20rem']);
    expect(fixedMinimums('a { grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr)); }')).toEqual([]);
  });
});
