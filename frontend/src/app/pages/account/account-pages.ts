import type { FrameGroup, FramePage } from '../admin/admin-frame/frame-modes';

/** The one group of the account navigation. It has no heading: the frame title says "Konto". */
export const ACCOUNT_GROUPS: readonly FrameGroup[] = [{ key: 'account', title: null }];

/**
 * Every page of the account area (`/account/*`), in navigation order. The account frame
 * and the account menu of the rail follow the same rules.
 *
 * - An empty `permissions` list: every signed-in person sees the entry.
 * - "API-Zugang" needs `mcp.use`, the same as its entry in the account menu. The route
 *   itself has no gate, so a person who lost the permission can still revoke old grants
 *   through a direct link.
 *
 * The calendar subscription is not an account page. It is a popover of the meetings page,
 * and `/account/calendar` redirects there.
 */
export const ACCOUNT_PAGES: readonly FramePage[] = [
  {
    link: 'notifications',
    title: 'account.menu.notifications',
    desc: 'account.nav.notificationsDesc',
    icon: 'bell',
    group: 'account',
    permissions: [],
  },
  {
    link: 'grants',
    title: 'account.menu.apiAccess',
    desc: 'account.nav.grantsDesc',
    icon: 'webhook',
    group: 'account',
    permissions: ['mcp.use'],
  },
];
