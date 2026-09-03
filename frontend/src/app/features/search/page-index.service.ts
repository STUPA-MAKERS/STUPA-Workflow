import { Injectable, computed, inject } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { routes } from '../../app.routes';

/** One navigable page, already resolved to a label the reader would recognise. */
export interface PageEntry {
  path: string;
  label: string;
  /** The section it sits under, for example "Verwaltung". Null at the top level. */
  parentLabel: string | null;
}

/**
 * The pages the current user may open, for the search palette.
 *
 * A user looking for "roles" means the settings page, not a record, and a palette that
 * only searched records would answer nothing. The list comes from the route table, so a
 * new page appears here the day it is routed and nobody has to remember a registry.
 *
 * The filter MIRRORS `authGuard`, including its three escape hatches. Getting that wrong
 * in the permissive direction would offer a page that then bounces to /forbidden, which
 * is worse than not offering it; getting it wrong the other way hides a page the user
 * has. The guard stays authoritative — this only decides what to show.
 */
@Injectable({ providedIn: 'root' })
export class PageIndexService {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  readonly visible = computed<PageEntry[]>(() => {
    if (!this.auth.isAuthenticated()) return [];
    const children = routes[0]?.children ?? [];
    const out: PageEntry[] = [];
    for (const route of children) {
      const path = route.path;
      const data = route.data;
      // A page needs a static path and a title. A parameterised route (`:id`) is a
      // record view, which the record half of the search already covers.
      if (!path || path.includes(':') || !data?.['title']) continue;
      // A `contextual` route only means something after an action carried the reader
      // there. Offering it is offering a dead end: /status without an id renders
      // "Antrag nicht gefunden", and /apply/confirmation congratulates the reader on a
      // submission that never happened.
      if (data['contextual'] === true) continue;
      if (!this.allowed(data)) continue;
      const parent = (data['parent'] as string[] | undefined)?.[0];
      out.push({
        path: `/${path}`,
        label: this.i18n.translate(data['title'] as never),
        parentLabel: parent ? this.i18n.translate(`nav.${parent}` as never) : null,
      });
    }
    return out;
  });

  /** The same decision `authGuard` makes, minus the redirect. */
  private allowed(data: Record<string, unknown>): boolean {
    const permission = data['permission'] as string | string[] | undefined;
    const required = permission === undefined ? [] : ([] as string[]).concat(permission);
    if (required.length === 0) return true;
    if (this.auth.canAny(...required)) return true;
    if (data['allowCommitteeMember'] === true && this.auth.gremien().length > 0) return true;
    if (data['allowScopedBudgetView'] === true && this.auth.hasScopedBudgetView()) return true;
    return data['allowAuthenticated'] === true;
  }
}
