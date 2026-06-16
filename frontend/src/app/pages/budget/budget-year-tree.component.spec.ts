import { render, screen, fireEvent } from '@testing-library/angular';
import {
  BudgetYearTreeComponent,
  PALETTE,
  type BudgetYearSelection,
} from './budget-year-tree.component';
import type { BudgetTreeNode, FiscalYear } from './budget-tree.api';

function top(over: Partial<BudgetTreeNode> = {}): BudgetTreeNode {
  return {
    id: 't-1',
    parentId: null,
    gremiumId: null,
    key: 'VS',
    pathKey: 'VS',
    name: 'VS-Mittel',
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    fullyBound: false,
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [],
    ...over,
  };
}

function fy(id: string, year: number): FiscalYear {
  return {
    id,
    budgetId: 't-1',
    year,
    display: String(year),
    startDate: `${year}-01-01`,
    endDate: `${year}-12-31`,
    active: true,
  };
}

describe('BudgetYearTreeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders an empty-state when there are no budgets', async () => {
    const { fixture } = await render(BudgetYearTreeComponent, {
      inputs: { tops: [], fiscalYears: {} },
    });
    // Empty paragraph text comes from the 'budget.tree.empty' i18n key.
    expect(fixture.nativeElement.querySelector('.byt__empty')).toBeTruthy();
  });

  it('renders each budget with its fiscal years and highlights the active one', async () => {
    const tops = [top({ id: 't-1', name: 'VS-Mittel' })];
    const { fixture } = await render(BudgetYearTreeComponent, {
      inputs: {
        tops,
        fiscalYears: { 't-1': [fy('fy-1', 2026), fy('fy-2', 2027)] },
        selectedBudgetId: 't-1',
        selectedFyId: 'fy-2',
      },
    });
    expect(screen.getByText('VS-Mittel')).toBeInTheDocument();
    expect(screen.getByText('2026')).toBeInTheDocument();
    expect(screen.getByText('2027')).toBeInTheDocument();
    // The selected budget div carries the --sel modifier.
    expect(fixture.nativeElement.querySelector('.byt__budget--sel')).toBeTruthy();
    // The active year button carries the --active modifier.
    expect(fixture.nativeElement.querySelector('.byt__node--active')).toBeTruthy();
  });

  it('shows a per-budget no-years placeholder when a budget has none', async () => {
    const { fixture } = await render(BudgetYearTreeComponent, {
      inputs: { tops: [top()], fiscalYears: {} },
    });
    // budget present but no years → .byt__empty inside the <ul>, plus dot rendered.
    expect(fixture.nativeElement.querySelector('.byt__years .byt__empty')).toBeTruthy();
  });

  it('emits budgetPicked when a budget node is clicked', async () => {
    let picked: string | undefined;
    await render(BudgetYearTreeComponent, {
      inputs: { tops: [top({ id: 't-9', name: 'AStA' })], fiscalYears: {} },
      on: { budgetPicked: (id: string) => (picked = id) },
    });
    fireEvent.click(screen.getByText('AStA'));
    expect(picked).toBe('t-9');
  });

  it('emits yearPicked with the budget + fiscal-year ids when a year is clicked', async () => {
    let sel: BudgetYearSelection | undefined;
    await render(BudgetYearTreeComponent, {
      inputs: {
        tops: [top({ id: 't-1' })],
        fiscalYears: { 't-1': [fy('fy-7', 2025)] },
      },
      on: { yearPicked: (s: BudgetYearSelection) => (sel = s) },
    });
    fireEvent.click(screen.getByText('2025'));
    expect(sel).toEqual({ budgetId: 't-1', fiscalYearId: 'fy-7' });
  });

  it('caps shown years at 5 and renders a "more" indicator with the rest as a title', async () => {
    const years = [
      fy('a', 2020),
      fy('b', 2021),
      fy('c', 2022),
      fy('d', 2023),
      fy('e', 2024),
      fy('f', 2025),
      fy('g', 2026),
    ];
    const { fixture } = await render(BudgetYearTreeComponent, {
      inputs: { tops: [top()], fiscalYears: { 't-1': years } },
    });
    const c = fixture.componentInstance;
    expect(c.shownYears('t-1').map((y) => y.year)).toEqual([2020, 2021, 2022, 2023, 2024]);
    expect(c.hiddenCount('t-1')).toBe(2);
    expect(c.moreTitle('t-1')).toBe('2025, 2026');
    const more = fixture.nativeElement.querySelector('.byt__more');
    expect(more).toBeTruthy();
    expect(more.getAttribute('title')).toBe('2025, 2026');
  });

  it('hiddenCount is clamped to 0 when there are fewer than the max years', async () => {
    const { fixture } = await render(BudgetYearTreeComponent, {
      inputs: { tops: [top()], fiscalYears: { 't-1': [fy('a', 2020)] } },
    });
    const c = fixture.componentInstance;
    expect(c.hiddenCount('t-1')).toBe(0);
    expect(c.moreTitle('t-1')).toBe('');
    expect(fixture.nativeElement.querySelector('.byt__more')).toBeFalsy();
  });

  it('years() returns an empty array for an unknown budget id (?? fallback)', async () => {
    const { fixture } = await render(BudgetYearTreeComponent, {
      inputs: { tops: [top()], fiscalYears: {} },
    });
    expect(fixture.componentInstance.years('does-not-exist')).toEqual([]);
  });

  describe('dotColor', () => {
    it('returns the explicit node color when set', async () => {
      const { fixture } = await render(BudgetYearTreeComponent, {
        inputs: { tops: [top({ id: 't-1', color: '#abcdef' })], fiscalYears: {} },
      });
      expect(fixture.componentInstance.dotColor(top({ id: 't-1', color: '#abcdef' }))).toBe(
        '#abcdef',
      );
    });

    it('falls back to the palette by stable budget index when no color', async () => {
      const tops = [top({ id: 't-0' }), top({ id: 't-1' })];
      const { fixture } = await render(BudgetYearTreeComponent, {
        inputs: { tops, fiscalYears: {} },
      });
      const c = fixture.componentInstance;
      expect(c.dotColor(tops[0])).toBe(PALETTE[0]);
      expect(c.dotColor(tops[1])).toBe(PALETTE[1]);
    });

    it('returns the first palette colour for a node not present in tops (index -1)', async () => {
      const { fixture } = await render(BudgetYearTreeComponent, {
        inputs: { tops: [top({ id: 't-known' })], fiscalYears: {} },
      });
      // index === -1 → ((-1 % len) + len) % len === len - 1
      const expected = PALETTE[PALETTE.length - 1];
      expect(fixture.componentInstance.dotColor(top({ id: 'unknown' }))).toBe(expected);
    });
  });
});
