import { render, screen } from '@testing-library/angular';
import type { BudgetTransfer } from '../../budget/budget-tree.api';
import type { ColumnSet, CostCentreLabel } from '../../budget/expense-display.util';
import { TransfersTableComponent } from './transfers-table.component';

const TRANSFER: BudgetTransfer = {
  transferId: 'tr-1',
  expenseId: 'e-1',
  incomeId: 'e-2',
  fromBudgetId: 'b-1',
  fromPathKey: 'VS-800',
  toBudgetId: 'b-2',
  toPathKey: 'VS-900',
  fiscalYearId: 'fy-1',
  amount: '50.00',
  currency: 'EUR',
  description: 'Umbuchung Fest',
  note: 'Beschluss',
  invoiceDate: null,
  paymentDate: '2026-05-01',
  actor: null,
  actorName: null,
  createdAt: '2026-05-01T10:00:00Z',
};

async function setup(opts: { canManage?: boolean; columnSet?: ColumnSet } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const edit = jest.fn();
  const remove = jest.fn();
  const costCentres = new Map<string, CostCentreLabel>([
    ['b-1', { name: 'Rücklage', path: 'VS-800', color: '#b8323a' }],
  ]);
  const view = await render(TransfersTableComponent, {
    inputs: {
      rows: [TRANSFER],
      canManage: opts.canManage ?? true,
      columnSet: opts.columnSet ?? 'full',
      costCentres,
    },
    on: { edit, remove },
  });
  return { ...view, edit, remove };
}

describe('TransfersTableComponent', () => {
  it('shows one row per transfer: both cost centres, the note and the amount', async () => {
    const { container } = await setup();
    expect(screen.getByText('Umbuchung Fest')).toBeInTheDocument();
    expect(screen.getByText('Beschluss')).toBeInTheDocument();
    expect(screen.getByText('Rücklage')).toBeInTheDocument();
    // The second cost centre is outside the loaded tree: its path names it.
    expect(screen.getByText('VS-900')).toBeInTheDocument();
    expect(container.querySelectorAll('.tt__swatch').length).toBe(1);
    expect(screen.getByText(/50,00/)).toBeInTheDocument();
  });

  it('drops the invoice date below the full set', async () => {
    const { fixture } = await setup({ columnSet: 'compact' });
    expect(fixture.componentInstance.columns().map((c) => c.key)).not.toContain('invoiceDate');
  });

  it('runs edit and delete from the row menu', async () => {
    const { fixture, edit, remove } = await setup();
    const cmp = fixture.componentInstance;
    cmp.onMenu({ id: 'edit', label: '' }, TRANSFER);
    cmp.onMenu({ id: 'delete', label: '' }, TRANSFER);
    cmp.onMenu({ id: 'other', label: '' }, TRANSFER);
    expect(edit).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(cmp.rowId(TRANSFER)).toBe('tr-1');
    expect(screen.getByRole('button', { name: 'Aktionen für „Umbuchung Fest"' })).toBeInTheDocument();
  });

  it('has no actions column for a reader', async () => {
    const { container } = await setup({ canManage: false });
    expect(container.querySelector('.dt__cell--stickyEnd')).toBeNull();
  });
});
