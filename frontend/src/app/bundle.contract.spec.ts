/**
 * The split of the bundles (spec 002003). jsdom builds nothing, so this spec reads the
 * sources: the Markdown editor (tiptap, KaTeX) stays behind the `@defer` of the TOP sheet,
 * the DE texts stay in their own chunk, and the build budgets hold both sizes.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const FRONTEND = join(__dirname, '..', '..');
const APP = join(FRONTEND, 'src', 'app');
const read = (path: string): string => readFileSync(path, 'utf8');

function tsFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return tsFiles(path);
    return name.endsWith('.ts') && !name.endsWith('.spec.ts') ? [path] : [];
  });
}

/** The import statements of a source that bring values, not only types. */
function valueImports(source: string, from: string): string[] {
  const statements = source.match(/import\s[^;]*?from\s+'[^']+';/g) ?? [];
  return statements.filter((s) => s.endsWith(`'${from}';`) && !/^import\s+type\s/.test(s));
}

describe('bundleContract', () => {
  it('imports values of the Markdown editor only in the TOP sheet of the kit, which defers it', () => {
    const offenders = tsFiles(APP)
      .filter((file) => valueImports(read(file), '@stupa-makers/ui-kit/markdown-editor').length > 0)
      .map((file) => relative(APP, file));
    expect(offenders).toEqual([]);
    const kitSheet = join(FRONTEND, 'vendor', 'ui-kit', 'views', 'protocol', 'src', 'top-sheet-view.component');
    expect(valueImports(read(`${kitSheet}.ts`), '@stupa-makers/ui-kit/markdown-editor')).toHaveLength(1);
    expect(read(`${kitSheet}.html`)).toContain('@defer (on immediate)');
  });

  it('keeps the DE texts out of the main bundle', () => {
    const translations = read(join(APP, 'core', 'i18n', 'translations.ts'));
    expect(valueImports(translations, './catalog/de.json')).toEqual([]);
  });

  it('holds the meeting chunk and the start bundle under their budgets', () => {
    const angular = JSON.parse(read(join(FRONTEND, 'angular.json'))) as {
      projects: Record<
        string,
        { architect: { build: { configurations: Record<string, { budgets?: { type: string; name?: string; maximumError: string }[] }> } } }
      >;
    };
    const budgets = Object.values(angular.projects).flatMap((p) => p.architect.build.configurations['production']?.budgets ?? []);
    expect(budgets).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ type: 'initial', maximumError: '1MB' }),
        expect.objectContaining({ type: 'bundle', name: 'meetings-component', maximumError: '700kB' }),
      ]),
    );
  });
});
