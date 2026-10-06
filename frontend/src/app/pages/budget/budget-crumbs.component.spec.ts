import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../testing/a11y';
import { BudgetCrumbsComponent, fitCrumbs, visibleParents } from './budget-crumbs.component';
import type { BudgetTreeNode } from './budget-tree.api';

function node(id: string, name: string, key: string): BudgetTreeNode {
  return {
    id,
    parentId: null,
    gremiumId: null,
    key,
    pathKey: key,
    name,
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [],
  };
}

/** Haushalt › Fachschaften › Fachschaft Gestaltung › Werkstatt › Siebdruck. */
const PATH = [
  node('hh', 'Haushalt Studierendenschaft', 'HH'),
  node('fs', 'Fachschaften', 'HH-200'),
  node('gm', 'Fachschaft Gestaltung und angewandte Medien', 'HH-200-230'),
  node('ws', 'Werkstatt', 'HH-200-230-231'),
  node('sd', 'Siebdruck', 'HH-200-230-231-2311'),
];

const base = { min: 88, sep: 21, more: 28, key: 0 };

describe('fitCrumbs', () => {
  it('shows every crumb when the natural widths fit', () => {
    expect(fitCrumbs({ ...base, widths: [200, 90, 60], available: 500 })).toEqual({ hidden: 0, squeeze: 'none' });
  });

  it('keeps every parent when each fits at its minimum', () => {
    // 88 + 21 + 50 + 21 + 60 + key 40 = 280: the long root shortens, the short one keeps its width.
    expect(fitCrumbs({ ...base, key: 40, widths: [200, 50, 60], available: 280 })).toEqual({
      hidden: 0,
      squeeze: 'none',
    });
  });

  it('hides the levels after the root first', () => {
    const widths = [200, 200, 200, 60];
    // root 88+21, … 28+21, parent 88+21, current 60 = 327.
    expect(fitCrumbs({ ...base, widths, available: 327 })).toEqual({ hidden: 1, squeeze: 'none' });
    // root 88+21, … 28+21, current 60 = 218.
    expect(fitCrumbs({ ...base, widths, available: 326 })).toEqual({ hidden: 2, squeeze: 'none' });
    // … 28+21, current 60 = 109.
    expect(fitCrumbs({ ...base, widths, available: 217 })).toEqual({ hidden: 3, squeeze: 'none' });
  });

  it('shortens the key, then drops it and shortens the name, when "… › current" does not fit', () => {
    // … 28+21, current 100, key 150 (at least 88).
    const m = { ...base, key: 150, widths: [200, 100] };
    expect(fitCrumbs({ ...m, available: 299 })).toEqual({ hidden: 1, squeeze: 'none' });
    expect(fitCrumbs({ ...m, available: 298 })).toEqual({ hidden: 1, squeeze: 'key' });
    expect(fitCrumbs({ ...m, available: 237 })).toEqual({ hidden: 1, squeeze: 'key' });
    expect(fitCrumbs({ ...m, available: 236 })).toEqual({ hidden: 1, squeeze: 'name' });
    // A key shorter than the minimum does not shorten: the name gives way.
    expect(fitCrumbs({ ...m, key: 30, available: 178 })).toEqual({ hidden: 1, squeeze: 'name' });
  });

  it('has nothing to hide for a root alone, and nothing at all for an empty path', () => {
    expect(fitCrumbs({ ...base, widths: [100], key: 50, available: 150 })).toEqual({ hidden: 0, squeeze: 'none' });
    expect(fitCrumbs({ ...base, widths: [100], key: 50, available: 149 })).toEqual({ hidden: 0, squeeze: 'name' });
    expect(fitCrumbs({ ...base, widths: [], available: 10 })).toEqual({ hidden: 0, squeeze: 'none' });
  });
});

describe('visibleParents', () => {
  it('keeps the root and the parents nearest to the current crumb', () => {
    expect(visibleParents(4, 0)).toEqual([0, 1, 2, 3]);
    expect(visibleParents(4, 2)).toEqual([0, 3]);
    expect(visibleParents(4, 3)).toEqual([0]);
    expect(visibleParents(4, 4)).toEqual([]);
  });
});

describe('BudgetCrumbsComponent', () => {
  let barWidth = 2000;
  let observers: ResizeObserverCallback[] = [];
  const disconnect = jest.fn();
  const original = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;

  beforeEach(() => {
    barWidth = 2000;
    observers = [];
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      constructor(cb: ResizeObserverCallback) {
        observers.push(cb);
      }
      observe(): void {}
      disconnect = disconnect;
    };
    // 8px per character for the hidden names; fixed widths for the minimum, "…" and the key.
    jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      let width = 0;
      if (this.hasAttribute('data-crumb')) width = (this.getAttribute('data-text') ?? '').length * 8;
      else if (this.hasAttribute('data-min')) width = 88;
      else if (this.hasAttribute('data-more')) width = 28;
      else if (this.hasAttribute('data-key')) width = 120;
      return { width, height: 20, top: 0, left: 0, right: width, bottom: 20, x: 0, y: 0, toJSON: () => ({}) };
    });
    jest.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.classList.contains('bd__crumbs') ? barWidth : 0;
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = original;
  });

  async function setup(nodes: readonly BudgetTreeNode[] = PATH) {
    const picks: string[] = [];
    const view = await render(BudgetCrumbsComponent, {
      inputs: { nodes },
      on: { pick: (id: string) => picks.push(id) },
    });
    const nav = () => screen.getByRole('navigation', { name: 'Kostenstellen-Pfad' });
    const resize = async (width: number) => {
      barWidth = width;
      for (const cb of observers) cb([], {} as ResizeObserver);
      view.fixture.detectChanges();
      await view.fixture.whenStable();
    };
    return { view, picks, nav, resize };
  }

  it('shows the whole path with the key of the current cost centre in a wide bar', async () => {
    const { nav, view } = await setup();
    const trail = within(nav());
    for (const n of PATH.slice(0, -1)) expect(trail.getByRole('button', { name: n.name })).toBeTruthy();
    const current = trail.getByText('Siebdruck');
    expect(current.getAttribute('aria-current')).toBe('page');
    expect(current.getAttribute('title')).toBe('Siebdruck');
    expect(current).not.toHaveClass('bd__crumb--tight');
    expect(trail.getByText('HH-200-230-231-2311')).not.toHaveClass('bd__key--tight');
    expect(trail.queryByRole('button', { name: 'Weitere Ebenen des Pfads' })).toBeNull();
    // A parent keeps its natural width as its floor (below the minimum).
    // (jsdom drops custom properties from the style, so the value is read from the source.)
    const c = view.fixture.componentInstance as unknown as { crumbWidth(i: number): string | null };
    expect(c.crumbWidth(3)).toBe('72px');
    expect(c.crumbWidth(9)).toBeNull();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('goes up on a click of a parent', async () => {
    const { nav, picks } = await setup();
    await userEvent.setup().click(within(nav()).getByRole('button', { name: 'Fachschaften' }));
    expect(picks).toEqual(['fs']);
  });

  it('puts the levels after the root into a "…" menu when the bar narrows', async () => {
    const { nav, picks, resize, view } = await setup();
    // root 88+13, … 28+13, Werkstatt 72+13, current 72, key 120 = 419.
    await resize(419);
    const trail = within(nav());
    const names = Array.from(nav().querySelectorAll('.bd__crumb, .rm__trigger'), (el) => el.textContent?.trim());
    expect(names).toEqual(['Haushalt Studierendenschaft', '…', 'Werkstatt', 'Siebdruck']);
    const more = trail.getByRole('button', { name: 'Weitere Ebenen des Pfads' });
    const user = userEvent.setup();
    await user.click(more);
    const menu = screen.getByRole('menu');
    expect(within(menu).getAllByRole('menuitem').map((i) => i.textContent?.trim())).toEqual([
      'Fachschaften',
      'Fachschaft Gestaltung und angewandte Medien',
    ]);
    await user.keyboard('{ArrowDown}{Enter}');
    expect(picks).toEqual(['gm']);
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('hides every parent, then shortens the key, then the name, in a very narrow bar', async () => {
    const { nav, resize } = await setup();
    const names = () => Array.from(nav().querySelectorAll('.bd__crumb, .rm__trigger'), (el) => el.textContent?.trim());
    const key = () => nav().querySelector('.bd__key');
    // … 28+13, current 72, key 120 = 233.
    await resize(233);
    expect(names()).toEqual(['…', 'Siebdruck']);
    expect(key()).not.toHaveClass('bd__key--tight');
    // The key shortens, down to the minimum of 88: … 41 + current 72 + 88 = 201.
    await resize(232);
    expect(key()).toHaveClass('bd__key--tight');
    expect(within(nav()).getByText('Siebdruck')).not.toHaveClass('bd__crumb--tight');
    await resize(201);
    expect(key()).toHaveClass('bd__key--tight');
    await resize(200);
    expect(names()).toEqual(['…', 'Siebdruck']);
    expect(key()).toBeNull();
    expect(within(nav()).getByText('Siebdruck')).toHaveClass('bd__crumb--tight');
    // Wide again: the whole path is back.
    await resize(2000);
    expect(within(nav()).queryByRole('button', { name: 'Weitere Ebenen des Pfads' })).toBeNull();
    expect(key()).toBeTruthy();
  });

  it('fits a new path again and draws a root alone', async () => {
    const { nav, view } = await setup();
    view.fixture.componentRef.setInput('nodes', [PATH[0]]);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    await waitFor(() => expect(nav().querySelectorAll('[data-crumb]').length).toBe(1));
    expect(within(nav()).queryAllByRole('button')).toHaveLength(0);
    expect(within(nav()).getByText('Haushalt Studierendenschaft')).toHaveAttribute('aria-current', 'page');
  });

  it('draws nothing for an empty path', async () => {
    const { nav } = await setup([]);
    expect(nav().querySelectorAll('.bd__crumb')).toHaveLength(0);
  });

  it('stops observing on destroy', async () => {
    const { view } = await setup();
    view.fixture.destroy();
    expect(disconnect).toHaveBeenCalled();
  });

  it('copes without a ResizeObserver', async () => {
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = undefined;
    const { nav } = await setup();
    expect(nav().querySelector('.bd__crumb--current')?.textContent).toContain('Siebdruck');
  });
});
