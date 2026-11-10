import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

/**
 * § 000632: an admin template shows a load through `app-load-state`. It holds no
 * `app-load-error`, and it holds `app-skeleton` only in a `#loading` template.
 *
 * A second test guards the trap of that template: the reference `#loading` hides a member
 * `loading` of the component in the whole template, so a call `loading()` fails at run time.
 */
const ROOT = __dirname;

function templates(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return templates(path);
    return name.endsWith('.html') ? [path] : [];
  });
}

/** The template without the content of its `#loading` templates. */
function withoutLoadingTemplates(html: string): string {
  let out = '';
  let rest = html;
  for (;;) {
    const start = rest.search(/<ng-template\s+#loading\s*>/);
    if (start < 0) return out + rest;
    out += rest.slice(0, start);
    rest = rest.slice(start);
    let depth = 0;
    const tag = /<(\/?)ng-template\b[^>]*>/g;
    let end = rest.length;
    for (let m = tag.exec(rest); m; m = tag.exec(rest)) {
      depth += m[1] ? -1 : 1;
      if (depth === 0) {
        end = m.index + m[0].length;
        break;
      }
    }
    rest = rest.slice(end);
  }
}

describe('AdminLoadState', () => {
  const files = templates(ROOT).map((path) => ({ name: relative(ROOT, path), html: readFileSync(path, 'utf8') }));

  it('finds the admin templates', () => {
    expect(files.length).toBeGreaterThan(30);
  });

  it('no admin template places app-load-error itself', () => {
    expect(files.filter((f) => f.html.includes('<app-load-error')).map((f) => f.name)).toEqual([]);
  });

  it('an admin template holds app-skeleton only in a #loading template', () => {
    const outside = files.filter((f) => withoutLoadingTemplates(f.html).includes('<app-skeleton'));
    expect(outside.map((f) => f.name)).toEqual([]);
  });

  it('a template with #loading does not call a member loading()', () => {
    const shadowed = files.filter((f) => /#loading\b/.test(f.html) && /(^|[^.\w])loading\(\)/.test(f.html));
    expect(shadowed.map((f) => f.name)).toEqual([]);
  });
});
