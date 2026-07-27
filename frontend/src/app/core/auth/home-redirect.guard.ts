import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { AuthService } from './auth.service';

/**
 * Home-page switch. `/` is the public applicant landing page with a single apply
 * call to action. A logged-in user does not belong there. The guard sends that
 * user to `/dashboard`.
 *
 * It reuses `ensureLoaded()`, the one-time `/me` probe that the app start caches
 * with `shareReplay`. Without a session the landing page stays open. This is a
 * guard and not a redirect in the component, so the landing page does not flash.
 */
export const homeRedirectGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  return auth.ensureLoaded().pipe(
    map((principal) => (principal ? router.createUrlTree(['/dashboard']) : true)),
  );
};
