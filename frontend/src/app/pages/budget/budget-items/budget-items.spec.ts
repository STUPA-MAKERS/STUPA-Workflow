import { budgetItemKey, mergeBudgetItems } from './budget-items';
import { itemApp, itemBooking } from './budget-items.fixtures';

describe('mergeBudgetItems', () => {
  const a1 = itemApp({ applicationId: 'a1', createdAt: '2026-06-01T00:00:00Z' });
  const a2 = itemApp({ applicationId: 'a2', createdAt: '2026-01-01T00:00:00Z' });
  const b1 = itemBooking({ id: 'b1', createdAt: '2026-04-01T00:00:00Z' });

  it('sorts both types into one list, the newest first', () => {
    const items = mergeBudgetItems([a2, a1], [b1], true);
    expect(items.map(budgetItemKey)).toEqual(['a:a1', 'b:b1', 'a:a2']);
  });

  it('stops at the oldest loaded booking while more bookings can follow', () => {
    expect(mergeBudgetItems([a2, a1], [b1], false).map(budgetItemKey)).toEqual(['a:a1', 'b:b1']);
  });

  it('shows nothing before the first page of bookings is there', () => {
    expect(mergeBudgetItems([a1], [], false)).toEqual([]);
  });

  it('finds the oldest booking in any order of the page', () => {
    const b2 = itemBooking({ id: 'b2', createdAt: '2026-02-01T00:00:00Z' });
    expect(mergeBudgetItems([a2], [b2, b1], false).map(budgetItemKey)).toEqual(['b:b1', 'b:b2']);
    expect(mergeBudgetItems([a2], [b1, b2], false).map(budgetItemKey)).toEqual(['b:b1', 'b:b2']);
  });
});
