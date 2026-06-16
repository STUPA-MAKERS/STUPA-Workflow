import { render, screen } from '@testing-library/angular';
import { BudgetPieComponent, type PieSlice } from './budget-pie.component';

/** Direkten Zugriff auf die `protected`-Member für gezielte Branch-Abdeckung. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PieInternals = any;

const SLICES: PieSlice[] = [
  { label: 'Alpha', value: 60, color: '#111', id: 'a' },
  { label: 'Beta', value: 40, color: '#222', id: 'b' },
];

async function setup(inputs: Partial<{ title: string; slices: PieSlice[] }> = {}) {
  const view = await render(BudgetPieComponent, {
    inputs: { title: 'Verteilung', slices: SLICES, ...inputs },
  });
  return { ...view, c: view.fixture.componentInstance as unknown as PieInternals };
}

describe('BudgetPieComponent (#budget-redesign)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders the title and one path per non-zero slice', async () => {
    const view = await setup();
    expect(screen.getByText('Verteilung')).toBeTruthy();
    const paths = view.container.querySelectorAll('path.pie__slice');
    expect(paths.length).toBe(2);
    // SVG has the title as accessible label.
    expect(view.container.querySelector('svg.pie__svg')?.getAttribute('aria-label')).toBe(
      'Verteilung',
    );
  });

  it('shows the empty paragraph (not the svg) when total is 0', async () => {
    const view = await setup({ slices: [] });
    expect(view.container.querySelector('svg.pie__svg')).toBeNull();
    expect(view.container.querySelector('p.pie__empty')).toBeTruthy();
  });

  it('treats slices with non-positive values as empty (total clamps negatives to 0)', async () => {
    const view = await setup({
      slices: [
        { label: 'Neg', value: -10, color: '#333' },
        { label: 'Zero', value: 0, color: '#444' },
      ],
    });
    // total() = max(0,-10)+max(0,0) = 0 → empty branch.
    expect(view.fixture.componentInstance as unknown as PieInternals).toBeTruthy();
    expect(view.container.querySelector('p.pie__empty')).toBeTruthy();
  });

  it('total() sums and floors negative slice values to zero', async () => {
    const { c } = await setup({
      slices: [
        { label: 'Pos', value: 30, color: '#1' },
        { label: 'Neg', value: -5, color: '#2' },
      ],
    });
    expect(c.total()).toBe(30);
  });

  it('arcs() computes percent and skips zero/negative fractions', async () => {
    const { c } = await setup({
      slices: [
        { label: 'Big', value: 75, color: '#1', id: 'big' },
        { label: 'Small', value: 25, color: '#2', id: 'small' },
        { label: 'Skip', value: 0, color: '#3' },
        { label: 'SkipNeg', value: -3, color: '#4' },
      ],
    });
    const arcs = c.arcs();
    // Only the two positive slices become arcs.
    expect(arcs.length).toBe(2);
    expect(arcs[0].percent).toBe(75);
    expect(arcs[1].percent).toBe(25);
    // mid coordinates are unit-circle components.
    expect(typeof arcs[0].midX).toBe('number');
    expect(typeof arcs[0].midY).toBe('number');
    expect(arcs[0].d).toContain('M ');
  });

  it('arcs() returns empty when total <= 0', async () => {
    const { c } = await setup({ slices: [] });
    expect(c.arcs()).toEqual([]);
  });

  it('renders a full-ring path for a single 100% slice', async () => {
    const { c, container } = await setup({
      slices: [{ label: 'All', value: 100, color: '#abc', id: 'all' }],
    });
    const arcs = c.arcs();
    expect(arcs.length).toBe(1);
    expect(arcs[0].percent).toBe(100);
    // Full circle path uses two "Z"-closed sub-paths (outer + inner hole).
    const d = container.querySelector('path.pie__slice')?.getAttribute('d') ?? '';
    expect((d.match(/Z/g) ?? []).length).toBe(2);
  });

  it('produces a large-arc flag for slices spanning more than half the circle', async () => {
    const { c } = await setup({
      slices: [
        { label: 'Most', value: 80, color: '#1', id: 'most' }, // > 50% → large=1
        { label: 'Rest', value: 20, color: '#2', id: 'rest' }, // < 50% → large=0
      ],
    });
    const arcs = c.arcs();
    // donutArc embeds the large-arc flag in the "A R R 0 <large> 1" command.
    expect(arcs[0].d).toMatch(/A 70 70 0 1 1/);
    expect(arcs[1].d).toMatch(/A 70 70 0 0 1/);
  });

  it('active() is null with no hover and the chosen arc when hovered', async () => {
    const { c } = await setup();
    expect(c.active()).toBeNull();
    c.hovered.set(0);
    expect(c.active()?.label).toBe('Alpha');
    // Out-of-range hover index falls back to null via ?? .
    c.hovered.set(99);
    expect(c.active()).toBeNull();
  });

  it('legend shows the hovered slice and falls back to the hint otherwise', async () => {
    const view = await setup();
    // No hover → hint span present.
    expect(view.container.querySelector('.pie__legHint')).toBeTruthy();
    (view.fixture.componentInstance as unknown as PieInternals).hovered.set(0);
    view.fixture.detectChanges();
    expect(view.container.querySelector('.pie__legLabel')?.textContent).toContain('Alpha');
    expect(view.container.querySelector('.pie__legVal')).toBeTruthy();
  });

  it('emits sliceClick only for slices that carry an id', async () => {
    const { c } = await setup();
    const emit = jest.fn();
    c.sliceClick.subscribe(emit);
    c.onSlice({ id: 'x', label: 'l', value: 1, color: '#0', d: '', midX: 0, midY: 0, percent: 1 });
    expect(emit).toHaveBeenCalledWith('x');
    emit.mockClear();
    c.onSlice({ label: 'l', value: 1, color: '#0', d: '', midX: 0, midY: 0, percent: 1 });
    expect(emit).not.toHaveBeenCalled();
  });

  it('sliceTransform translates+scales the hovered slice and returns none otherwise', async () => {
    const { c } = await setup();
    const arc = { id: 'x', label: 'l', value: 1, color: '#0', d: '', midX: 1, midY: 0.5, percent: 1 };
    c.hovered.set(2);
    expect(c.sliceTransform(arc, 2)).toContain('translate(');
    expect(c.sliceTransform(arc, 2)).toContain('scale(1.04)');
    expect(c.sliceTransform(arc, 3)).toBe('none');
  });

  it('money() formats integers as whole euros in the active locale', async () => {
    const { c } = await setup();
    const out = c.money(1234);
    expect(out).toContain('1.234');
    expect(out).toContain('€');
    // maximumFractionDigits:0 → no decimal part.
    expect(out).not.toMatch(/,\d\d/);
  });

  it('clicking a slice path in the DOM emits its id', async () => {
    const view = await setup();
    const emit = jest.fn();
    (view.fixture.componentInstance as unknown as PieInternals).sliceClick.subscribe(emit);
    const path = view.container.querySelector('path.pie__slice') as SVGPathElement;
    path.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(emit).toHaveBeenCalledWith('a');
  });
});
