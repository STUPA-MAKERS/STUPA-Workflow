import { Injectable, computed, inject } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import type { TranslationKey } from '@core/i18n/translations';
import type { IconName } from '@stupa-makers/ui-kit';

/**
 * The gremium permissions that open the voting pages. Casting is `vote.cast`. Running a
 * vote is `vote.manage`, or the meeting lead `session.manage`. All three are gremium
 * permissions: no global permission grants a voting right.
 */
export const VOTING_GREMIUM_PERMISSIONS = ['vote.cast', 'vote.manage', 'session.manage'];

/** The global permissions of the budget pages (budget, bookings, invoices). */
export const BUDGET_PERMISSIONS = ['budget.view', 'budget.structure', 'budget.book'];

/**
 * Every permission of an admin page. Each one opens the admin overview and shows the
 * "Verwaltung" entry. The list holds the permission of every entry of the admin
 * navigation (`ADMIN_PAGES`, a spec keeps the two in step) plus `admin.gremium_roles`,
 * whose pages the overview links per gremium.
 */
export const ADMIN_AREA_PERMISSIONS = [
  'admin.site',
  'admin.gremien',
  'admin.types',
  'admin.roles',
  'admin.users',
  'admin.group_mappings',
  'admin.gremium_roles',
  'admin.cd_variants',
  'admin.delegations',
  'admin.deadlines',
  'admin.notifications',
  'privacy.manage',
  'webhook.manage',
  'audit.read',
  'backup.manage',
  'budget.structure',
  'form.configure',
  'flow.configure',
];

/** The key of a navigation entry. */
export type NavKey =
  | 'start'
  | 'applications'
  | 'tasks'
  | 'meetings'
  | 'voting'
  | 'budget'
  | 'expenses'
  | 'invoices'
  | 'admin';

/** One entry of the navigation rail and of the phone bar. */
export interface NavItem {
  key: NavKey;
  path: string;
  labelKey: TranslationKey;
  icon: IconName;
  /** Visible when the principal has at least one of these permissions (empty = any session). */
  permissions: string[];
  /** Also visible with one of these gremium permissions in any gremium. */
  gremiumPermissions?: string[];
  /** Also visible to a member of any gremium. */
  inAnyCommittee?: boolean;
  /** Also visible with a scoped budget view. */
  scopedBudgetView?: boolean;
  /** Match the active route exactly. */
  exact?: boolean;
  /** `end` entries sit at the foot of the rail, after the spacer. */
  place: 'main' | 'end';
}

/**
 * The navigation of the app, in rail order. The route guards use the same permissions
 * (app.routes.ts), so an entry never leads to /forbidden.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  { key: 'start', path: '/dashboard', labelKey: 'shell.nav.start', icon: 'home', permissions: [], place: 'main' },
  // Without application.read these pages show only the applications and tasks of the user.
  { key: 'applications', path: '/applications', labelKey: 'nav.applications', icon: 'file', permissions: [], place: 'main' },
  { key: 'tasks', path: '/tasks', labelKey: 'nav.tasks', icon: 'tasks', permissions: [], place: 'main' },
  {
    key: 'meetings',
    path: '/meetings',
    labelKey: 'nav.meetings',
    icon: 'users',
    // Meetings are gremium business. The admin passes through `canInAnyGremium`. The
    // only global key is the read right `meeting.view_all`.
    permissions: ['meeting.view_all'],
    gremiumPermissions: ['session.manage', 'protocol.write'],
    inAnyCommittee: true,
    place: 'main',
  },
  {
    key: 'voting',
    path: '/voting',
    labelKey: 'nav.voting',
    icon: 'vote',
    permissions: [],
    gremiumPermissions: VOTING_GREMIUM_PERMISSIONS,
    place: 'main',
  },
  {
    key: 'budget',
    path: '/budget',
    labelKey: 'nav.budget',
    icon: 'pie',
    permissions: BUDGET_PERMISSIONS,
    // A gremium with an assigned cost centre sees the tab in scoped form.
    scopedBudgetView: true,
    place: 'main',
  },
  { key: 'expenses', path: '/expenses', labelKey: 'nav.expenses', icon: 'swap', permissions: BUDGET_PERMISSIONS, place: 'main' },
  { key: 'invoices', path: '/invoices', labelKey: 'nav.invoices', icon: 'receipt', permissions: BUDGET_PERMISSIONS, place: 'main' },
  { key: 'admin', path: '/admin', labelKey: 'nav.admin', icon: 'shield', permissions: ADMIN_AREA_PERMISSIONS, place: 'end' },
];

/** The entries of the phone bar. The other visible entries go into the "Mehr" sheet. */
export const BOTTOM_BAR_KEYS: readonly NavKey[] = ['start', 'applications', 'meetings', 'tasks'];

/**
 * The navigation entries the signed-in principal may open.
 *
 * The filter is UX only: the route guards and the server stay authoritative.
 */
@Injectable({ providedIn: 'root' })
export class NavService {
  private readonly auth = inject(AuthService);

  readonly visible = computed<NavItem[]>(() => {
    if (!this.auth.isAuthenticated()) return [];
    const inAnyCommittee = this.auth.gremien().length > 0;
    return NAV_ITEMS.filter(
      (item) =>
        this.globalAllows(item) ||
        (item.gremiumPermissions ?? []).some((p) => this.auth.canInAnyGremium(p)) ||
        (!!item.inAnyCommittee && inAnyCommittee) ||
        (!!item.scopedBudgetView && this.auth.hasScopedBudgetView()),
    );
  });

  /** The principal may see the meetings entry, so the rail asks for the live flag. */
  readonly meetingsVisible = computed(() => this.visible().some((i) => i.key === 'meetings'));

  /** Global permission part of the gate. An empty list opens the entry for every
   *  session, unless the entry is gated by gremium permissions instead. */
  private globalAllows(item: NavItem): boolean {
    if (item.permissions.length === 0) return !item.gremiumPermissions;
    return this.auth.canAny(...item.permissions);
  }
}
