/**
 * § NF/accessibility/conformance/000493: every shared component has a jest-axe test.
 *
 * A shared component appears on many pages, so one axe error repeats on each of them. This
 * spec reads the sources of `src/app/shared/` and of the ui-kit and finds each component
 * class. A component passes when its own spec calls `toHaveNoViolations`, or when another
 * spec that calls it names the class (the ui-kit `a11y.spec.ts` scans many primitives at
 * once).
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const FRONTEND = join(__dirname, '../../..');
const ROOTS = [
  'src/app/shared',
  'vendor/ui-kit/src',
  'vendor/ui-kit/shell',
  'vendor/ui-kit/markdown-editor',
  'vendor/ui-kit/markdown-view',
  'vendor/ui-kit/pwa',
];

const files = (root: string): readonly string[] =>
  (readdirSync(join(FRONTEND, root), { recursive: true }) as string[])
    .filter((f) => !f.includes('node_modules'))
    .map((f) => join(root, f));

const all = ROOTS.flatMap(files);
const read = (path: string): string => readFileSync(join(FRONTEND, path), 'utf8');

/** Every spec that runs axe, by path. */
const axeSpecs = new Map(
  all
    .filter((f) => f.endsWith('.spec.ts'))
    .map((f) => [f, read(f)] as const)
    .filter(([, src]) => src.includes('toHaveNoViolations')),
);

/** Every `@Component` class with the file that declares it. */
const components = all
  .filter((f) => f.endsWith('.ts') && !f.endsWith('.spec.ts'))
  .flatMap((f) =>
    [...read(f).matchAll(/@Component\(\{[\s\S]*?\}\)\s*export class (\w+)/g)].map((m) => ({
      file: f,
      cls: m[1],
    })),
  );

const covered = ({ file, cls }: { file: string; cls: string }): boolean =>
  axeSpecs.has(file.replace(/\.ts$/, '.spec.ts')) ||
  [...axeSpecs.values()].some((src) => new RegExp(`\\b${cls}\\b`).test(src));

describe('sharedComponentAxeContract', () => {
  it('finds the components of the app and of the ui-kit', () => {
    expect(components.length).toBeGreaterThan(80);
    expect(components.map((c) => c.cls)).toEqual(
      expect.arrayContaining(['ChatComponent', 'DialogComponent', 'MarkdownEditorComponent']),
    );
  });

  it('has an axe test for every shared component', () => {
    const missing = components.filter((c) => !covered(c)).map((c) => `${relative('.', c.file)} ${c.cls}`);
    expect(missing).toEqual([]);
  });
});
