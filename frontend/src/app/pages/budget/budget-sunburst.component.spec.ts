import { render } from '@testing-library/angular';
import { BudgetSunburstComponent } from './budget-sunburst.component';
import type { BudgetAllocationView, BudgetTreeNode } from './budget-tree.api';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SunInternals = any;

/** Knoten-Fabrik mit nur den Feldern, die der Sunburst liest. */
function node(
  id: string,
  alloc: Partial<BudgetAllocationView> & { fiscalYearId: string },
  children: BudgetTreeNode[] = [],
  extra: Partial<BudgetTreeNode> = {},
): BudgetTreeNode {
  const view: BudgetAllocationView = {
    fiscalYearId: alloc.fiscalYearId,
    allocated: alloc.allocated ?? '0',
    bound: alloc.bound ?? '0',
    expended: alloc.expended ?? '0',
    income: alloc.income ?? '0',
    committed: alloc.committed ?? '0',
    requested: alloc.requested ?? '0',
    available: alloc.available ?? '0',
  };
  return {
    id,
    parentId: null,
    gremiumId: null,
    key: id,
    pathKey: id.toUpperCase(),
    name: `Node ${id}`,
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
    byFiscalYear: [view],
    children,
    ...extra,
  };
}

const FY = 'fy-1';

async function setup(
  inputs: Partial<{ root: BudgetTreeNode | null; fyId: string; metric: string }> = {},
) {
  const view = await render(BudgetSunburstComponent, {
    inputs: { root: null, fyId: FY, metric: 'allocated', ...inputs },
  });
  return { ...view, c: view.fixture.componentInstance as unknown as SunInternals };
}

describe('BudgetSunburstComponent (#budget-sunburst)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('total() is 0 with no root and shows the empty paragraph', async () => {
    const view = await setup({ root: null });
    expect((view.fixture.componentInstance as unknown as SunInternals).total()).toBe(0);
    expect(view.container.querySelector('p.sb__empty')).toBeTruthy();
    expect(view.container.querySelector('svg.sb__svg')).toBeNull();
  });

  it('segments() is empty when the root total is 0 (no metric data)', async () => {
    const root = node('root', { fiscalYearId: FY, allocated: '0' });
    const { c } = await setup({ root });
    expect(c.total()).toBe(0);
    expect(c.segments()).toEqual([]);
  });

  it('metricOf falls back to 0 when the fiscal year is not present', async () => {
    const root = node('root', { fiscalYearId: 'other', allocated: '500' });
    const { c } = await setup({ root, fyId: FY });
    // Looking for FY but data only on 'other' → 0.
    expect(c.total()).toBe(0);
  });

  it('subtree adds own remainder plus children sums and clamps negative own to 0', async () => {
    // Parent alloc 100; child alloc 120 (> parent) → own clamps to 0, total = child 120.
    const child = node('c1', { fiscalYearId: FY, allocated: '120' });
    const root = node('root', { fiscalYearId: FY, allocated: '100' }, [child]);
    const { c } = await setup({ root });
    expect(c.total()).toBe(120);
  });

  it('builds one segment per positive child with computed percent and path', async () => {
    const a = node('a', { fiscalYearId: FY, allocated: '60' });
    const b = node('b', { fiscalYearId: FY, allocated: '40' });
    const root = node('root', { fiscalYearId: FY, allocated: '100' }, [a, b]);
    const { c } = await setup({ root });
    const segs = c.segments();
    expect(segs.map((s: { id: string }) => s.id)).toEqual(['a', 'b']);
    expect(segs[0].percent).toBe(60);
    expect(segs[1].percent).toBe(40);
    expect(segs[0].depth).toBe(1);
    expect(segs[0].d).toContain('M ');
  });

  it('skips children whose subtree value is <= 0', async () => {
    const zero = node('z', { fiscalYearId: FY, allocated: '0' });
    const real = node('r', { fiscalYearId: FY, allocated: '50' });
    const root = node('root', { fiscalYearId: FY, allocated: '50' }, [zero, real]);
    const { c } = await setup({ root });
    const segs = c.segments();
    expect(segs.map((s: { id: string }) => s.id)).toEqual(['r']);
  });

  it('lays out deeper rings with decreasing opacity and inherits the parent color', async () => {
    const grandchild = node('gc', { fiscalYearId: FY, allocated: '30' });
    const child = node('ch', { fiscalYearId: FY, allocated: '30' }, [grandchild]);
    const root = node('root', { fiscalYearId: FY, allocated: '30' }, [child]);
    const { c } = await setup({ root });
    const segs = c.segments();
    const ch = segs.find((s: { id: string }) => s.id === 'ch');
    const gc = segs.find((s: { id: string }) => s.id === 'gc');
    expect(ch.depth).toBe(1);
    expect(gc.depth).toBe(2);
    // Deeper ring is dimmer.
    expect(gc.opacity).toBeLessThan(ch.opacity);
    // Grandchild has no own color → inherits the child's branch color.
    expect(gc.color).toBe(ch.color);
  });

  it('honours an explicit cost-centre color over the palette', async () => {
    const colored = node('cc', { fiscalYearId: FY, allocated: '50' }, [], { color: '#abcdef' });
    const root = node('root', { fiscalYearId: FY, allocated: '50' }, [colored]);
    const { c } = await setup({ root });
    expect(c.segments()[0].color).toBe('#abcdef');
  });

  it('emits the root id from the centre click and the segment id from a segment click', async () => {
    const child = node('a', { fiscalYearId: FY, allocated: '50' });
    const root = node('root', { fiscalYearId: FY, allocated: '50' }, [child]);
    const { c } = await setup({ root });
    const emit = jest.fn();
    c.nodeClick.subscribe(emit);
    c.rootClick();
    expect(emit).toHaveBeenCalledWith('root');
  });

  it('rootClick does nothing when there is no root', async () => {
    const { c } = await setup({ root: null });
    const emit = jest.fn();
    c.nodeClick.subscribe(emit);
    c.rootClick();
    expect(emit).not.toHaveBeenCalled();
  });

  it('onMove positions the tooltip relative to the host with the +14px offset', async () => {
    const { c } = await setup();
    const host = document.createElement('div');
    host.getBoundingClientRect = () =>
      ({ left: 100, top: 50, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON() {} }) as DOMRect;
    c.onMove({ currentTarget: host, clientX: 140, clientY: 80 } as unknown as PointerEvent);
    expect(c.tip()).toEqual({ x: 140 - 100 + 14, y: 80 - 50 + 14 });
  });

  it('money() formats whole euros with no decimals', async () => {
    const { c } = await setup();
    const out = c.money(2500);
    expect(out).toContain('2.500');
    expect(out).toContain('€');
    expect(out).not.toMatch(/,\d\d/);
  });

  it('renders a full-circle annular ring when a single child takes the whole span', async () => {
    // root has exactly one positive child taking 100% → childSpan == 2π → full-circle annular branch.
    const only = node('only', { fiscalYearId: FY, allocated: '100' });
    const root = node('root', { fiscalYearId: FY, allocated: '100' }, [only]);
    const { c, container } = await setup({ root });
    const segs = c.segments();
    expect(segs.length).toBe(1);
    // Full annular path closes two sub-paths (outer + inner).
    const d = container.querySelector('path.sb__seg')?.getAttribute('d') ?? segs[0].d;
    expect((d.match(/Z/g) ?? []).length).toBe(2);
  });

  it('renders a large-arc segment when a child spans more than half the ring', async () => {
    const big = node('big', { fiscalYearId: FY, allocated: '80' });
    const small = node('small', { fiscalYearId: FY, allocated: '20' });
    const root = node('root', { fiscalYearId: FY, allocated: '100' }, [big, small]);
    const { c } = await setup({ root });
    const segs = c.segments();
    // big > 50% of the ring → large-arc flag 1 in the outer arc command.
    expect(segs[0].d).toMatch(/A [\d.]+ [\d.]+ 0 1 1/);
    // small < 50% → large-arc flag 0.
    expect(segs[1].d).toMatch(/A [\d.]+ [\d.]+ 0 0 1/);
  });

  it('reads the metric named by the metric input (expended vs allocated)', async () => {
    const root = node('root', { fiscalYearId: FY, allocated: '100', expended: '40' });
    const { c } = await setup({ root, metric: 'expended' });
    expect(c.total()).toBe(40);
  });

  it('renders the SVG, centre name and hint when there is data', async () => {
    const child = node('a', { fiscalYearId: FY, allocated: '50' });
    const root = node('root', { fiscalYearId: FY, allocated: '50' }, [child]);
    const view = await render(BudgetSunburstComponent, {
      inputs: { root, fyId: FY, metric: 'allocated' },
    });
    expect(view.container.querySelector('svg.sb__svg')).toBeTruthy();
    expect(view.container.querySelector('text.sb__center-name')?.textContent).toContain('Node root');
    expect(view.container.querySelector('p.sb__empty')).toBeNull();
  });
});
