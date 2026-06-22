import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { AuthService } from './auth.service';

/**
 * Startseiten-Weiche: `/` ist die öffentliche Applicant-Landeseite (ein Antrags-CTA).
 * Angemeldete Nutzer:innen haben dort nichts zu suchen → Redirect auf `/dashboard`.
 *
 * Reuse von `ensureLoaded()` (einmaliger, `shareReplay`-gecachter `/me`-Probe, beim
 * App-Start gesetzt); ohne Session bleibt die Landeseite offen. Als Guard (statt
 * Redirect in der Komponente), damit die Landeseite nicht kurz aufblitzt.
 */
export const homeRedirectGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  return auth.ensureLoaded().pipe(
    map((principal) => (principal ? router.createUrlTree(['/dashboard']) : true)),
  );
};
