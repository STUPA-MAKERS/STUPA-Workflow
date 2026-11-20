/**
 * §ui-kit:NF/accessibility/conformance/000491: the axe sweep of the e2e suite visits every route.
 *
 * The sweep reads its routes from `e2e/axe-routes.ts`. `axeRouteGaps` of the kit walks the
 * router config, so a new route without an axe check fails here and not first in a real
 * browser.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { axeRouteGaps, pageRoutes } from '@stupa-makers/ui-kit/shell';
import { routes } from './app.routes';

const table = readFileSync(join(__dirname, '../../e2e/axe-routes.ts'), 'utf8');
const listed = [...table.matchAll(/(?:fixed\(|path: )'([^']*)'/g)].map((m) => m[1] ?? '');

describe('axeRouteSweep', () => {
  it('has the page routes of the app', () => {
    expect(pageRoutes(routes).length).toBeGreaterThan(60);
  });

  it('lists every page route of the app in the e2e axe sweep', () => {
    expect(axeRouteGaps(routes, listed).missing).toEqual([]);
  });

  it('lists no route that the app does not have', () => {
    expect(axeRouteGaps(routes, listed).unknown).toEqual([]);
  });
});
