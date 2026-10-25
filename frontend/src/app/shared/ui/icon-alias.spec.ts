/**
 * The app uses one name per icon: the canonical name of the ui-kit set, never an alias.
 *
 * The kit keeps older names (`add`, `delete`, `chevron-right`, `paperclip`, …) as aliases
 * of the same shape, so a template with `name="add"` renders the same plus as `name="plus"`.
 * Two names for one icon make a search for an icon miss half of its uses, so this spec
 * reads the alias table from the kit source and fails if an app template or TS file
 * passes an alias as an icon name.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const APP = join(__dirname, '../..');
const KIT_ICONS = join(__dirname, '../../../../vendor/ui-kit/src/lib/icon/icons.ts');

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
  );
}

/** The alias table of the kit: alias → canonical name. */
function kitAliases(): Map<string, string> {
  const src = readFileSync(KIT_ICONS, 'utf8');
  const body = /const ALIASES[^=]*=\s*\{([\s\S]*?)\};/.exec(src)?.[1] ?? '';
  return new Map(
    [...body.matchAll(/'?([\w-]+)'?\s*:\s*'([\w-]+)'/g)].map((m) => [m[1], m[2]] as const),
  );
}

/** The places where a file passes an icon name. */
function iconContexts(src: string): string[] {
  const patterns = [
    /<app-icon\b[^>]*>/g, // an icon tag, with `name="…"` or `[name]="… ? '…' : '…'"`
    /\[?\w*[iI]con\]?="[^"]*"/g, // an icon input of another component
    /\b\w*[iI]con\w*\??\s*:\s*'[\w-]+'/g, // a menu item or a tile: `icon: '…'`
    /<IconName>\(\s*'[\w-]+'\s*\)/g, // an input default
    /Record<[^>]*IconName>\s*=\s*\{[^}]*\}/g, // a lookup table
    /\):\s*IconName\s*\{[\s\S]*?\n\}/g, // a function that returns an icon
  ];
  return patterns.flatMap((p) => src.match(p) ?? []);
}

describe('icon names in the app', () => {
  const aliases = kitAliases();

  /** This is a sanity check: if the parser breaks, the check below passes for nothing. */
  it('reads the alias table of the kit', () => {
    expect(aliases.get('add')).toBe('plus');
    expect(aliases.get('chevron-right')).toBe('right');
    expect(aliases.get('paperclip')).toBe('clip');
  });

  it('finds icon names in the app', () => {
    expect(iconContexts(`<app-icon name="add" />`)).toEqual([`<app-icon name="add" />`]);
    expect(iconContexts(`{ id: 'x', icon: 'delete' }`)).toEqual([`icon: 'delete'`]);
  });

  it('no template or TS file uses an alias name', () => {
    const literal = /['"]([\w-]+)['"]/g;
    const hits: string[] = [];
    for (const f of files(APP)) {
      if (!/\.(html|ts)$/.test(f) || f.endsWith('.spec.ts')) continue;
      for (const ctx of iconContexts(readFileSync(f, 'utf8'))) {
        for (const m of ctx.matchAll(literal)) {
          const canonical = aliases.get(m[1]);
          if (canonical) hits.push(`${relative(APP, f)}: '${m[1]}' → '${canonical}'`);
        }
      }
    }
    expect(hits).toEqual([]);
  });
});
