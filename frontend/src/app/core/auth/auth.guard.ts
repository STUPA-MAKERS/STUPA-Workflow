import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { ToastService } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { AuthService } from './auth.service';

/**
 * Protects OIDC routes. The flow:
 * 1. The guard loads the principal once through `ensureLoaded`. It then decides
 *    synchronously.
 * 2. If there is no session, the guard starts the OIDC login with a full redirect
 *    and cancels the navigation.
 * 3. If `route.data.permission` is set and the principal lacks it, the guard sends
 *    the user to the 403 page (`/forbidden`).
 *
 * RBAC here is only UX. The server stays authoritative. The guard decides after it
 * loads the real principal. It never rejects before it checks the permissions.
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
        // A gremium member may see the meetings of that gremium without
        // meeting.manage or protocol.write. The server also scopes and authorizes.
        const allowCommittee = route.data['allowCommitteeMember'] === true;
        if (allowCommittee && auth.gremien().length > 0) {
          return true;
        }
        // Gremium scope of the budget tab. A member of a gremium with an assigned
        // cost center sees the tab without global budget.* permissions. The
        // server returns ONLY the assigned subtrees.
        if (
          route.data['allowScopedBudgetView'] === true &&
          auth.hasScopedBudgetView()
        ) {
          return true;
        }
        // A delegation recipient can be an external user with no permission and no
        // gremium. These routes let any authenticated user through. The server
        // stays authoritative and returns the content or a 403.
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
