import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { ToastService } from '@shared/ui/toast/toast.service';
import { I18nService } from '@core/i18n/i18n.service';
import { AuthService } from './auth.service';

/**
 * Schützt OIDC-Routen (overview §4). Ablauf:
 * 1. Principal sicher geladen (`ensureLoaded`, einmalig) → synchrone Entscheidung.
 * 2. Keine Session → OIDC-Login (Full-Redirect); Navigation abgebrochen.
 * 3. `route.data.permission` gesetzt, aber fehlt → 403-Seite (`/forbidden`, #71).
 *
 * RBAC ist hier reine UX; der Server bleibt autoritativ (security.md §2). Die
 * Entscheidung fällt **nach** dem Laden des echten Principals — kein blindes
 * Wegwerfen vor Perm-Auswertung.
 */
export const authGuard: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const toast = inject(ToastService);
  const i18n = inject(I18nService);

  return auth.ensureLoaded().pipe(
    map((principal) => {
      if (!principal) {
        auth.login();
        return false;
      }
      const permission = route.data['permission'] as string | string[] | undefined;
      const required = permission === undefined ? [] : ([] as string[]).concat(permission);
      if (required.length > 0 && !auth.canAny(...required)) {
        // Gremium-Mitglieder dürfen ihre Sitzungen sehen, auch ohne meeting.manage/
        // protocol.write (#sessions). Der Server scoped/autorisiert zusätzlich.
        const allowCommittee = route.data['allowCommitteeMember'] === true;
        if (allowCommittee && auth.gremien().length > 0) {
          return true;
        }
        // Delegations-Empfänger (#delegation-rework) können externe Nutzer ohne
        // Permission/Gremium sein — diese Routen lassen jeden Angemeldeten durch;
        // der Server bleibt autoritativ (Inhalt/403 kommen von dort).
        if (route.data['allowAuthenticated'] === true) {
          return true;
        }
        toast.error(i18n.translate('rbac.forbidden'));
        return router.createUrlTree(['/forbidden']);
      }
      return true;
    }),
  );
};
