/**
 * Focus ring contract of the app and the ui-kit styles (spec 000508). jsdom applies no
 * styles, so this spec reads the SCSS.
 *
 * A rule may remove the outline only in one of these cases:
 * - the browser's mouse focus (`:focus:not(:focus-visible)`), which needs no ring;
 * - the stylesheet draws its own 2px ring in the focus colour (`--color-focus-ring`, or a
 *   mixin of the kit that draws it: the field box, the option menu);
 * - the target takes the focus only from the script (`tabindex="-1"`): a heading or a
 *   pane that the route focus or a dialog moves to. These are listed below with a reason.
 *
 * The e2e run checks the ring itself on every route; this spec stops a new removal early.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = join(__dirname, '..', '..');
const DIRS = [join(ROOT, 'src'), join(ROOT, 'vendor', 'ui-kit', 'src')];

/** A ring of its own: the token, or a kit mixin that draws one. */
const DRAWS_RING = /--color-focus-ring|@include\s+(?:f\.box|om\.option-focus|field\.box)\b/;

/** Removals on targets that only the script focuses, by file and selector. */
const SCRIPT_TARGETS: Readonly<Record<string, readonly string[]>> = {
  // The heading of the bar and the edited text: the route focus and the edit mode focus them.
  'src/app/features/apply/status-timeline.component.scss': ['.sp__title:focus,\n.sp__editText strong:focus'],
  // The section that a deep link scrolls to and focuses.
  'src/app/pages/admin/help-tickets/help-tickets.component.scss': ['.ht__sec:focus'],
  'src/app/pages/applications/applications-detail.component.scss': ['.ad__sec:focus'],
  // The detail pane and the sheet take the focus on open when nothing in them can.
  'vendor/ui-kit/src/lib/list-detail/list-detail-layout.component.scss': ['.ld__detail:focus'],
  'vendor/ui-kit/src/lib/side-sheet/side-sheet.component.scss': ['.ss:focus'],
  // The viewer root takes the focus when it has no control; its controls draw `--fv-focus`.
  'vendor/ui-kit/src/lib/file-viewer/file-viewer.component.scss': ['.fv'],
};

function scssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === 'node_modules' ? [] : scssFiles(path);
    return name.endsWith('.scss') ? [path] : [];
  });
}

/** The selector of every rule that sets `outline: none` or `outline: 0`. */
export function outlineRemovals(source: string): string[] {
  const text = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '');
  return Array.from(text.matchAll(/(?:^|[;{\s])outline\s*:\s*(?:none|0)\s*(?:!important\s*)?[;}]/g)).map((m) => {
    let depth = 0;
    let open = m.index;
    while (open > 0) {
      open--;
      if (text[open] === '}') depth++;
      else if (text[open] === '{' && depth-- === 0) break;
    }
    const before = text.slice(0, open);
    return before.slice(Math.max(before.lastIndexOf('}'), before.lastIndexOf(';'), before.lastIndexOf('{')) + 1).trim();
  });
}

describe('FocusRingStyles', () => {
  it('finds a removal with its selector, nested or not', () => {
    expect(outlineRemovals('.a:focus { outline: none; }')).toEqual(['.a:focus']);
    expect(outlineRemovals('.a { color: red; &:focus { outline: 0; } }')).toEqual(['&:focus']);
    expect(outlineRemovals('.a { outline: 2px solid red; outline-offset: 0; }')).toEqual([]);
    expect(outlineRemovals('/* .a { outline: none; } */ .b { x: y; }')).toEqual([]);
  });

  it('removes an outline only for the mouse focus, under a ring of its own or on a script target', () => {
    const offenders = DIRS.flatMap(scssFiles).flatMap((path) => {
      const rel = relative(ROOT, path);
      const source = readFileSync(path, 'utf8');
      if (DRAWS_RING.test(source)) return [];
      return outlineRemovals(source)
        .filter((selector) => !/:focus:not\(:focus-visible\)/.test(selector))
        .filter((selector) => !(SCRIPT_TARGETS[rel] ?? []).includes(selector))
        .map((selector) => `${rel}: ${selector}`);
    });
    expect(offenders).toEqual([]);
  });
});
