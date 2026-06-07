import type { BudgetStats, PotUsage } from '@core/api/models';
import {
  formatMoney,
  formatNumber,
  kpiTotals,
  potUsageBar,
  usagePercent,
} from './budget.util';

function pot(overrides: Partial<PotUsage> = {}): PotUsage {
  return {
    budgetPotId: 'p1',
    name: 'Topf A',
    period: '2026',
    total: 1000,
    currency: 'EUR',
    requested: 200,
    reserved: 100,
    approved: 150,
    paid: 50,
    committed: 300,
    available: 700,
    ...overrides,
  };
}

function stats(pots: PotUsage[], distribution: BudgetStats['statusDistribution'] = []): BudgetStats {
  return { pots, statusDistribution: distribution };
}

describe('kpiTotals', () => {
  it('sums each stage and the application count across pots', () => {
    const k = kpiTotals(
      stats(
        [pot(), pot({ budgetPotId: 'p2', requested: 50, reserved: 0, approved: 0, paid: 0, committed: 0, total: 500, available: 500 })],
        [
          { gremiumId: 'g1', stateId: 's1', count: 3 },
          { gremiumId: 'g1', stateId: 's2', count: 4 },
        ],
      ),
    );
    expect(k.potCount).toBe(2);
    expect(k.requested).toBe(250);
    expect(k.committed).toBe(300);
    expect(k.total).toBe(1500);
    expect(k.applicationCount).toBe(7);
  });

  it('reports a single shared currency and no mix', () => {
    const k = kpiTotals(stats([pot(), pot({ budgetPotId: 'p2' })]));
    expect(k.currency).toBe('EUR');
    expect(k.mixedCurrency).toBe(false);
  });

  it('flags mixed currencies and blanks the currency', () => {
    const k = kpiTotals(stats([pot(), pot({ budgetPotId: 'p2', currency: 'USD' })]));
    expect(k.mixedCurrency).toBe(true);
    expect(k.currency).toBe('');
  });

  it('returns null total/available when no pot has a limit', () => {
    const k = kpiTotals(stats([pot({ total: null, available: null })]));
    expect(k.total).toBeNull();
    expect(k.available).toBeNull();
  });

  it('only sums limits/available for limited pots, ignoring unlimited ones', () => {
    const k = kpiTotals(
      stats([pot({ total: 1000, available: 700 }), pot({ budgetPotId: 'p2', total: null, available: null })]),
    );
    expect(k.total).toBe(1000);
    expect(k.available).toBe(700);
  });

  it('yields zeros and null totals for an empty pot list', () => {
    const k = kpiTotals(stats([]));
    expect(k.potCount).toBe(0);
    expect(k.committed).toBe(0);
    expect(k.total).toBeNull();
    expect(k.applicationCount).toBe(0);
  });
});

describe('potUsageBar', () => {
  it('builds committed segments as percentages of the total', () => {
    const bar = potUsageBar(pot());
    const byStage = Object.fromEntries(bar.segments.map((s) => [s.stage, s.pct]));
    expect(byStage['paid']).toBe(5); // 50 / 1000
    expect(byStage['approved']).toBe(15); // 150 / 1000
    expect(byStage['reserved']).toBe(10); // 100 / 1000
    expect(bar.committedPct).toBe(30);
    expect(bar.availablePct).toBe(70);
    expect(bar.overcommitted).toBe(false);
  });

  it('marks overcommitment when committed exceeds the limit', () => {
    const bar = potUsageBar(pot({ total: 200, committed: 300, available: 0 }));
    expect(bar.overcommitted).toBe(true);
    expect(bar.committedPct).toBe(100); // clamped
    expect(bar.availablePct).toBe(0);
  });

  it('scales relative to committed and shows no free rest when the pot is unlimited', () => {
    const bar = potUsageBar(pot({ total: null, available: null, committed: 300 }));
    expect(bar.denominator).toBe(300);
    expect(bar.committedPct).toBe(100);
    expect(bar.availablePct).toBe(0);
  });
});

describe('usagePercent', () => {
  it('rounds committed/total to a whole percent', () => {
    expect(usagePercent(pot({ total: 1000, committed: 333 }))).toBe(33);
  });
  it('returns null for unlimited pots', () => {
    expect(usagePercent(pot({ total: null }))).toBeNull();
  });
});

describe('formatMoney / formatNumber', () => {
  it('formats a currency amount for the locale', () => {
    expect(formatMoney(1234.5, 'EUR', 'de')).toContain('1.234,5');
  });
  it('renders an em dash for null', () => {
    expect(formatMoney(null, 'EUR', 'de')).toBe('—');
  });
  it('falls back to a plain number when currency is blank (mixed)', () => {
    expect(formatMoney(1000, '', 'de')).toBe(formatNumber(1000, 'de'));
  });
});
