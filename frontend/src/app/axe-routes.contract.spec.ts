/**
 * § NF/accessibility/conformance/000491: the axe sweep of the e2e suite visits every route.
 *
 * The sweep reads its routes from `e2e/axe-routes.ts`. This spec walks the router config and
 * finds each route that shows a page, so a new route without an axe check fails here and
 * not first in a real browser. A redirect shows no page of its own.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { Route } from '@angular/router';
import { routes } from './app.routes';

const join2 = (base: string, path: string): string => [base, path].filter((p) => p !== '').join('/');

const pages = (list: readonly Route[], base = ''): readonly string[] =>
  list.flatMap((r) => {
    if (r.redirectTo !== undefined) return [];
    const full = join2(base, r.path ?? '');
    const own = r.component || r.loadComponent ? [full] : [];
    return [...own, ...pages(r.children ?? [], full)];
  });

const table = readFileSync(join(__dirname, '../../e2e/axe-routes.ts'), 'utf8');
const listed = new Set([...table.matchAll(/(?:fixed\(|path: )'([^']*)'/g)].map((m) => m[1]));

describe('axeRouteSweep', () => {
  it('lists every page route of the app in the e2e axe sweep', () => {
    const all = [...new Set(pages(routes))];
    expect(all.length).toBeGreaterThan(60);
    expect(all.filter((p) => !listed.has(p))).toEqual([]);
  });

  it('lists no route that the app does not have', () => {
    const all = new Set(pages(routes));
    expect([...listed].filter((p) => !all.has(p))).toEqual([]);
  });
});
