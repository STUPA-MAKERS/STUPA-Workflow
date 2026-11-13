import type { FiscalYear } from './budget-tree.api';
import { defaultFiscalYearId } from './fiscal-year.util';

const fy = (year: number, over: Partial<FiscalYear> = {}): FiscalYear => ({
  id: `fy-${year}`,
  budgetId: 'top',
  year,
  display: String(year),
  startDate: `${year}-01-01`,
  endDate: `${year}-12-31`,
  active: true,
  closedAt: null,
  ...over,
});

describe('defaultFiscalYearId', () => {
  it('takes the active open year that holds today', () => {
    expect(defaultFiscalYearId([fy(2025), fy(2026), fy(2027)], '2026-11-12')).toBe('fy-2026');
  });

  it('takes the newest active open year when no such year holds today', () => {
    const years = [fy(2025), fy(2026, { closedAt: '2026-12-01T00:00:00Z' }), fy(2028), fy(2029, { active: false })];
    expect(defaultFiscalYearId(years, '2026-11-12')).toBe('fy-2028');
  });

  it('takes the newest year when no year is active and open', () => {
    expect(defaultFiscalYearId([fy(2024, { active: false }), fy(2025, { closedAt: 'x' })], '2026-11-12')).toBe('fy-2025');
  });

  it('gives an empty id without a year', () => {
    expect(defaultFiscalYearId([])).toBe('');
  });
});
