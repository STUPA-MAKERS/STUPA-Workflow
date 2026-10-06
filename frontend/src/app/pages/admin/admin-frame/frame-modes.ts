import type { TranslationKey } from '@core/i18n/translations';
import type { IconName } from '@stupa-makers/ui-kit';
import { ACCOUNT_GROUPS, ACCOUNT_PAGES } from '../../account/account-pages';
import { ADMIN_GROUPS, ADMIN_PAGES } from './admin-pages';

/** One entry of a frame navigation: a page below the home path of the frame. */
export interface FramePage {
  /** The path below the home path of the frame. */
  link: string;
  title: TranslationKey;
  /** One functional line under the title (the home page and the search). */
  desc: TranslationKey;
  icon: IconName;
  group: string;
  /**
   * Visible when the principal holds at least ONE of these permissions. An empty list
   * makes the entry visible to every signed-in person. This is UX only; the route gate
   * and the server stay authoritative.
   */
  permissions: readonly string[];
}

/** A group of a frame navigation. A group without a title shows its entries only. */
export interface FrameGroup {
  key: string;
  title: TranslationKey | null;
}

/** The areas that use the frame: the administration and the account. */
export type FrameModeKey = 'admin' | 'account';

/**
 * What differs between the areas of the frame. The layout (navigation column beside a
 * page sheet, one column below wide) is the same for all.
 */
export interface FrameMode {
  /** The home path of the area, for example `/admin`. */
  home: string;
  /** The title above the navigation ("Verwaltung", "Konto"). */
  title: TranslationKey;
  /** The accessible name of the navigation. */
  navLabel: TranslationKey;
  groups: readonly FrameGroup[];
  pages: readonly FramePage[];
  /** Show "Einstellungen durchsuchen" above the entries. */
  search: boolean;
  /** Show the "Zustand" tiles above the entries. */
  health: boolean;
  /**
   * Below wide, every page except the home page shows "Zur Liste" above it, which leads
   * back to the navigation. Without it the breadcrumbs lead back (the administration).
   */
  backLink: boolean;
}

/** The modes of the frame. A route picks one with `data: { frame: '<key>' }`. */
export const FRAME_MODES: Readonly<Record<FrameModeKey, FrameMode>> = {
  admin: {
    home: '/admin',
    title: 'admin.home.title',
    navLabel: 'admin.frame.navLabel',
    groups: ADMIN_GROUPS,
    pages: ADMIN_PAGES,
    search: true,
    health: true,
    backLink: false,
  },
  account: {
    home: '/account',
    title: 'account.frame.title',
    navLabel: 'account.frame.navLabel',
    groups: ACCOUNT_GROUPS,
    pages: ACCOUNT_PAGES,
    search: false,
    health: false,
    backLink: true,
  },
};
