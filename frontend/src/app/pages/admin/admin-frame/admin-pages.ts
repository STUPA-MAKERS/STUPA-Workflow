import type { TranslationKey } from '@core/i18n/translations';
import type { IconName } from '@stupa-makers/ui-kit';

/** A group of the admin navigation (board Verwaltung), in navigation order. */
export type AdminGroupKey =
  | 'people'
  | 'gremien'
  | 'applications'
  | 'finance'
  | 'appearance'
  | 'communication'
  | 'security';

/** One page of the admin area: an entry of the admin navigation. */
export interface AdminPage {
  /** The path below `/admin`. */
  link: string;
  title: TranslationKey;
  /** One functional line under the title (the home page and the settings search). */
  desc: TranslationKey;
  icon: IconName;
  group: AdminGroupKey;
  /**
   * Visible when the principal holds at least ONE of these permissions. The list is the
   * same as the gate of the route in `app.routes.ts`, so an entry never leads to the
   * 403 page. This is UX only; the server stays authoritative.
   */
  permissions: readonly string[];
}

/** The groups of the admin navigation, in order. */
export const ADMIN_GROUPS: readonly { key: AdminGroupKey; title: TranslationKey }[] = [
  { key: 'people', title: 'admin.nav.group.people' },
  { key: 'gremien', title: 'admin.nav.group.gremien' },
  { key: 'applications', title: 'admin.nav.group.applications' },
  { key: 'finance', title: 'admin.nav.group.finance' },
  { key: 'appearance', title: 'admin.nav.group.appearance' },
  { key: 'communication', title: 'admin.nav.group.communication' },
  { key: 'security', title: 'admin.nav.group.security' },
];

/**
 * Every admin page. The admin navigation, the admin home page and the permission list
 * of the "Verwaltung" rail entry (`ADMIN_AREA_PERMISSIONS`) all follow this list.
 */
export const ADMIN_PAGES: readonly AdminPage[] = [
  { link: 'users', title: 'admin.nav.users', desc: 'admin.nav.usersDesc', icon: 'users', group: 'people', permissions: ['admin.users'] },
  { link: 'roles', title: 'admin.nav.roles', desc: 'admin.nav.rolesDesc', icon: 'shield', group: 'people', permissions: ['admin.roles'] },
  { link: 'group-mappings', title: 'admin.nav.groupMappings', desc: 'admin.nav.groupMappingsDesc', icon: 'key', group: 'people', permissions: ['admin.group_mappings'] },
  // The kill switch for agent tokens of any person needs the users permission.
  { link: 'oauth-grants', title: 'admin.nav.oauthGrants', desc: 'admin.nav.oauthGrantsDesc', icon: 'key', group: 'people', permissions: ['admin.users'] },
  { link: 'gremien', title: 'admin.nav.gremien', desc: 'admin.nav.gremienDesc', icon: 'landmark', group: 'gremien', permissions: ['admin.gremien'] },
  { link: 'delegations', title: 'admin.nav.delegations', desc: 'admin.nav.delegationsDesc', icon: 'repeat', group: 'gremien', permissions: ['admin.delegations'] },
  { link: 'forms', title: 'admin.nav.forms', desc: 'admin.nav.formsDesc', icon: 'form', group: 'applications', permissions: ['form.configure'] },
  // The flow editor route and its save both accept either key.
  { link: 'flow', title: 'admin.nav.flow', desc: 'admin.nav.flowDesc', icon: 'flow', group: 'applications', permissions: ['flow.configure', 'admin.types'] },
  { link: 'deadlines', title: 'admin.nav.deadlines', desc: 'admin.nav.deadlinesDesc', icon: 'clock', group: 'applications', permissions: ['admin.deadlines'] },
  { link: 'cost-centres', title: 'admin.nav.costCentres', desc: 'admin.nav.costCentresDesc', icon: 'euro', group: 'finance', permissions: ['budget.structure'] },
  { link: 'branding', title: 'admin.nav.branding', desc: 'admin.nav.brandingDesc', icon: 'palette', group: 'appearance', permissions: ['admin.site'] },
  { link: 'cd-variants', title: 'admin.nav.cdVariants', desc: 'admin.nav.cdVariantsDesc', icon: 'document', group: 'appearance', permissions: ['admin.cd_variants'] },
  { link: 'notifications', title: 'admin.nav.notifications', desc: 'admin.nav.notificationsDesc', icon: 'bell', group: 'communication', permissions: ['admin.notifications'] },
  { link: 'mail-templates', title: 'admin.nav.mailTemplates', desc: 'admin.nav.mailTemplatesDesc', icon: 'mail', group: 'communication', permissions: ['admin.notifications'] },
  { link: 'webhooks', title: 'admin.nav.webhooks', desc: 'admin.nav.webhooksDesc', icon: 'webhook', group: 'communication', permissions: ['webhook.manage'] },
  { link: 'audit', title: 'admin.nav.audit', desc: 'admin.nav.auditDesc', icon: 'shieldok', group: 'security', permissions: ['audit.read'] },
  { link: 'privacy', title: 'admin.nav.privacy', desc: 'admin.nav.privacyDesc', icon: 'lock', group: 'security', permissions: ['privacy.manage'] },
  { link: 'backups', title: 'admin.nav.backups', desc: 'admin.nav.backupsDesc', icon: 'db', group: 'security', permissions: ['backup.manage'] },
];
