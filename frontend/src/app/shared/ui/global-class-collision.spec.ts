/**
 * The global app stylesheet must not use a class name of a ui-kit component.
 *
 * The kit styles are encapsulated, but a global rule reaches into the kit templates. A
 * global `.seg` row group once set `flex-direction: column` on the root of the kit
 * Segmented control (`<div class="seg">`), and the options stacked vertically. jsdom does
 * not apply styles, so this spec compares the class names: it collects the BEM blocks that
 * the kit templates use and the class selectors in `src/styles.scss`.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const KIT_LIB = join(__dirname, '../../../../vendor/ui-kit/src/lib');
const GLOBAL_STYLES = join(__dirname, '../../../styles.scss');

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
  );
}

/** The block part of a BEM class: `seg__opt--on` → `seg`. */
const block = (cls: string) => cls.split(/__|--/)[0];

function kitBlocks(): Set<string> {
  const out = new Set<string>();
  for (const f of files(KIT_LIB)) {
    if (!f.endsWith('.html') && !f.endsWith('.component.ts')) continue;
    const src = readFileSync(f, 'utf8');
    for (const m of src.matchAll(/\bclass="([^"]*)"/g)) {
      for (const c of m[1].split(/\s+/).filter(Boolean)) out.add(block(c));
    }
    for (const m of src.matchAll(/\[class\.([\w-]+)\]/g)) out.add(block(m[1]));
  }
  return out;
}

function globalBlocks(): Set<string> {
  const src = readFileSync(GLOBAL_STYLES, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '');
  return new Set([...src.matchAll(/(?<![\w-])\.([a-zA-Z][\w-]*)/g)].map((m) => block(m[1])));
}

describe('global app classes and ui-kit classes', () => {
  const kit = kitBlocks();

  it('finds the kit blocks', () => {
    // A sanity check: if the parser breaks, the collision check below passes for nothing.
    expect(kit).toContain('seg');
    expect(kit).toContain('btn');
  });

  it('src/styles.scss uses no class block of a kit component', () => {
    const clashes = [...globalBlocks()].filter((b) => kit.has(b));
    expect(clashes).toEqual([]);
  });

  it('the row group is not called `.seg`', () => {
    expect(globalBlocks()).toContain('rowgroup');
    expect(globalBlocks()).not.toContain('seg');
  });
});
