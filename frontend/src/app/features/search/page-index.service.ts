import { Injectable, computed, inject } from '@angular/core';
import type { Data, Routes } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { routeFeatures } from '@core/features/feature.guard';
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { routes } from '../../app.routes';

/** One navigable page, already resolved to a label the reader would recognise. */
export interface PageEntry {
  readonly path: string;
  readonly label: string;
  /** The section it sits under, for example "Verwaltung". Null at the top level. */
  readonly parentLabel: string | null;
}

/** A routed page that passed the filters, before its labels are read. */
interface PageCandidate {
  readonly path: string;
  readonly data: Data;
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
  private readonly features = inject(FeatureService);

  readonly visible = computed<readonly PageEntry[]>(() => {
    if (!this.auth.isAuthenticated()) return [];
    const found = this.collect(routes[0]?.children ?? [], '');
    const unique = found.filter((c, i) => found.findIndex((o) => o.path === c.path) === i);
    return unique.map((c) => this.entry(c));
  });

  /**
   * The pages of `list` below `prefix`, each child before its frame. A route with children
   * is a frame (the admin frame, the applications list): its children are pages too, at the
   * full path. A path can come twice; the first one counts.
   *
   * A parameterised route (`:id`) is a record view, which the record half of the search already
   * covers. A `contextual` route is left out, because it only means something after an action
   * carried the reader there: /status without an id renders "Antrag nicht gefunden".
   */
  private collect(list: Routes, prefix: string): readonly PageCandidate[] {
    return list.flatMap((route) => {
      const path = [prefix, route.path ?? ''].filter(Boolean).join('/');
      const data = route.data;
      const children = route.children ? this.collect(route.children, path) : [];
      const offered =
        !!data && this.features.isOn(...routeFeatures(route)) && this.offered(path, data);
      return offered ? [...children, { path: `/${path}`, data }] : children;
    });
  }

  /** A page of the palette: a plain path with a title, not contextual, and allowed. */
  private offered(path: string, data: Data): boolean {
    if (!path || path.includes(':') || !data['title']) return false;
    if (data['contextual'] === true) return false;
    return this.allowed(data);
  }

  /** The entry of a page, with the labels in the current language. */
  private entry({ path, data }: PageCandidate): PageEntry {
    const parent = (data['parent'] as string[] | undefined)?.[0];
    return {
      path,
      label: this.i18n.translate(data['title'] as never),
      parentLabel: parent ? this.i18n.translate(`nav.${parent}` as never) : null,
    };
  }

  /** The same decision `authGuard` makes, minus the redirect. */
  private allowed(data: Record<string, unknown>): boolean {
    const permission = data['permission'] as string | string[] | undefined;
    const required = permission === undefined ? [] : ([] as string[]).concat(permission);
    const gremiumPermission = data['gremiumPermission'] as string | string[] | undefined;
    const gremiumRequired =
      gremiumPermission === undefined ? [] : ([] as string[]).concat(gremiumPermission);
    if (required.length === 0 && gremiumRequired.length === 0) return true;
    if (required.length > 0 && this.auth.canAny(...required)) return true;
    if (gremiumRequired.some((p) => this.auth.canInAnyGremium(p))) return true;
    if (data['allowCommitteeMember'] === true && this.auth.gremien().length > 0) return true;
    if (data['allowScopedBudgetView'] === true && this.auth.hasScopedBudgetView()) return true;
    return data['allowAuthenticated'] === true;
  }
}
