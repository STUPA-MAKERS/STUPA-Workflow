import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { BudgetTreeNode, Expense } from '../../budget/budget-tree.api';
import { costCentreIndex } from '../../budget/expense-display.util';
import { BulkPanelComponent } from './bulk-panel.component';

const TREE: BudgetTreeNode[] = [
  {
    id: 'top',
    parentId: null,
    gremiumId: null,
    key: 'VS',
    pathKey: 'VS',
    name: 'Gesamthaushalt',
    currency: 'EUR',
    active: true,
    color: '#72a384',
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [],
  },
];

const ROW: Expense = {
  id: 'e-1',
  budgetId: 'top',
  pathKey: 'VS',
  fiscalYearId: 'fy',
  kind: 'expense',
  amount: '380.00',
  currency: 'EUR',
  description: 'Getränke Erstsemester-Frühstück',
  applicationId: null,
  applicationTitle: null,
  transferId: null,
  actor: null,
  actorName: null,
  invoiceDate: null,
  paymentDate: '2026-09-28',
  correspondent: null,
  note: null,
  referenceNumber: null,
  paymentMethod: null,
  category: null,
  invoiceId: null,
  invoiceNumber: null,
  parentExpenseId: null,
  childCount: 0,
  createdAt: '2026-09-28T00:00:00Z',
};

async function setup(inputs: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const handlers = { reassign: jest.fn(), exported: jest.fn(), remove: jest.fn(), closed: jest.fn() };
  const view = await render(BulkPanelComponent, {
    inputs: {
      rows: [ROW, { ...ROW, id: 'e-2', description: 'Honorar', amount: '640.00', applicationId: 'a' }],
      costCentres: costCentreIndex(TREE),
      tree: TREE,
      canExport: true,
      ...inputs,
    },
    on: handlers,
  });
  return { view, ...handlers, user: userEvent.setup() };
}

describe('BulkPanelComponent', () => {
  it('names the selection with its common cost centre and its sum', async () => {
    await setup();
    expect(screen.getByRole('heading', { name: '2 Buchungen ausgewählt' })).toBeInTheDocument();
    expect(screen.getAllByText('Gesamthaushalt').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/−1\.020,00/).length).toBe(2);
    // The bound booking keeps its cost centre: the hint names it.
    expect(screen.getByText(/„Honorar“ ist mit einem Antrag verknüpft/)).toBeInTheDocument();
  });

  it('leaves out the common cost centre of mixed rows and signs a positive sum', async () => {
    await setup({
      rows: [
        { ...ROW, kind: 'income', amount: '500.00' },
        { ...ROW, id: 'e-2', budgetId: 'other', amount: '100.00' },
      ],
    });
    expect(screen.getAllByText(/\+400,00/).length).toBe(2);
    expect(screen.queryByText(/ist mit einem Antrag verknüpft/)).toBeNull();
  });

  it('sums an even selection without a sign', async () => {
    await setup({ rows: [{ ...ROW, kind: 'income' }, { ...ROW, id: 'e-2' }] });
    expect(screen.getAllByText(/^0,00/).length).toBe(2);
  });

  it('picks a cost centre and a category, then reassigns', async () => {
    const { view, reassign, user } = await setup();
    const apply = screen.getByRole('button', { name: 'Übernehmen' });
    expect(apply).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /Kostenstelle/ }));
    await user.click(screen.getByRole('button', { name: /Gesamthaushalt/ }));
    expect(view.fixture.componentInstance.budgetId()).toBe('top');
    view.fixture.detectChanges();
    await user.click(screen.getByRole('button', { name: 'Übernehmen' }));
    expect(reassign).toHaveBeenCalled();
  });

  it('runs the export, the delete and the close', async () => {
    const { exported, remove, closed, user } = await setup();
    await user.click(screen.getByRole('button', { name: 'Exportieren' }));
    expect(exported).toHaveBeenCalled();
    expect(screen.getByText('Sammel-Löschen gilt für höchstens 5 Buchungen.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '2 Buchungen löschen' }));
    expect(remove).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Auswahl beenden' }));
    expect(closed).toHaveBeenCalled();
  });

  it('turns the delete off with its reason and hides the export without the right', async () => {
    await setup({ deleteReason: 'Zu viele', canExport: false });
    expect(screen.getByText('Zu viele')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '2 Buchungen löschen' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Exportieren' })).toBeNull();
  });

  it('shows only the reassign form in its sheet variant', async () => {
    await setup({ variant: 'reassign', rows: [] });
    expect(screen.queryByRole('heading')).toBeNull();
    expect(screen.getByRole('button', { name: 'Übernehmen' })).toBeInTheDocument();
  });
});
