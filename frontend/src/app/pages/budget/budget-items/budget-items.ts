import type { BudgetApplication, Expense } from '../budget-tree.api';

/** One entry of the list of a cost centre: an application or a booking. */
export type BudgetItem =
  | { readonly type: 'application'; readonly at: string; readonly app: BudgetApplication }
  | { readonly type: 'booking'; readonly at: string; readonly booking: Expense };

/** The filter of the item type. `''` shows both types. */
export type BudgetItemType = '' | 'application' | 'booking';

/**
 * The applications and the bookings of a cost centre as one list, the newest first.
 *
 * Both lists are sorted by `createdAt`. The applications arrive in full, the bookings page
 * by page. While more bookings can follow (`bookingsDone` is false), the list stops at the
 * oldest booking that is loaded, because an older application could otherwise show before a
 * booking of the next page that is newer than it. The next page then moves that limit.
 */
export function mergeBudgetItems(
  apps: readonly BudgetApplication[],
  bookings: readonly Expense[],
  bookingsDone: boolean,
): readonly BudgetItem[] {
  const items: BudgetItem[] = [
    ...apps.map((app): BudgetItem => ({ type: 'application', at: app.createdAt, app })),
    ...bookings.map((booking): BudgetItem => ({ type: 'booking', at: booking.createdAt, booking })),
  ].sort((a, b) => b.at.localeCompare(a.at));
  if (bookingsDone) return items;
  const oldest = bookings.reduce<string | null>((min, b) => (min === null || b.createdAt < min ? b.createdAt : min), null);
  if (oldest === null) return [];
  return items.filter((item) => item.at >= oldest);
}

/** The id of an item, unique over both types. */
export function budgetItemKey(item: BudgetItem): string {
  return item.type === 'application' ? `a:${item.app.applicationId}` : `b:${item.booking.id}`;
}
