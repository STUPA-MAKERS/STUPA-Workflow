import { signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Expense } from '../../budget/budget-tree.api';
import type { ColumnSet, CostCentreLabel } from '../../budget/expense-display.util';
import type { ExpenseSubBookingsState } from '../expense-sub-bookings.state';
import { ExpensesTableComponent } from './expenses-table.component';

const EXPENSE: Expense = {
  id: 'e-1',
  budgetId: 'b-1',
  pathKey: 'VS-800',
  fiscalYearId: 'fy-1',
  kind: 'expense',
  amount: '120.00',
  currency: 'EUR',
  description: 'Druckkosten Flyer',
  applicationId: null,
  applicationTitle: null,
  transferId: null,
  actor: null,
  actorName: null,
  invoiceDate: '2026-05-20',
  paymentDate: '2026-05-28',
  correspondent: 'Copyshop Müller',
  note: null,
  referenceNumber: null,
  paymentMethod: null,
  category: null,
  invoiceId: null,
  invoiceNumber: null,
  parentExpenseId: null,
  childCount: 0,
  createdAt: '2026-05-30T09:00:00Z',
};

const COST_CENTRES = new Map<string, CostCentreLabel>([
  ['b-1', { name: 'Öffentlichkeit', path: 'VS-800', color: '#2f7fc1' }],
]);

interface Opts {
  rows?: Expense[];
  canManage?: boolean;
  columnSet?: ColumnSet;
  loading?: boolean;
}

/** The part of the sub-booking state the table reads: open parents and their children. */
function fakeSub(children: Expense[] = []) {
  const open = signal<ReadonlySet<string>>(new Set());
  return {
    isSubExpanded: (id: string) => open().has(id),
    subOf: (id: string) => children.filter((c) => c.parentExpenseId === id),
    toggleSub: jest.fn((e: Expense) =>
      open.update((s) => {
        const next = new Set(s);
        if (next.has(e.id)) next.delete(e.id);
        else next.add(e.id);
        return next;
      }),
    ),
  };
}

async function setup(opts: Opts & { children?: Expense[] } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const sub = fakeSub(opts.children);
  const edit = jest.fn();
  const remove = jest.fn();
  const addSub = jest.fn();
  const viewInvoice = jest.fn();
  const selectedChange = jest.fn();
  const sortChange = jest.fn();
  const view = await render(ExpensesTableComponent, {
    providers: [provideRouter([])],
    inputs: {
      rows: opts.rows ?? [EXPENSE],
      loading: opts.loading ?? false,
      canManage: opts.canManage ?? true,
      columnSet: opts.columnSet ?? 'full',
      sort: { key: 'paymentDate', direction: 'desc' },
      sub: sub as unknown as ExpenseSubBookingsState,
      costCentres: COST_CENTRES,
      budgetLink: (e: Expense) => ({ budget: 'top', ks: e.budgetId, fy: e.fiscalYearId }),
    },
    on: { edit, remove, addSub, viewInvoice, selectedChange, sortChange },
  });
  return { ...view, sub, edit, remove, addSub, viewInvoice, selectedChange, sortChange };
}

describe('ExpensesTableComponent', () => {
  it('shows every column of the board on the full set', async () => {
    const { container } = await setup();
    const heads = [...container.querySelectorAll('thead th')].map((th) => th.textContent?.trim());
    expect(heads.join(' ')).toMatch(
      /Zahldatum.*Rechnungsdatum.*Art.*Beschreibung.*Empfänger\/Zahler.*Betrag.*Kostenstelle.*Aktionen/,
    );
  });

  it('drops invoice date and kind on the compact set, and the payee on the tight one', async () => {
    const compact = await setup({ columnSet: 'compact' });
    const keys = compact.fixture.componentInstance.columns().map((c) => c.key);
    expect(keys).not.toContain('invoiceDate');
    expect(keys).not.toContain('kind');
    expect(keys).toContain('correspondent');
    compact.fixture.componentRef.setInput('columnSet', 'tight');
    expect(compact.fixture.componentInstance.columns().map((c) => c.key)).not.toContain(
      'correspondent',
    );
  });

  it('shows the signed amount, the kind and the cost centre with its swatch', async () => {
    const { container } = await setup({
      rows: [EXPENSE, { ...EXPENSE, id: 'e-2', kind: 'income', amount: '50.00' }],
    });
    expect(screen.getByText(/−\s*120,00/)).toBeInTheDocument();
    const income = screen.getByText(/\+\s*50,00/);
    expect(income.classList).toContain('et__income');
    expect(screen.getAllByText('Einnahme')[0].classList).toContain('et__income');
    const cc = container.querySelector('a.et__cc') as HTMLAnchorElement;
    expect(cc.textContent).toContain('Öffentlichkeit');
    expect(cc.getAttribute('title')).toBe('VS-800 · Öffentlichkeit');
    expect(cc.getAttribute('href')).toContain('/budget?budget=top&ks=b-1&fy=fy-1');
    expect(cc.querySelector('.et__swatch')).not.toBeNull();
  });

  it('falls back to the path of a cost centre outside the tree, without a swatch', async () => {
    const { container } = await setup({ rows: [{ ...EXPENSE, budgetId: 'b-x', pathKey: 'VS-900' }] });
    const cc = container.querySelector('a.et__cc') as HTMLAnchorElement;
    expect(cc.textContent?.trim()).toBe('VS-900');
    expect(cc.querySelector('.et__swatch')).toBeNull();
  });

  it('links the application under the description (N29)', async () => {
    await setup({
      rows: [{ ...EXPENSE, applicationId: 'app-1', applicationTitle: null }],
    });
    const link = screen.getByRole('link', { name: 'Antrag' });
    expect(link.getAttribute('href')).toBe('/applications/app-1');
  });

  it('expands a parent into "↳" rows that inherit the cost centre', async () => {
    const parent = { ...EXPENSE, id: 'p-1', childCount: 2 };
    const { fixture, container, sub } = await setup({
      rows: [parent],
      children: [
        { ...EXPENSE, id: 'c-1', description: 'Rahmen', parentExpenseId: 'p-1' },
        { ...EXPENSE, id: 'c-2', description: 'Farbe', parentExpenseId: 'p-1', invoiceId: 'inv-1' },
      ],
    });
    const toggle = screen.getByRole('button', { name: '2 Unterbuchungen ein-/ausklappen' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    await userEvent.click(toggle);
    expect(sub.toggleSub).toHaveBeenCalledWith(parent);
    fixture.detectChanges();
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Rahmen')).toBeInTheDocument();
    expect(container.querySelectorAll('.et__subMark').length).toBe(2);
    expect(screen.getAllByText('erbt').length).toBe(2);
  });

  it('offers no expander to a reader', async () => {
    await setup({ rows: [{ ...EXPENSE, childCount: 2 }], canManage: false });
    expect(screen.queryByRole('button', { name: /Unterbuchungen/ })).toBeNull();
  });

  it('opens the linked invoice from the receipt button', async () => {
    const row = { ...EXPENSE, invoiceId: 'inv-1' };
    const { viewInvoice } = await setup({ rows: [row] });
    await userEvent.click(screen.getByRole('button', { name: 'Verknüpfte Rechnung anzeigen' }));
    expect(viewInvoice).toHaveBeenCalledWith(row);
  });

  it('runs the row menu: sub-booking, edit, delete', async () => {
    const { fixture, addSub, edit, remove } = await setup();
    const cmp = fixture.componentInstance;
    expect(cmp.menuFor(false)[0].items.map((i) => i.id)).toEqual(['sub', 'edit']);
    expect(cmp.menuFor(true)[0].items.map((i) => i.id)).toEqual(['edit']);
    cmp.onMenu({ id: 'sub', label: '' }, EXPENSE);
    cmp.onMenu({ id: 'edit', label: '' }, EXPENSE);
    cmp.onMenu({ id: 'delete', label: '' }, EXPENSE);
    cmp.onMenu({ id: 'other', label: '' }, EXPENSE);
    expect(addSub).toHaveBeenCalledWith(EXPENSE);
    expect(edit).toHaveBeenCalledWith(EXPENSE);
    expect(remove).toHaveBeenCalledWith(EXPENSE);
    expect(
      screen.getByRole('button', { name: 'Aktionen für „Druckkosten Flyer"' }),
    ).toBeInTheDocument();
  });

  it('passes the selection and the sort on', async () => {
    const { container, fixture, selectedChange, sortChange } = await setup();
    (container.querySelector('tbody input[type=checkbox]') as HTMLInputElement).click();
    expect(selectedChange).toHaveBeenCalledWith(new Set(['e-1']));
    await userEvent.click(screen.getByRole('button', { name: /Betrag/ }));
    expect(sortChange).toHaveBeenCalledWith({ key: 'amount', direction: 'desc' });
    expect(fixture.componentInstance.rowSelectLabel(EXPENSE)).toBe('Druckkosten Flyer');
    expect(fixture.componentInstance.rowId(EXPENSE)).toBe('e-1');
  });

  it('has no actions column and no selection for a reader', async () => {
    const { container } = await setup({ canManage: false });
    expect(container.querySelector('.dt__cell--stickyEnd')).toBeNull();
    expect(container.querySelectorAll('input[type=checkbox]').length).toBe(0);
  });

  it('shows dashes for a booking without dates and payee', async () => {
    await setup({
      rows: [{ ...EXPENSE, invoiceDate: null, paymentDate: null, correspondent: null }],
    });
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
  });

  it('counts a missing child count as none', async () => {
    const { fixture } = await setup();
    expect(
      fixture.componentInstance.toggleLabel({ ...EXPENSE, childCount: undefined as unknown as number }),
    ).toBe('0 Unterbuchungen ein-/ausklappen');
  });
});
