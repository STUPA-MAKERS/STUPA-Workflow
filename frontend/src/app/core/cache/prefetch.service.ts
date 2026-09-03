import { Injectable, effect, inject } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { BudgetTreeApi } from '../../pages/budget/budget-tree.api';

/**
 * Warms the caches for reference data, once, after sign-in.
 *
 * Only the cost-centre tree so far, and it earns the place: it is one request for the
 * whole tree, five pages need it, and it changes only when someone edits a cost centre.
 * Fetching it while the reader is still looking at the dashboard means the budget,
 * bookings and applications pages paint their filter immediately instead of after a
 * round trip.
 *
 * Two rules keep a prefetch from being a tax on everyone:
 *
 * 1. **Only what the caller may see.** A prefetch for someone without budget access
 *    would spend a request to earn a 403.
 * 2. **Only once.** The effect runs on every signal change, so it guards itself; without
 *    that, a token refresh would refetch the tree for no reason.
 *
 * The result is not used here. It goes into the HTTP cache, and the page that needs it
 * finds it there.
 */
@Injectable({ providedIn: 'root' })
export class PrefetchService {
  private readonly auth = inject(AuthService);
  private readonly budgets = inject(BudgetTreeApi);
  private done = false;

  constructor() {
    effect(() => {
      if (this.done || !this.auth.isAuthenticated()) return;
      if (!this.canSeeBudgets()) return;
      this.done = true;
      // Failure is silent on purpose: nothing is waiting on this, and the page that
      // really needs the tree asks for it again and reports its own error.
      this.budgets.tree().subscribe({ error: () => undefined });
    });
  }

  private canSeeBudgets(): boolean {
    return (
      this.auth.canAny('budget.view', 'budget.structure', 'budget.book') ||
      this.auth.hasScopedBudgetView()
    );
  }
}
