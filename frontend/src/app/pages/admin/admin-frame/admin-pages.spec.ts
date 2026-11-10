import { routes } from '../../../app.routes';
import { ADMIN_PAGES } from './admin-pages';

/** The child paths of the `/admin` route in `app.routes.ts`. */
function adminChildPaths(): readonly string[] {
  const shell = routes.find((r) => r.children?.some((c) => c.path === 'admin'));
  const admin = (shell?.children ?? routes).find((r) => r.path === 'admin');
  return (admin?.children ?? []).map((c) => c.path ?? '');
}

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
});
