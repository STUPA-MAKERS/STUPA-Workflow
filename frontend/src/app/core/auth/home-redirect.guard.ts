import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { AuthService } from './auth.service';

/**
 * Home-page switch: `/` is the public applicant landing page (a single apply CTA).
 * Logged-in users have no business there → redirect to `/dashboard`.
 *
 * Reuses `ensureLoaded()` (the one-time, `shareReplay`-cached `/me` probe set at
 * app start); without a session the landing page stays open. Done as a guard
 * (rather than a redirect in the component) so the landing page does not flash.
 */
export const homeRedirectGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  return auth.ensureLoaded().pipe(
    map((principal) => (principal ? router.createUrlTree(['/dashboard']) : true)),
  );
};
