import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { BudgetTransfer } from '../../budget/budget-tree.api';
import type { CostCentreLabel } from '../../budget/expense-display.util';
import { TransferDetailComponent } from './transfer-detail.component';

const TRANSFER: BudgetTransfer = {
  transferId: 'tr-1',
  expenseId: 'e-a',
  incomeId: 'e-b',
  fromBudgetId: 'b-1',
  fromPathKey: 'VS-900',
  toBudgetId: 'b-2',
  toPathKey: 'VS-300',
  fiscalYearId: 'fy',
  amount: '2500.00',
  currency: 'EUR',
  description: 'Zuschuss Hallensanierung',
  note: 'Beschluss des Finanzausschusses',
  invoiceDate: null,
  paymentDate: '2025-11-17',
  actor: 'sub',
  actorName: 'Mara Keller',
  createdAt: '2025-11-17T10:02:00Z',
};

const CC = new Map<string, CostCentreLabel>([
  ['b-1', { name: 'Rücklagen', path: 'VS-900', color: '#888888' }],
  ['b-2', { name: 'Hochschulsport', path: 'VS-300', color: null }],
]);

async function setup(inputs: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const edit = jest.fn();
  const remove = jest.fn();
  const view = await render(TransferDetailComponent, {
    inputs: { transfer: TRANSFER, costCentres: CC, fyLabel: '2025', canManage: true, split: true, ...inputs },
    on: { edit, remove },
  });
  return { view, edit, remove, user: userEvent.setup() };
}

describe('TransferDetailComponent', () => {
  it('shows the pair, both bookings, the data and who booked it', async () => {
    await setup();
    expect(screen.getByText('Übertrag · HHJ 2025')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Zuschuss Hallensanierung' })).toBeInTheDocument();
    expect(screen.getByText('Ausgabe auf')).toBeInTheDocument();
    expect(screen.getByText('Einnahme auf')).toBeInTheDocument();
    expect(screen.getByText(/−2\.500,00/)).toBeInTheDocument();
    expect(screen.getByText(/\+2\.500,00/)).toBeInTheDocument();
    expect(screen.getByText('Mara Keller')).toBeInTheDocument();
    expect(screen.getByText('Beschluss des Finanzausschusses')).toBeInTheDocument();
    expect(screen.getByText(/Die beiden Kostenstellen eines Übertrags sind fest/)).toBeInTheDocument();
  });

  it('falls back to the paths and dashes for what it does not know', async () => {
    await setup({ costCentres: new Map(), fyLabel: null, transfer: { ...TRANSFER, note: null, actorName: null, paymentDate: null } });
    expect(screen.getByText('Übertrag')).toBeInTheDocument();
    expect(screen.getAllByText('VS-900').length).toBeGreaterThan(0);
    expect(screen.getAllByText('—').length).toBeGreaterThan(2);
  });

  it('runs edit and delete for a booker, and shows neither to a reader', async () => {
    const { view, edit, remove, user } = await setup();
    await user.click(screen.getByRole('button', { name: 'Übertrag bearbeiten' }));
    expect(edit).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
    await user.click(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(remove).toHaveBeenCalled();
    view.fixture.componentInstance.onMenu({ id: 'other', label: '' });
    view.fixture.componentRef.setInput('canManage', false);
    view.fixture.detectChanges();
    expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).toBeNull();
  });

  it('shows a labelled edit on a phone', async () => {
    const { edit, user } = await setup({ phone: true });
    await user.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    expect(edit).toHaveBeenCalled();
  });
});
