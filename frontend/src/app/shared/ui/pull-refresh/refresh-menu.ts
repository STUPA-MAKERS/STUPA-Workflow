import { freshly } from '@core/cache/cache.interceptor';
import type { Translate } from '@core/i18n/translations';
import { type RowMenuItem, type RowMenuSection, visibly } from '@stupa-makers/ui-kit';

/** The id of the "Aktualisieren" entry of a list menu. */
export const REFRESH_MENU_ID = 'refresh';

/**
 * The menu section with the "Aktualisieren" entry: the one-tap alternative to the pull to
 * refresh of a phone list (app spec 000514). The page runs its reload through
 * `reloadLikePull` when `isRefreshItem` is true.
 */
export function refreshMenuSection(t: Translate): RowMenuSection {
  return { items: [{ id: REFRESH_MENU_ID, label: t('action.refresh'), icon: 'reload' }] };
}

export function isRefreshItem(item: RowMenuItem): boolean {
  return item.id === REFRESH_MENU_ID;
}

/**
 * Run the reload of a list the way a pull does (`PullRefreshDirective`): its GETs skip the
 * stored answer of the HTTP cache and run the bar of the app.
 */
export function reloadLikePull(reload: () => void): void {
  visibly(() => freshly(reload));
}
