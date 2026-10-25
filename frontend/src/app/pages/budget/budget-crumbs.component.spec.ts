import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { runAxe } from '../../../testing/a11y';
import {
  BudgetCrumbsComponent,
  type CrumbFit,
  type CrumbMetrics,
  fitCrumbs,
  visibleParents,
} from './budget-crumbs.component';
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

/** The fit with the key text as wide as the whole key and no lead, unless a test sets them. */
const fit = (m: Omit<CrumbMetrics, 'keyText' | 'lead'> & Partial<Pick<CrumbMetrics, 'keyText' | 'lead'>>) =>
  fitCrumbs({ keyText: m.key, lead: 0, ...m });

/**
 * What the trail draws for a fit, as the stylesheet lays it out: the key keeps the gap and
 * its margin before it, and only its text shortens; the leading "…" moves to the start.
 */
function drawn(m: CrumbMetrics, f: CrumbFit): number {
  const parents = m.widths.length - 1;
  const short = (w: number) => Math.min(w, m.min);
  const shortParents = f.squeeze === 'parents' || f.squeeze === 'name';
  let total = f.squeeze === 'name' ? short(m.widths[parents]) : m.widths[parents];
  total += m.key - m.keyText + (f.squeeze === 'none' ? m.keyText : short(m.keyText));
  if (f.hidden > 0) total += m.more + m.sep - (f.hidden >= parents ? m.lead : 0);
  for (const i of visibleParents(parents, f.hidden)) total += (shortParents ? short(m.widths[i]) : m.widths[i]) + m.sep;
  return total;
}

describe('fitCrumbs', () => {
  it('shows every crumb when the natural widths fit', () => {
    expect(fit({ ...base, widths: [200, 90, 60], available: 392 })).toEqual({ hidden: 0, squeeze: 'none' });
  });

  /**
   * There are five levels: root 200, two levels between (150, 120), parent 100, current 60, key
   * 150. Step 1 keeps all at full width: 630 + 4 × 21 + key 150 = 864. Step 2 (root 200+21, …
   * 28+21, parent 100+21, current 60, key 150 = 601) puts the two levels between into the menu, and
   * the rest keeps its full width. Step 3 shortens the key to the minimum of 88: 539. Step 4
   * shortens root and parent too (88 each): 88+21 + 49 + 88+21 + 60 + 88 = 415. Step 5 is "… ›
   * current" with the full key (49 + 60 + 150 = 259), then the short key (197). Step 6 shortens the
   * current name.
   */
  it('goes through the steps in order, at their exact boundaries', () => {
    const m = { ...base, key: 150, widths: [200, 150, 120, 100, 60] };
    const at = (available: number) => fit({ ...m, available });
    expect(at(864)).toEqual({ hidden: 0, squeeze: 'none' });
    expect(at(863)).toEqual({ hidden: 2, squeeze: 'none' });
    expect(at(601)).toEqual({ hidden: 2, squeeze: 'none' });
    expect(at(600)).toEqual({ hidden: 2, squeeze: 'key' });
    expect(at(539)).toEqual({ hidden: 2, squeeze: 'key' });
    expect(at(538)).toEqual({ hidden: 2, squeeze: 'parents' });
    expect(at(415)).toEqual({ hidden: 2, squeeze: 'parents' });
    expect(at(414)).toEqual({ hidden: 4, squeeze: 'none' });
    expect(at(259)).toEqual({ hidden: 4, squeeze: 'none' });
    expect(at(258)).toEqual({ hidden: 4, squeeze: 'key' });
    expect(at(197)).toEqual({ hidden: 4, squeeze: 'key' });
    expect(at(196)).toEqual({ hidden: 4, squeeze: 'name' });
  });

  /**
   * Full width is 200+21 + 100+21 + 60 + 150 = 552, and shortened 88+21 + 88+21 + 60 + 88 = 366.
   */
  it('has nothing between to hide for root › parent › current', () => {
    const m = { ...base, key: 150, widths: [200, 100, 60] };
    expect(fit({ ...m, available: 552 })).toEqual({ hidden: 0, squeeze: 'none' });
    expect(fit({ ...m, available: 551 })).toEqual({ hidden: 0, squeeze: 'key' });
    expect(fit({ ...m, available: 366 })).toEqual({ hidden: 0, squeeze: 'parents' });
    expect(fit({ ...m, available: 365 })).toEqual({ hidden: 2, squeeze: 'none' });
  });

  /**
   * Root 50 and key 40 are below the minimum: 50+21 + 300+21 + 60 + 40 = 492, and the shortened
   * step only shortens the long parent: 50+21 + 88+21 + 60 + 40 = 280.
   */
  it('keeps a parent or a key that is shorter than the minimum at its own width', () => {
    const m = { ...base, key: 40, widths: [50, 300, 60] };
    expect(fit({ ...m, available: 491 })).toEqual({ hidden: 0, squeeze: 'parents' });
    expect(fit({ ...m, available: 280 })).toEqual({ hidden: 0, squeeze: 'parents' });
    expect(fit({ ...m, available: 279 })).toEqual({ hidden: 2, squeeze: 'none' });
  });

  it('has nothing to hide for a root alone, and nothing at all for an empty path', () => {
    expect(fit({ ...base, widths: [100], key: 50, available: 150 })).toEqual({ hidden: 0, squeeze: 'none' });
    expect(fit({ ...base, widths: [100], key: 50, available: 149 })).toEqual({ hidden: 0, squeeze: 'name' });
    expect(fit({ ...base, widths: [], available: 10 })).toEqual({ hidden: 0, squeeze: 'none' });
  });
});

describe('fitCrumbs against the drawn trail', () => {
  /**
   * The widths are those of the browser: gap 4, key margin 8 and key text 120 (key 132), minimum
   * 72, a separator 13 + 2 × 4, the "…" 28 with a lead of 8.
   */
  const m: Omit<CrumbMetrics, 'available'> = {
    widths: [216, 96, 344, 72, 72],
    key: 132,
    keyText: 120,
    min: 72,
    sep: 21,
    more: 28,
    lead: 8,
  };

  /** Step 3 is root 216+21, … 28+21, parent 72+21, current 72, key 4+8+72 = 535. */
  it('counts the short key with the space before it, at the step 3/4 boundary', () => {
    expect(fitCrumbs({ ...m, available: 535 })).toEqual({ hidden: 2, squeeze: 'key' });
    expect(drawn({ ...m, available: 535 }, fitCrumbs({ ...m, available: 535 }))).toBe(535);
    expect(fitCrumbs({ ...m, available: 534 })).toEqual({ hidden: 2, squeeze: 'parents' });
  });

  /** "… › current" with the full key is 28+21 − 8 + 72 + 132 = 245. */
  it('gets the lead of the "…" back when it leads the trail', () => {
    expect(fitCrumbs({ ...m, available: 245 })).toEqual({ hidden: 4, squeeze: 'none' });
    expect(fitCrumbs({ ...m, available: 244 })).toEqual({ hidden: 4, squeeze: 'key' });
  });

  /** The last step shortens the name as far as it must; the stylesheet does the rest. */
  it('never draws more than the bar holds, from a narrow bar to a wide one', () => {
    for (let available = 190; available <= 1200; available++) {
      const f = fitCrumbs({ ...m, available });
      if (f.squeeze === 'name') continue;
      expect(drawn({ ...m, available }, f)).toBeLessThanOrEqual(available);
    }
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

  /**
   * The hidden names measure 8px per character; the minimum, the "…" and the key have fixed widths.
   */
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

  /**
   * A parent keeps its natural width as its floor (below the minimum). jsdom drops custom
   * properties from the style, so the value is read from the source.
   */
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
    const c = view.fixture.componentInstance as unknown as { crumbWidth(i: number): string | null };
    expect(c.crumbWidth(3)).toBe('72px');
    expect((view.fixture.componentInstance as unknown as { keyWidth(): string | null }).keyWidth()).toBe('120px');
    expect(c.crumbWidth(9)).toBeNull();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('goes up on a click of a parent', async () => {
    const { nav, picks } = await setup();
    await userEvent.setup().click(within(nav()).getByRole('button', { name: 'Fachschaften' }));
    expect(picks).toEqual(['fs']);
  });

  /**
   * The trail is root 216+13, … 28+13, Werkstatt 72+13, current 72, key 120 = 547, so nothing
   * shortens yet.
   */
  it('keeps the first level, the parent and the current crumb, with the levels between in a "…" menu', async () => {
    const { nav, picks, resize, view } = await setup();
    await resize(547);
    const trail = within(nav());
    const names = Array.from(nav().querySelectorAll('.bd__crumb, .rm__trigger'), (el) => el.textContent?.trim());
    expect(names).toEqual(['Haushalt Studierendenschaft', '…', 'Werkstatt', 'Siebdruck']);
    expect(nav()).not.toHaveClass('bd__crumbs--parents');
    expect(nav().querySelector('.bd__key')).not.toHaveClass('bd__key--tight');
    expect(nav().querySelector('.bd__more')).not.toHaveClass('bd__more--lead');
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

  /**
   * The key at its minimum of 88 gives 547 − 120 + 88 = 515. Then root and parent shorten too, and
   * the key stays at its minimum: root 88+13, … 41, Werkstatt (below the minimum) 72+13, current
   * 72, key 88 = 387. "… › current" with the full key is 41 + 72 + 120 = 233, and the "…" leads the
   * trail. The short key gives 41 + 72 + 88 = 201. Last, the name shortens, and the short key
   * stays. When wide again, the whole path is back.
   */
  it('shortens the key, then the parents, then hides them, and shortens the name last', async () => {
    const { nav, resize } = await setup();
    const names = () => Array.from(nav().querySelectorAll('.bd__crumb, .rm__trigger'), (el) => el.textContent?.trim());
    const key = () => nav().querySelector('.bd__key');
    const current = () => within(nav()).getByText('Siebdruck');
    await resize(546);
    expect(key()).toHaveClass('bd__key--tight');
    expect(nav()).not.toHaveClass('bd__crumbs--parents');
    await resize(515);
    expect(nav()).not.toHaveClass('bd__crumbs--parents');
    expect(key()).not.toHaveClass('bd__key--min');
    await resize(514);
    expect(nav()).toHaveClass('bd__crumbs--parents');
    expect(key()).toHaveClass('bd__key--min');
    expect(names()).toEqual(['Haushalt Studierendenschaft', '…', 'Werkstatt', 'Siebdruck']);
    await resize(387);
    expect(names()).toHaveLength(4);
    await resize(386);
    expect(names()).toEqual(['…', 'Siebdruck']);
    expect(key()).not.toHaveClass('bd__key--min');
    expect(nav().querySelector('.bd__more')).toHaveClass('bd__more--lead');
    expect(key()).not.toHaveClass('bd__key--tight');
    await resize(233);
    expect(key()).not.toHaveClass('bd__key--tight');
    await resize(232);
    expect(key()).toHaveClass('bd__key--tight');
    expect(current()).not.toHaveClass('bd__crumb--tight');
    await resize(201);
    expect(current()).not.toHaveClass('bd__crumb--tight');
    await resize(200);
    expect(current()).toHaveClass('bd__crumb--tight');
    expect(key()).toHaveClass('bd__key--min');
    expect(key()?.getAttribute('title')).toBe('HH-200-230-231-2311');
    await resize(2000);
    expect(within(nav()).queryByRole('button', { name: 'Weitere Ebenen des Pfads' })).toBeNull();
    expect(key()).not.toHaveClass('bd__key--tight');
  });

  /** A click on a parent does the same. */
  it('moves the focus to the current crumb of the new path after a pick', async () => {
    const { nav, picks, resize, view } = await setup();
    view.fixture.componentInstance.pick.subscribe((id: string) => {
      view.fixture.componentRef.setInput('nodes', PATH.slice(0, PATH.findIndex((n) => n.id === id) + 1));
    });
    await resize(547);
    const user = userEvent.setup();
    await user.click(within(nav()).getByRole('button', { name: 'Weitere Ebenen des Pfads' }));
    await user.keyboard('{ArrowDown}{Enter}');
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    expect(picks).toEqual(['gm']);
    await waitFor(() => expect(document.activeElement?.textContent?.trim()).toBe('Fachschaft Gestaltung und angewandte Medien'));
    expect(document.activeElement).toHaveAttribute('aria-current', 'page');
    await resize(2000);
    await user.click(within(nav()).getByRole('button', { name: 'Haushalt Studierendenschaft' }));
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    await waitFor(() => expect(document.activeElement?.textContent?.trim()).toBe('Haushalt Studierendenschaft'));
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
