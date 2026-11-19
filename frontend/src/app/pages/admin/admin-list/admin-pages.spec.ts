import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { routes } from '../../../app.routes';
import { ADMIN_PAGES } from './admin-pages';

/**
 * The paths below `/admin` in `app.routes.ts`: the children of the list page and the two
 * editors beside it (spec 001442).
 */
function adminChildPaths(): readonly string[] {
  const shell = routes.find((r) => r.children?.some((c) => c.path === 'admin'));
  const siblings = shell?.children ?? routes;
  const admin = siblings.find((r) => r.path === 'admin');
  const editors = siblings
    .map((r) => r.path ?? '')
    .filter((p) => p.startsWith('admin/'))
    .map((p) => p.slice('admin/'.length));
  return [...(admin?.children ?? []).map((c) => c.path ?? ''), ...editors];
}

/**
 * Routes that show the component of another admin page, or a part that several pages share.
 * `texts` shows the branding editor, and the roles of a committee are in `gremium-roles`
 * beside the role matrix that the committees page uses too.
 */
const SHARED_FOLDERS: Readonly<Record<string, readonly string[]>> = {
  admin: ['admin-list'],
  texts: ['branding'],
  committees: ['committees', 'gremium-roles'],
};

describe('ADMIN_PAGES', () => {
  it('links every entry to a route below /admin, so no menu entry opens an empty page', () => {
    const paths = adminChildPaths();
    expect(paths.length).toBeGreaterThan(0);
    for (const page of ADMIN_PAGES) {
      expect([page.link, paths.includes(page.link)]).toEqual([page.link, true]);
    }
  });

  it('links the committees page with the English path (spec 000591)', () => {
    expect(ADMIN_PAGES.map((p) => p.link)).toContain('committees');
    expect(ADMIN_PAGES.map((p) => p.link)).not.toContain('gremien');
  });

  it('gives every entry its own icon (§ F/administration/admin/000638)', () => {
    const icons = ADMIN_PAGES.map((p) => p.icon);
    expect(icons.filter((icon, i) => icons.indexOf(icon) !== i)).toEqual([]);
  });

  it('keeps the component of an admin route in the folder of its route segment (§ S/frontend/angular/000639)', () => {
    const source = readFileSync(join(__dirname, '../../../app.routes.ts'), 'utf8');
    const admin = source.slice(source.indexOf("path: 'admin',"), source.indexOf("path: 'oauth/consent'"));
    // Each child route: its path, then the first lazy import after it.
    const pairs = [...admin.matchAll(/path: '([a-z-]+)[^']*',(?:(?!path: ')[\s\S])*?import\('\.\/pages\/admin\/([a-z-]+)\//g)].map(
      (m) => [m[1], m[2]],
    );
    expect(pairs.length).toBeGreaterThan(15);
    expect(pairs.filter(([segment, folder]) => segment !== folder && !SHARED_FOLDERS[segment]?.includes(folder))).toEqual([]);
  });
});
