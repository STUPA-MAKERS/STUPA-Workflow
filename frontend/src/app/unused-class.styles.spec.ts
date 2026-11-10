/**
 * No class without a use (§ S/frontend/angular/000636).
 *
 * A layout that a shared component replaced leaves its classes behind in the stylesheet of
 * the page. They read as if the page still had a look of its own, and they hide which rules
 * the page needs. jsdom applies no styles, so this spec reads the sources.
 *
 * A class with a block prefix (`block__element`) in a `*.component.scss` has a use when a
 * template or a TypeScript file of the same folder holds its name. A modifier
 * (`block__element--state`) also has a use when the folder builds the name from
 * `block__element--`. A class of another component, which the page styles from outside, has
 * a use when that component holds the name: its block is not a block of this folder, and a
 * source of the app or of the ui-kit holds the name.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';

const APP = __dirname;
const KIT = join(__dirname, '../../vendor/ui-kit');

/** Every file below `dir` that `keep` accepts. Build output and packages are left out. */
function walk(dir: string, keep: (name: string) => boolean): readonly string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (name === 'node_modules' || name === 'dist' || name.startsWith('.')) return [];
    if (statSync(path).isDirectory()) return walk(path, keep);
    return keep(name) ? [path] : [];
  });
}

const isSource = (name: string): boolean => name.endsWith('.html') || (name.endsWith('.ts') && !name.endsWith('.spec.ts'));

/** The templates and TypeScript files of one folder, as one text. */
function folderSource(dir: string): string {
  return readdirSync(dir)
    .filter(isSource)
    .map((name) => readFileSync(join(dir, name), 'utf8'))
    .join('\n');
}

/** The class names with a block prefix in a stylesheet, without its comments. */
function classesOf(scss: string): readonly string[] {
  const code = scss.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  return [...new Set([...code.matchAll(/\.([a-zA-Z]\w*__[\w-]+)/g)].map((m) => m[1]))].sort();
}

/** The name itself, or for a modifier the stem that the source builds the name from. */
function holds(source: string, name: string): boolean {
  return source.includes(name) || (name.includes('--') && source.includes(`${name.split('--')[0]}--`));
}

describe('ComponentStylesheets', () => {
  const everywhere = [...walk(APP, isSource), ...walk(KIT, isSource)].map((path) => readFileSync(path, 'utf8')).join('\n');
  const sheets = walk(APP, (name) => name.endsWith('.component.scss'));

  it('finds the stylesheets of the app', () => {
    expect(sheets.length).toBeGreaterThan(100);
  });

  it('hold no class without a use', () => {
    const unused = sheets.flatMap((sheet) => {
      const own = folderSource(dirname(sheet));
      return classesOf(readFileSync(sheet, 'utf8'))
        .filter((name) => !holds(own, name) && (own.includes(`${name.split('__')[0]}__`) || !holds(everywhere, name)))
        .map((name) => `${relative(APP, sheet)}: .${name}`);
    });
    expect(unused).toEqual([]);
  });

  it('reports a class that only a comment or another stylesheet names', () => {
    expect(classesOf('// .old__row was here\n.new__row { color: red; }\n/* .old__cell */')).toEqual(['new__row']);
    expect(holds('<li class="new__row">', 'new__row')).toBe(true);
    expect(holds("[class]=\"'new__row--' + state\"", 'new__row--open')).toBe(true);
    expect(holds('<li class="new__row">', 'old__row')).toBe(false);
  });
});
