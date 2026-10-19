import { Component, signal } from '@angular/core';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { BudgetAllocationView, BudgetTreeNode } from '../budget-tree.api';
import { CostCentreSelectComponent } from './cost-centre-select.component';

const FIG = (fiscalYearId: string, available: string): BudgetAllocationView => ({
  fiscalYearId,
  allocated: '0',
  bound: '0',
  expended: '0',
  income: '0',
  committed: '0',
  requested: '0',
  available,
});

const NODE = (
  id: string,
  parentId: string | null,
  key: string,
  pathKey: string,
  name: string,
  extra: Partial<BudgetTreeNode> = {},
): BudgetTreeNode => ({
  id,
  parentId,
  gremiumId: null,
  key,
  pathKey,
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
  ...extra,
});

const TREE: BudgetTreeNode[] = [
  NODE('vsm', null, 'VSM', 'VSM', 'VS-Mittel', {
    color: '#4a86d8',
    byFiscalYear: [FIG('fy-v', '9000')],
    children: [
      NODE('p6', 'vsm', '6', 'VSM-6', 'Personalausgaben', {
        byFiscalYear: [FIG('fy-v', '4000')],
        children: [
          NODE('p60', 'p6', '60', 'VSM-6-60', 'Personal', {
            children: [
              NODE('erst', 'p60', '120', 'VSM-6-60-120', 'Erstsemesterparty', {
                color: '#7c4dd8',
                byFiscalYear: [FIG('fy-v', '2750'), FIG('fy-old', '10')],
              }),
              NODE('woche', 'p60', '121', 'VSM-6-60-121', 'Erstsemesterwoche', {
                byFiscalYear: [FIG('fy-v', '980')],
              }),
            ],
          }),
        ],
      }),
    ],
  }),
  NODE('qsm', null, 'QSM', 'QSM', 'QS-Mittel', {
    byFiscalYear: [FIG('fy-q', '500'), FIG('fy-q2', '1')],
    children: [
      NODE('tut', 'qsm', '310', 'QSM-310', 'Ersti-Tutorien', {
        byFiscalYear: [FIG('fy-q', '-120')],
      }),
    ],
  }),
];

@Component({
  standalone: true,
  imports: [CostCentreSelectComponent],
  template: `
    <app-cost-centre-select
      label="Kostenstelle"
      placeholder="Kostenstelle wählen …"
      emptyLabel="Keine Kostenstellen sichtbar."
      [required]="true"
      [nodes]="nodes()"
      [value]="value()"
      [fiscalYearId]="fy()"
      [fiscalYears]="years()"
      (picked)="value.set($event); picks.push($event)"
      (opened)="opens = opens + 1"
    />
    <button type="button">Draußen</button>
  `,
})
class Host {
  readonly nodes = signal<BudgetTreeNode[]>(TREE);
  readonly value = signal('');
  readonly fy = signal('');
  readonly years = signal<ReadonlyMap<string, string>>(new Map([['qsm', 'fy-q']]));
  readonly picks: string[] = [];
  opens = 0;
}

function setPhone(matches: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: matches && query.includes('max-width'),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  })) as unknown as typeof window.matchMedia;
}

async function setup(init: (h: Host) => void = () => undefined) {
  const view = await render(Host);
  init(view.fixture.componentInstance);
  view.fixture.detectChanges();
  const tick = async () => {
    await new Promise((r) => setTimeout(r));
    await new Promise((r) => setTimeout(r));
    view.fixture.detectChanges();
  };
  const field = () => screen.getByRole('button', { name: /^Kostenstelle/ });
  return { view, host: view.fixture.componentInstance, field, tick, user: userEvent.setup() };
}

describe('CostCentreSelectComponent', () => {
  const realMatchMedia = window.matchMedia;
  beforeEach(() => setPhone(false));
  afterEach(() => {
    window.matchMedia = realMatchMedia;
  });

  it('shows the placeholder, then the pick with its swatch and path key', async () => {
    const { field, view, host } = await setup();
    expect(field()).toHaveTextContent('Kostenstelle wählen …');
    expect(field()).toHaveAttribute('aria-expanded', 'false');
    expect(field()).toHaveAttribute('aria-required', 'true');
    host.value.set('erst');
    view.fixture.detectChanges();
    expect(field()).toHaveAccessibleName(/Kostenstelle.*Erstsemesterparty VSM-6-60-120/);
    const swatch = view.container.querySelector<HTMLElement>('.ccs__box .ccs__swatch');
    expect(swatch?.style.background).toBe('rgb(124, 77, 216)');
    // An id the tree does not hold shows the placeholder.
    host.value.set('gone');
    view.fixture.detectChanges();
    expect(field()).toHaveTextContent('Kostenstelle wählen …');
  });

  it('lists every cost centre grouped by its top-level budget with the free amount', async () => {
    const { field, tick, user, host } = await setup((h) => h.fy.set('fy-v'));
    await user.click(field());
    await tick();
    expect(host.opens).toBe(1);
    expect(field()).toHaveAttribute('aria-expanded', 'true');
    const groups = screen.getAllByRole('group');
    expect(groups.map((g) => g.getAttribute('aria-label'))).toEqual([
      'VSM · VS-Mittel',
      'QSM · QS-Mittel',
    ]);
    const erst = screen.getByRole('option', { name: /Erstsemesterparty/ });
    expect(erst).toHaveTextContent('120');
    expect(erst).toHaveTextContent('2.750,00 € frei');
    // The year of the form where the cost centre has it, else the year of its budget.
    const tut = screen.getByRole('option', { name: /Ersti-Tutorien/ });
    expect(tut).toHaveTextContent(/[−-]120,00 € frei/);
    expect(tut.querySelector('.ccs__free--neg')).not.toBeNull();
    // A cost centre without figures shows no amount.
    expect(screen.getByRole('option', { name: /^60 Personal$/ })).not.toHaveTextContent('frei');
    // QSM has two years and none of the form: the year from `fiscalYears`.
    expect(screen.getByRole('option', { name: /QS-Mittel/ })).toHaveTextContent('500,00 € frei');
    await user.click(erst);
    expect(host.picks).toEqual(['erst']);
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(field()).toHaveFocus();
  });

  it('takes the only year of a budget when neither the form nor the map has one', async () => {
    const { field, tick, user } = await setup((h) => h.years.set(new Map()));
    await user.click(field());
    await tick();
    expect(screen.getByRole('option', { name: /^VSM VS-Mittel/ })).toHaveTextContent(
      '9.000,00 € frei',
    );
    expect(screen.getByRole('option', { name: /QS-Mittel/ })).not.toHaveTextContent('frei');
  });

  it('searches, marks the hit and names the parents of the hits', async () => {
    const { field, tick, user, view } = await setup();
    await user.click(field());
    await tick();
    const search = screen.getByRole('combobox', { name: 'Kostenstelle suchen' });
    expect(search).toHaveFocus();
    await user.type(search, 'erst');
    const options = screen
      .getAllByRole('option')
      .map((o) => o.textContent?.replace(/\s+/g, ' ').trim());
    expect(options).toEqual([
      expect.stringContaining('VS-Mittel'),
      expect.stringContaining('Erstsemesterparty'),
      expect.stringContaining('Erstsemesterwoche'),
      expect.stringContaining('QS-Mittel'),
      expect.stringContaining('Ersti-Tutorien'),
    ]);
    const trails = [...view.container.ownerDocument.querySelectorAll('.ccs__trail')].map(
      (t) => t.textContent,
    );
    expect(trails).toEqual(['6 Personalausgaben › 60 Personal']);
    const marks = [...view.container.ownerDocument.querySelectorAll('mark')].map(
      (m) => m.textContent,
    );
    expect(marks).toContain('Erst');
    // The first hit is active, so Enter picks it.
    expect(search).toHaveAttribute(
      'aria-activedescendant',
      screen.getByRole('option', { name: /Erst ?semesterparty/ }).id,
    );
    await user.clear(search);
    await user.type(search, 'zzz');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(screen.getByText('Keine Kostenstelle gefunden.')).toBeInTheDocument();
  });

  it('moves and picks with the keyboard, and closes with Escape', async () => {
    const { field, tick, user, host } = await setup((h) => h.value.set('woche'));
    field().focus();
    await user.keyboard('{ArrowDown}');
    await tick();
    const search = screen.getByRole('combobox', { name: 'Kostenstelle suchen' });
    const active = () =>
      document.getElementById(search.getAttribute('aria-activedescendant') ?? '');
    expect(active()).toHaveTextContent('Erstsemesterwoche');
    expect(screen.getByRole('option', { name: /Erstsemesterwoche/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await user.keyboard('{ArrowUp}');
    expect(active()).toHaveTextContent('Erstsemesterparty');
    await user.keyboard('{Control>}{End}{/Control}');
    expect(active()).toHaveTextContent('Ersti-Tutorien');
    await user.keyboard('{ArrowDown}');
    expect(active()).toHaveTextContent('Ersti-Tutorien');
    await user.keyboard('{Control>}{Home}{/Control}');
    expect(active()).toHaveTextContent('VS-Mittel');
    await user.keyboard('{ArrowUp}{Home}{End}');
    expect(active()).toHaveTextContent('VS-Mittel');
    await user.hover(screen.getByRole('option', { name: /QS-Mittel/ }));
    expect(active()).toHaveTextContent('QS-Mittel');
    await user.keyboard('{Enter}');
    expect(host.picks).toEqual(['qsm']);
    await user.click(field());
    await tick();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(field()).toHaveFocus();
    // The same pick again reports nothing.
    await user.click(field());
    await tick();
    await user.click(screen.getByRole('option', { name: /QS-Mittel/ }));
    expect(host.picks).toEqual(['qsm']);
  });

  it('closes on a press outside, on Tab and on a second press of the field', async () => {
    const { field, tick, user } = await setup();
    await user.click(field());
    await tick();
    await user.click(screen.getByRole('button', { name: 'Draußen' }));
    expect(screen.queryByRole('listbox')).toBeNull();
    await user.click(field());
    await tick();
    await user.keyboard('{Tab}');
    expect(screen.queryByRole('listbox')).toBeNull();
    await user.click(field());
    await tick();
    await user.click(field());
    expect(screen.queryByRole('listbox')).toBeNull();
    // Enter on an empty list picks nothing.
    await user.click(field());
    await tick();
    await user.type(screen.getByRole('combobox'), 'zzz{Enter}');
    expect(screen.getByText('Keine Kostenstelle gefunden.')).toBeInTheDocument();
  });

  it('says so when the tree is empty', async () => {
    const { field, tick, user } = await setup((h) => h.nodes.set([]));
    await user.click(field());
    await tick();
    expect(screen.getByText('Keine Kostenstellen sichtbar.')).toBeInTheDocument();
  });

  it('follows a scroll of the page and closes when the field leaves the viewport', async () => {
    const { field, tick, user, view } = await setup();
    await user.click(field());
    await tick();
    window.dispatchEvent(new Event('resize'));
    view.fixture.detectChanges();
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    jest.spyOn(field(), 'getBoundingClientRect').mockReturnValue({
      top: -200,
      bottom: -100,
      left: 0,
      right: 100,
      width: 100,
      height: 100,
      x: 0,
      y: -200,
      toJSON: () => ({}),
    });
    window.dispatchEvent(new Event('scroll'));
    view.fixture.detectChanges();
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('opens the list in the shared bottom sheet on a phone', async () => {
    setPhone(true);
    const { field, tick, user, host } = await setup();
    await user.click(field());
    await tick();
    const sheet = screen.getByRole('dialog', { name: 'Kostenstelle' });
    expect(document.querySelector('.ccs__menu')).toBeNull();
    await user.click(within(sheet).getByRole('option', { name: /Erstsemesterwoche/ }));
    expect(host.picks).toEqual(['woche']);
    expect(screen.queryByRole('dialog')).toBeNull();
    await user.click(field());
    await tick();
    await user.click(within(screen.getByRole('dialog')).getAllByRole('button')[0]);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('opens above the field when the room below is too small, inside the viewport', async () => {
    const { field, tick, user } = await setup();
    const rect = (top: number, left: number, width: number): DOMRect =>
      ({
        top,
        bottom: top + 56,
        left,
        right: left + width,
        width,
        height: 56,
        x: left,
        y: top,
        toJSON: () => ({}),
      }) as DOMRect;
    jest.spyOn(field(), 'getBoundingClientRect').mockReturnValue(rect(700, 900, 300));
    const [h, w] = [window.innerHeight, window.innerWidth];
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1200 });
    jest.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(400);
    await user.click(field());
    await tick();
    const menu = document.querySelector<HTMLElement>('.ccs__menu');
    // 400 px tall, above the field; 520 px wide, pulled left to stay inside the viewport.
    expect(menu?.style.top).toBe('296px');
    expect(menu?.style.width).toBe('520px');
    expect(menu?.style.left).toBe('672px');
    // A scroll inside the list moves nothing.
    menu?.querySelector('.ccs__search')?.dispatchEvent(new Event('scroll'));
    expect(menu?.style.top).toBe('296px');
    jest.restoreAllMocks();
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: h });
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: w });
  });

  it('finds a cost centre by its key, and keeps the sheet open on Tab on a phone', async () => {
    setPhone(true);
    const { field, tick, user } = await setup();
    await user.click(field());
    await tick();
    const search = within(screen.getByRole('dialog')).getByRole('combobox');
    await user.type(search, '310');
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([
      expect.stringContaining('QS-Mittel'),
      expect.stringContaining('Ersti-Tutorien'),
    ]);
    search.focus();
    await user.keyboard('{Tab}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('shows the card of a transfer leg with the projected lines and no chevron', async () => {
    @Component({
      standalone: true,
      imports: [CostCentreSelectComponent],
      template: `<app-cost-centre-select variant="card" label="Von" [nodes]="nodes" value="erst"
        ><span class="extra">Frei danach</span></app-cost-centre-select
      >`,
    })
    class CardHost {
      readonly nodes = TREE;
    }
    const view = await render(CardHost);
    const button = screen.getByRole('button', { name: /^Von/ });
    expect(button).toHaveTextContent('Erstsemesterparty');
    expect(button).toHaveTextContent('Frei danach');
    expect(view.container.querySelector('app-cost-centre-select')).toHaveClass('ccs--card');
    expect(view.container.querySelector('.ccs__chevron')).toBeNull();
  });
});
