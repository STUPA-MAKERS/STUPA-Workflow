/**
 * Every header view switch keeps one width (`_view-switch.scss`).
 *
 * A header view switch is the kit `app-segmented` with `size="control"`. The room for the
 * check mark comes from the mixin `keep-width`, which each of these components includes,
 * because a global rule must not use a class of the kit (`global-class-collision.spec.ts`).
 * jsdom applies no styles, so this spec reads the sources: each template with such a
 * switch has a stylesheet that includes the mixin, and the mixin reserves the width of the
 * check mark of the kit.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(__dirname, '../..');
const PARTIAL = join(__dirname, '_view-switch.scss');
const KIT_SEGMENTED = join(__dirname, '../../../../vendor/ui-kit/src/lib/segmented/segmented.component.html');

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)],
  );
}

/** The templates with an `app-segmented` element that has `size="control"`. */
function headerSwitchTemplates(): string[] {
  return files(APP).filter(
    (f) =>
      f.endsWith('.html') &&
      [...readFileSync(f, 'utf8').matchAll(/<app-segmented\b[^>]*>/g)].some((m) => /\bsize="control"/.test(m[0])),
  );
}

describe('header view switches', () => {
  it('include the mixin that keeps their width', () => {
    const templates = headerSwitchTemplates();
    // The todo board and the meeting overview have one each.
    expect(templates.length).toBeGreaterThanOrEqual(2);
    for (const html of templates) {
      const scss = readFileSync(html.replace(/\.html$/, '.scss'), 'utf8');
      expect({ html, uses: /@use '[./]*\/?(?:[\w-]+\/)*view-switch'/.test(scss) }).toEqual({ html, uses: true });
      expect({ html, includes: /@include \w+\.keep-width;/.test(scss) }).toEqual({ html, includes: true });
    }
  });

  it('reserve the width of the kit check mark on both sides', () => {
    const check = /<svg\s+class="seg__check"\s+width="(\d+)"/.exec(readFileSync(KIT_SEGMENTED, 'utf8'));
    expect(check).not.toBeNull();
    const partial = readFileSync(PARTIAL, 'utf8');
    expect(partial).toContain(`width: ${check![1]}px;`);
    expect(partial).toMatch(/\.seg__opt:not\(\.seg__opt--on\)::before,\s*\.seg__opt::after\s*\{/);
  });
});
