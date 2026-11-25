import { Injectable, computed, inject } from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { type FeatureKey, FeatureService } from '@core/features/feature.service';
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

/** The global permissions of the page "Bestellungen". */
export const ORDER_PERMISSIONS = ['order.manage', 'budget.view'];

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
  'admin.translations',
  'admin.notifications',
  'privacy.manage',
  'webhook.manage',
  'admin.calendars',
  'admin.features',
  'admin.paperless',
  'ticket.manage',
  'audit.read',
  'backup.manage',
  'budget.structure',
  'form.configure',
  'flow.configure',
];

/** The key of a navigation entry. */
export type NavKey =
  | 'applications'
  | 'tasks'
  | 'activity'
  | 'graph'
  | 'todos'
  | 'calendar'
  | 'meetings'
  | 'gremien'
  | 'voting'
  | 'budget'
  | 'expenses'
  | 'invoices'
  | 'orders'
  | 'tickets'
  | 'protocols'
  | 'decisions'
  | 'publicCalendar'
  | 'admin';

/** One entry of the navigation rail and of the phone bar. */
export interface NavItem {
  readonly key: NavKey;
  readonly path: string;
  readonly labelKey: TranslationKey;
  readonly icon: IconName;
  /** Visible when the principal has at least one of these permissions (empty = any session). */
  readonly permissions: readonly string[];
  /** Also visible with one of these gremium permissions in any gremium. */
  readonly gremiumPermissions?: readonly string[];
  /** Also visible to a member of any gremium. */
  readonly inAnyCommittee?: boolean;
  /** Also visible with a scoped budget view. */
  readonly scopedBudgetView?: boolean;
  /** Also visible to a principal who reported a ticket. */
  readonly reportedTickets?: boolean;
  /** Match the active route exactly. */
  readonly exact?: boolean;
  /**
   * The feature of the entry, or the features of a page that needs several: a public page
   * needs `public` and the feature of its records. The entry does not show while one is off.
   */
  readonly feature?: FeatureKey | readonly FeatureKey[];
  /** `end` entries sit at the foot of the rail, after the spacer. */
  readonly place: 'main' | 'end';
  /** The collapsible group of the entry: `public` is "Öffentlich" (spec 001303). */
  readonly group?: 'public';
}

/**
 * The navigation of the app, in rail order. The route guards use the same permissions
 * (app.routes.ts), so an entry never leads to /forbidden.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  /** The start page: the events of the own items (specs 001270, 001300); every session has it. */
  { key: 'activity', path: '/activity', labelKey: 'nav.activity', icon: 'history', permissions: [], feature: 'activity', place: 'main' },
  /** Without `application.read` these pages show only the applications and tasks of the user. */
  { key: 'applications', path: '/applications', labelKey: 'nav.applications', icon: 'file', permissions: [], place: 'main' },
  { key: 'tasks', path: '/tasks', labelKey: 'nav.tasks', icon: 'tasks', permissions: [], place: 'main' },
  /** Every session has at least the personal board. */
  { key: 'todos', path: '/todos', labelKey: 'nav.todos', icon: 'circleok', permissions: [], feature: 'todos', place: 'main' },
  { key: 'calendar', path: '/calendar', labelKey: 'nav.calendar', icon: 'cal', permissions: [], feature: 'calendar', place: 'main' },
  {
    key: 'meetings',
    path: '/meetings',
    labelKey: 'nav.meetings',
    icon: 'users',
    /**
     * Meetings are gremium business. The admin passes through `canInAnyGremium`. The only
     * global key is the read right `meeting.view_all`.
     */
    permissions: ['meeting.view_all'],
    gremiumPermissions: ['session.manage', 'protocol.write'],
    inAnyCommittee: true,
    feature: 'meetings',
    place: 'main',
  },
  {
    key: 'gremien',
    path: '/committees',
    labelKey: 'nav.gremien',
    icon: 'landmark',
    /** A member sees the own gremien; `gremium.view_all` (and the admin) sees every one. */
    permissions: ['gremium.view_all'],
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
    feature: 'voting',
    place: 'main',
  },
  {
    key: 'budget',
    path: '/budget',
    labelKey: 'nav.budget',
    icon: 'pie',
    permissions: BUDGET_PERMISSIONS,
    /** A gremium with an assigned cost centre sees the tab in scoped form. */
    scopedBudgetView: true,
    feature: 'budget',
    place: 'main',
  },
  { key: 'expenses', path: '/expenses', labelKey: 'nav.expenses', icon: 'swap', permissions: BUDGET_PERMISSIONS, feature: 'budget', place: 'main' },
  { key: 'invoices', path: '/invoices', labelKey: 'nav.invoices', icon: 'receipt', permissions: BUDGET_PERMISSIONS, feature: 'invoices', place: 'main' },
  { key: 'orders', path: '/orders', labelKey: 'nav.orders', icon: 'package', permissions: ORDER_PERMISSIONS, feature: 'orders', place: 'main' },
  { key: 'tickets', path: '/tickets', labelKey: 'nav.tickets', icon: 'ticket', permissions: ['ticket.manage'], reportedTickets: true, feature: 'tickets', place: 'main' },
  /** The graph of the elements and their relations (specs 001420, 001421). */
  { key: 'graph', path: '/graph', labelKey: 'nav.graph', icon: 'shapes', permissions: ['graph.view'], feature: 'graph', place: 'main' },
  /**
   * The public pages, for a signed-in person (spec 001303): the public start page `/` holds
   * the only other links to them, and it leads a session to the activity page. They form
   * the group "Öffentlich" at the end of the main entries; a page shows only while its
   * feature is on.
   */
  { key: 'protocols', path: '/protocols', labelKey: 'nav.public.protocols', icon: 'file', permissions: [], feature: ['meetings', 'public'], place: 'main', group: 'public' },
  { key: 'decisions', path: '/decisions', labelKey: 'nav.public.decisions', icon: 'vote', permissions: [], feature: ['meetings', 'public'], place: 'main', group: 'public' },
  { key: 'publicCalendar', path: '/public-calendar', labelKey: 'nav.public.calendar', icon: 'cal', permissions: [], feature: ['calendar', 'public'], place: 'main', group: 'public' },
  { key: 'admin', path: '/admin', labelKey: 'nav.admin', icon: 'shield', permissions: ADMIN_AREA_PERMISSIONS, place: 'end' },
];

/** The features of an entry: none, one or several. */
export function featuresOf(item: Pick<NavItem, 'feature'>): readonly FeatureKey[] {
  const { feature } = item;
  if (feature === undefined) return [];
  return typeof feature === 'string' ? [feature] : feature;
}

/** The entries of the phone bar. The other visible entries go into the "Mehr" sheet. */
export const BOTTOM_BAR_KEYS: readonly NavKey[] = ['activity', 'applications', 'meetings', 'tasks'];

/**
 * The navigation entries the signed-in principal may open.
 *
 * An entry of a feature that is off does not show. The filter is UX only: the route guards
 * and the server stay authoritative.
 */
@Injectable({ providedIn: 'root' })
export class NavService {
  private readonly auth = inject(AuthService);
  private readonly features = inject(FeatureService);

  readonly visible = computed<NavItem[]>(() => {
    if (!this.auth.isAuthenticated()) return [];
    const inAnyCommittee = this.auth.gremien().length > 0;
    return NAV_ITEMS.filter((item) => this.features.isOn(...featuresOf(item))).filter(
      (item) =>
        this.globalAllows(item) ||
        (item.gremiumPermissions ?? []).some((p) => this.auth.canInAnyGremium(p)) ||
        (!!item.inAnyCommittee && inAnyCommittee) ||
        (!!item.scopedBudgetView && this.auth.hasScopedBudgetView()) ||
        (!!item.reportedTickets && (this.auth.hasReportedTickets() || this.auth.worksOnTickets())),
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
