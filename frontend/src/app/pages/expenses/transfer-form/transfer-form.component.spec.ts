import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { BudgetTransfer, BudgetTreeNode } from '../../budget/budget-tree.api';
import { costCentreIndex } from '../../budget/expense-display.util';
import { ExpenseDialogsState } from '../expense-dialogs.state';
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
    children: [LEAF('kul', 'Kultur', '400', '11150'), LEAF('sport', 'Hochschulsport', '300', '7100')],
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
    providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
  });
  const http = TestBed.inject(HttpTestingController);
  http.match((r) => r.url.endsWith('/budgets')).forEach((r) => r.flush(TREE));
  http.match((r) => r.url.endsWith('/invoices')).forEach((r) => r.flush({ items: [], total: 0, limit: 200, offset: 0 }));
  const host = view.fixture.componentInstance;
  if (mode === 'create') host.dialogs.openTransfer();
  else host.transfers.openEdit(TRANSFER);
  view.fixture.detectChanges();
  const form = view.fixture.debugElement.children[0].componentInstance as TransferFormComponent;
  return { view, http, host, form, user: userEvent.setup() };
}

describe('TransferFormComponent', () => {
  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('picks the pair from the tree and shows how it books, with the amount left', async () => {
    const { host, http, view, user } = await setup('create');
    expect(screen.getByRole('heading', { name: 'Übertrag buchen' })).toBeInTheDocument();
    expect(screen.getByText('Wähle die beiden Kostenstellen.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Von Kostenstelle/ }));
    await user.click(screen.getByRole('button', { name: /Kultur/ }));
    expect(host.dialogs.tFromId()).toBe('kul');
    http.expectOne((r) => r.url.endsWith('/budgets/top/fiscal-years')).flush([
      { id: 'fy', budgetId: 'top', year: 2026, display: '2026', startDate: '', endDate: '', active: true },
    ]);
    // The same cost centre twice is no pair.
    host.dialogs.tToId.set('kul');
    view.fixture.detectChanges();
    expect(screen.getByRole('alert').textContent).toContain('andere Kostenstelle');
    await user.click(screen.getByRole('button', { name: /Zu Kostenstelle/ }));
    await user.click(screen.getByRole('button', { name: /Hochschulsport/ }));
    expect(host.dialogs.tToId()).toBe('sport');
    host.dialogs.tAmount.set('500');
    view.fixture.detectChanges();
    const text = (document.body.textContent ?? '').replace(/\s+/g, ' ');
    expect(text).toContain('verfügbar danach 10.650,00 €');
    expect(text).toContain('verfügbar danach 7.600,00 €');
    expect(text).toContain('−500,00 €');
    expect(text).toContain('+500,00 €');
  });

  it('opens and closes a tree with the same field, and ignores the "all" node', async () => {
    const { form, host } = await setup('create');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const f = form as any;
    f.toggle('to');
    expect(f.picking()).toBe('to');
    f.toggle('to');
    expect(f.picking()).toBeNull();
    f.pick('to', '');
    expect(host.dialogs.tToId()).toBe('');
  });

  it('shows the pair without figures when the fiscal year is not chosen', async () => {
    const { host, view } = await setup('create');
    host.dialogs.tFromId.set('kul');
    host.dialogs.tToId.set('sport');
    host.dialogs.tFiscalYearId.set('');
    view.fixture.detectChanges();
    expect(document.body.textContent).not.toContain('verfügbar danach');
  });

  it('submits and cancels a new transfer', async () => {
    const { host, form } = await setup('create');
    const create = jest.spyOn(host.dialogs, 'createTransfer').mockImplementation(() => undefined);
    form.submit(new Event('submit'));
    expect(create).toHaveBeenCalled();
    form.close();
    expect(host.dialogs.transferOpen()).toBe(false);
  });

  it('shows the fixed pair in the edit and deletes, saves or cancels', async () => {
    const { host, form, view, user } = await setup('edit');
    expect(screen.getByRole('heading', { name: 'Übertrag bearbeiten' })).toBeInTheDocument();
    expect(screen.getByText('Kultur')).toBeInTheDocument();
    expect(screen.getByText('HHJ 2026')).toBeInTheDocument();
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
