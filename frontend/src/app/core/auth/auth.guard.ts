import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { ToastService } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { AuthService } from './auth.service';

/**
 * Protects OIDC routes. Flow:
 * 1. Principal safely loaded (`ensureLoaded`, once) → synchronous decision.
 * 2. No session → OIDC login (full redirect); navigation cancelled.
 * 3. `route.data.permission` set but missing → 403 page (`/forbidden`).
 *
 * RBAC here is pure UX; the server stays authoritative. The decision is made
 * after loading the real principal — no blind rejection before evaluating perms.
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
        // Gremium members may see their meetings even without meeting.manage/
        // protocol.write. The server additionally scopes/authorizes.
        const allowCommittee = route.data['allowCommitteeMember'] === true;
        if (allowCommittee && auth.gremien().length > 0) {
          return true;
        }
        // Gremium scope of the budget tab: members of a gremium with an assigned
        // cost centre see the tab without global budget.* rights; the server
        // returns ONLY the assigned subtrees.
        if (
          route.data['allowScopedBudgetView'] === true &&
          auth.hasScopedBudgetView()
        ) {
          return true;
        }
        // Delegation recipients can be external users without a permission/
        // gremium — these routes let any authenticated user through; the server
        // stays authoritative (content/403 come from there).
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
