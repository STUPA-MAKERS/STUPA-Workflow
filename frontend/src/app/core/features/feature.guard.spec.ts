import { TestBed } from '@angular/core/testing';
import type { PartialMatchRouteSnapshot, Route } from '@angular/router';
import { routes } from '../../app.routes';
import { featureMatch, routeFeatures } from './feature.guard';
import { FEATURES, type FeatureKey, FeatureService } from './feature.service';

const run = (...keys: FeatureKey[]) =>
  TestBed.runInInjectionContext(() => featureMatch(...keys)({} as Route, [], {} as PartialMatchRouteSnapshot)) as Promise<boolean>;

/** Every route of the app, flat. */
const flat = (list: readonly Route[]): readonly Route[] =>
  list.flatMap((route) => [route, ...flat(route.children ?? [])]);

/** Spec 000758: a route of a feature that is off shows "Seite nicht gefunden". */
describe('featureMatch', () => {
  afterEach(() => localStorage.clear());

  it('matches while every feature of the route is on', async () => {
    TestBed.inject(FeatureService).apply({});
    await expect(run('meetings', 'voting')).resolves.toBe(true);
  });

  it('does not match while one feature of the route is off', async () => {
    TestBed.inject(FeatureService).apply({ voting: false });
    await expect(run('meetings', 'voting')).resolves.toBe(false);
    await expect(run('meetings')).resolves.toBe(true);
  });

  it('waits for the site config', async () => {
    const features = TestBed.inject(FeatureService);
    const settled = jest.fn();
    const match = run('todos').then((value) => {
      settled();
      return value;
    });
    await Promise.resolve();
    expect(settled).not.toHaveBeenCalled();
    features.apply({ todos: false });
    await expect(match).resolves.toBe(false);
  });

  it('names its features for the page index', () => {
    expect(routeFeatures({ canMatch: [featureMatch('budget'), () => true] })).toEqual(['budget']);
    expect(routeFeatures({})).toEqual([]);
  });

  /** Push has no page of its own: it gates the push groups of the account page. */
  it.each(FEATURES.filter((key) => key !== 'push'))('guards at least one route of %s', (key) => {
    expect(flat(routes).some((route) => routeFeatures(route).includes(key))).toBe(true);
  });

  it.each([
    ['activity', ['activity']],
    ['graph', ['graph']],
    ['todos', ['todos']],
    ['calendar', ['calendar']],
    ['meetings', ['meetings']],
    ['voting', ['voting']],
    ['budget', ['budget']],
    ['expenses', ['budget']],
    ['invoices', ['invoices']],
    ['tickets', ['tickets']],
    ['protocols', ['meetings', 'public']],
    ['decisions', ['meetings', 'public']],
    ['public-calendar', ['calendar', 'public']],
  ] as const)('guards /%s', (path, keys) => {
    const found = flat(routes).filter(
      (route) => route.path === path && route.redirectTo === undefined,
    );
    expect(found.length).toBeGreaterThan(0);
    for (const route of found) expect(routeFeatures(route)).toEqual(keys);
  });
});
