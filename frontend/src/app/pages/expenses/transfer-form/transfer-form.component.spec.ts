import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { BudgetTransfer, BudgetTreeNode } from '../../budget/budget-tree.api';
import { costCentreIndex } from '../../budget/expense-display.util';
import { currentFiscalYear, ExpenseDialogsState } from '../expense-dialogs.state';
import { ExpenseSubBookingsState } from '../expense-sub-bookings.state';
import { ExpenseTransfersState } from '../expense-transfers.state';
import { ExpensesListState } from '../expenses-list.state';
import { TransferFormComponent } from './transfer-form.component';

const FIG = (available: string) => [
  {
    fiscalYearId: 'fy',
    allocated: '0',
    bound: '0',
    expended: '0',
    income: '0',
    committed: '0',
    requested: '0',
    available,
  },
];

const LEAF = (id: string, name: string, key: string, available: string): BudgetTreeNode => ({
  id,
  parentId: 'top',
  gremiumId: null,
  key,
  pathKey: `VS-${key}`,
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
  byFiscalYear: FIG(available),
  children: [],
});

const TREE: BudgetTreeNode[] = [
  {
    ...LEAF('top', 'Gesamthaushalt', 'VS', '0'),
    parentId: null,
    pathKey: 'VS',
    children: [
      LEAF('kul', 'Kultur', '400', '11150'),
      LEAF('sport', 'Hochschulsport', '300', '7100'),
    ],
  },
];

const TRANSFER: BudgetTransfer = {
  transferId: 'tr-1',
  expenseId: 'e-a',
  incomeId: 'e-b',
  fromBudgetId: 'kul',
  fromPathKey: 'VS-400',
  toBudgetId: 'sport',
  toPathKey: 'VS-300',
  fiscalYearId: 'fy',
  amount: '500.00',
  currency: 'EUR',
  description: 'Zuschuss Turnierfahrt',
  note: null,
  invoiceDate: null,
  paymentDate: null,
  actor: null,
  actorName: null,
  createdAt: '2026-10-01T00:00:00Z',
};

const FY = {
  id: 'fy',
  budgetId: 'top',
  year: 2026,
  display: '2026',
  startDate: '',
  endDate: '',
  active: true,
};

let MODE: 'create' | 'edit' = 'create';
let LAYOUT: 'pane' | 'sheet' = 'pane';

@Component({
  standalone: true,
  imports: [TransferFormComponent],
  template: `
    <app-transfer-form
      [dialogs]="dialogs"
      [transfers]="transfers"
      [mode]="mode"
      [layout]="layout"
      [tree]="tree"
      [costCentres]="costCentres"
      fyLabel="2026"
      (remove)="removed = removed + 1"
    />
  `,
})
class HostComponent {
  readonly list = new ExpensesListState();
  readonly sub = new ExpenseSubBookingsState(this.list);
  readonly transfers = new ExpenseTransfersState(this.list);
  readonly dialogs = new ExpenseDialogsState(this.list, this.sub, this.transfers);
  readonly mode = MODE;
  readonly layout = LAYOUT;
  readonly tree = TREE;
  readonly costCentres = costCentreIndex(TREE);
  removed = 0;
}

async function setup(mode: 'create' | 'edit', layout: 'pane' | 'sheet' = 'pane') {
  localStorage.setItem('ap.locale', 'de');
  MODE = mode;
  LAYOUT = layout;
  const view = await render(HostComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = TestBed.inject(HttpTestingController);
  http.match((r) => r.url.endsWith('/budgets')).forEach((r) => r.flush(TREE));
  http
    .match((r) => r.url.endsWith('/invoices'))
    .forEach((r) => r.flush({ items: [], total: 0, limit: 200, offset: 0 }));
  const host = view.fixture.componentInstance;
  if (mode === 'create') {
    host.dialogs.openTransfer();
  } else host.transfers.openEdit(TRANSFER);
  view.fixture.detectChanges();
  const form = view.fixture.debugElement.children[0].componentInstance as TransferFormComponent;
  return { view, http, host, form, user: userEvent.setup() };
}

// The suite renders the whole transfer form with its two cost-centre trees
// in jsdom. One test takes 1–3 s alone, and more than the default 5 s while the full
// run keeps every core busy, so local gates timed out at random (CI passed). The same
// budget as the other heavy meeting suites.
jest.setTimeout(15_000);

const tick = () => new Promise((r) => setTimeout(r));
const text = () => (document.body.textContent ?? '').replace(/\s+/g, ' ');

describe('TransferFormComponent', () => {
  const realMatchMedia = window.matchMedia;
  beforeEach(() => {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => {
    window.matchMedia = realMatchMedia;
    TestBed.inject(HttpTestingController).verify();
  });

  it('picks the two legs in the cost-centre list and shows the free amount before and after', async () => {
    const { host, http, view, user } = await setup('create');
    expect(screen.getByRole('heading', { name: 'Übertrag buchen' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Von → nach' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Von Kostenstelle/ }));
    await tick();
    view.fixture.detectChanges();
    // Opening the list asks once for the years of the top budgets, for the free amounts.
    http.expectOne((r) => r.url.endsWith('/budgets/top/fiscal-years')).flush([FY]);
    await user.click(screen.getByRole('option', { name: /Kultur/ }));
    expect(host.dialogs.tFromId()).toBe('kul');
    http.expectOne((r) => r.url.endsWith('/budgets/top/fiscal-years')).flush([FY]);
    view.fixture.detectChanges();
    // Without an amount: the free amount as it is.
    expect(text()).toMatch(/Frei danach ?11\.150,00 €/);
    // The same cost centre twice is no pair.
    host.dialogs.tToId.set('kul');
    view.fixture.detectChanges();
    expect(screen.getByRole('alert').textContent).toContain('andere Kostenstelle');
    await user.click(screen.getByRole('button', { name: /^Zu Kostenstelle/ }));
    await tick();
    view.fixture.detectChanges();
    await user.click(screen.getByRole('option', { name: /Hochschulsport/ }));
    expect(host.dialogs.tToId()).toBe('sport');
    host.dialogs.tAmount.set('500');
    view.fixture.detectChanges();
    expect(text()).toMatch(/Frei danach ?11\.150,00 € 10\.650,00 €/);
    expect(text()).toMatch(/Frei danach ?7\.100,00 € 7\.600,00 €/);
    expect(document.querySelectorAll('s')).toHaveLength(2);
    // No description yet: the main action waits.
    expect(screen.getByRole('button', { name: /^500,00\s€ übertragen$/ })).toBeDisabled();
    host.dialogs.tDescription.set('Zuschuss');
    view.fixture.detectChanges();
    expect(screen.getByRole('button', { name: /^500,00\s€ übertragen$/ })).toBeEnabled();
  });

  it('swaps the direction and keeps the year inside one budget', async () => {
    const { host, view, user } = await setup('create');
    host.dialogs.tFromId.set('kul');
    host.dialogs.tToId.set('sport');
    host.dialogs.tFiscalYearId.set('fy');
    view.fixture.detectChanges();
    await user.click(screen.getByRole('button', { name: 'Richtung tauschen' }));
    expect(host.dialogs.tFromId()).toBe('sport');
    expect(host.dialogs.tToId()).toBe('kul');
    expect(host.dialogs.tFiscalYearId()).toBe('fy');
  });

  it('swaps a single leg: the target becomes the source and its years load', async () => {
    const { host, http, view, user } = await setup('create');
    host.dialogs.tToId.set('sport');
    view.fixture.detectChanges();
    await user.click(screen.getByRole('button', { name: 'Tauschen' }));
    expect(host.dialogs.tFromId()).toBe('sport');
    expect(host.dialogs.tToId()).toBe('');
    http.expectOne((r) => r.url.endsWith('/budgets/top/fiscal-years')).flush([FY]);
    expect(host.dialogs.tFiscalYearId()).toBe('fy');
    // Nothing to swap.
    host.dialogs.tFromId.set('');
    host.dialogs.swapTransfer();
    expect(host.dialogs.tToId()).toBe('');
  });

  it('loads the year of each top budget once, and again after a failure', async () => {
    const { host, http } = await setup('create');
    const years = () => http.match((r) => r.url.endsWith('/budgets/top/fiscal-years'));
    host.dialogs.loadTopFiscalYears();
    years()[0].flush({}, { status: 500, statusText: 'x' });
    expect(host.dialogs.topFiscalYears().size).toBe(0);
    host.dialogs.loadTopFiscalYears();
    years()[0].flush([FY]);
    expect(host.dialogs.topFiscalYears().get('top')).toBe('fy');
    host.dialogs.loadTopFiscalYears();
    expect(years()).toHaveLength(0);
  });

  it('ignores a pick without an id', async () => {
    const { form, host } = await setup('create');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (form as any).pick('to', '');
    expect(host.dialogs.tToId()).toBe('');
  });

  it('shows no free amounts while the fiscal year is not chosen', async () => {
    const { host, view } = await setup('create');
    host.dialogs.tFromId.set('kul');
    host.dialogs.tToId.set('sport');
    host.dialogs.tFiscalYearId.set('');
    view.fixture.detectChanges();
    expect(text()).not.toContain('Frei danach');
    expect(screen.getByRole('button', { name: 'Übertragen' })).toBeDisabled();
  });

  it('submits and cancels a new transfer with the buttons of the foot', async () => {
    const { host, view, user } = await setup('create');
    const create = jest.spyOn(host.dialogs, 'createTransfer').mockImplementation(() => undefined);
    host.dialogs.tFromId.set('kul');
    host.dialogs.tToId.set('sport');
    host.dialogs.tFiscalYearId.set('fy');
    host.dialogs.tAmount.set('20');
    host.dialogs.tDescription.set('Zuschuss');
    view.fixture.detectChanges();
    await user.click(screen.getByRole('button', { name: /^20,00\s€ übertragen$/ }));
    expect(create).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(host.dialogs.transferOpen()).toBe(false);
  });

  it('locks the pair in the edit and deletes, saves or cancels', async () => {
    const { host, form, view, user } = await setup('edit');
    expect(screen.getByRole('heading', { name: 'Übertrag bearbeiten' })).toBeInTheDocument();
    expect(screen.getByText('Kultur')).toBeInTheDocument();
    expect(screen.getByText('Hochschulsport')).toBeInTheDocument();
    expect(screen.getByText('2026')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Von Kostenstelle/ })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Löschen' }));
    expect(view.fixture.componentInstance.removed).toBe(1);
    const save = jest.spyOn(host.transfers, 'saveEdit').mockImplementation(() => undefined);
    form.submit(new Event('submit'));
    expect(save).toHaveBeenCalled();
    form.close();
    expect(host.transfers.editing()).toBeNull();
  });

  it('leaves out its head in the bottom sheet', async () => {
    await setup('edit', 'sheet');
    expect(screen.queryByRole('heading', { name: 'Übertrag bearbeiten' })).toBeNull();
  });
});

describe('currentFiscalYear', () => {
  it('takes the year that holds today, else the only active one', () => {
    const y = (id: string, startDate: string, endDate: string, active: boolean) => ({
      ...FY,
      id,
      startDate,
      endDate,
      active,
    });
    const today = new Date('2026-10-19T12:00:00Z');
    const fys = [
      y('a', '2025-01-01', '2025-12-31', true),
      y('b', '2026-01-01', '2026-12-31', false),
    ];
    expect(currentFiscalYear(fys, today)?.id).toBe('b');
    expect(currentFiscalYear([fys[0]], today)?.id).toBe('a');
    expect(currentFiscalYear([fys[0], { ...fys[0], id: 'c' }], today)).toBeNull();
    expect(currentFiscalYear([])).toBeNull();
  });
});
