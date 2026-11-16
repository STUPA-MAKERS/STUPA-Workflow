import { inject } from '@angular/core';
import type { CanMatchFn, Route } from '@angular/router';
import { type FeatureKey, FeatureService } from './feature.service';

/**
 * The features of each guard that `featureMatch` built. The page index of the command
 * palette reads it through `routeFeatures`, because a guard is a function and names nothing.
 */
const GUARD_FEATURES = new WeakMap<CanMatchFn, readonly FeatureKey[]>();

/**
 * Match a route only while every one of `keys` is on.
 *
 * A route that does not match falls through to the catch-all route, so a page of a feature
 * that is off shows "Seite nicht gefunden". The guard waits for the site config, because a
 * deep link arrives before the config.
 */
export function featureMatch(...keys: readonly FeatureKey[]): CanMatchFn {
  const guard: CanMatchFn = async () => {
    const features = inject(FeatureService);
    await features.ready;
    return features.isOn(...keys);
  };
  GUARD_FEATURES.set(guard, keys);
  return guard;
}

/** The features that the route needs: the keys of its `featureMatch` guards. */
export function routeFeatures(route: Route): readonly FeatureKey[] {
  return (route.canMatch ?? []).flatMap(
    (guard) => GUARD_FEATURES.get(guard as CanMatchFn) ?? [],
  );
}
