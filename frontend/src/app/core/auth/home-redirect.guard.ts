import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { FeatureService } from '@core/features/feature.service';
import { from } from 'rxjs';
import { map, switchMap } from 'rxjs/operators';
import { AuthService } from './auth.service';

/**
 * Home-page switch. `/` is the public applicant landing page with a single apply
 * call to action. A logged-in user does not belong there. The guard sends that
 * user to the start page of a signed-in person: `/activity` (spec 001300), or
 * `/applications` while `Aktivität` is off (spec 000758). It waits for the feature
 * switches, so a stored state from an older config does not decide.
 *
 * It reuses `ensureLoaded()`, the one-time `/me` probe that the app start caches
 * with `shareReplay`. Without a session the landing page stays open. This is a
 * guard and not a redirect in the component, so the landing page does not flash.
 */
export const homeRedirectGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const features = inject(FeatureService);

  return auth.ensureLoaded().pipe(
    switchMap((principal) =>
      from(features.ready).pipe(
        map(() => (principal ? router.createUrlTree([features.home()]) : true)),
      ),
    ),
  );
};
