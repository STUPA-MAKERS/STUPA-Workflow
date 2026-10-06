import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Application } from '@core/api/models';
import type { BudgetTreeNode, Expense, Invoice } from '../../budget/budget-tree.api';
import { costCentreIndex } from '../../budget/expense-display.util';
import { BookingDetailComponent } from './booking-detail.component';

const NODE = (over: Partial<BudgetTreeNode>): BudgetTreeNode => ({
  id: 'n',
  parentId: null,
  gremiumId: null,
  key: 'VS',
  pathKey: 'VS',
  name: 'Gesamthaushalt',
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
  ...over,
});

const TREE: BudgetTreeNode[] = [
  NODE({
    id: 'top',
    children: [
      NODE({
        id: 'fs',
        key: '200',
        pathKey: 'VS-200',
        name: 'Fachschaften',
        children: [
          NODE({
            id: 'mb',
            key: '220',
            pathKey: 'VS-200-220',
            name: 'Maschinenbau',
            color: '#f28c28',
            byFiscalYear: [
              {
                fiscalYearId: 'fy',
                allocated: '11500',
                bound: '3100',
                expended: '4200',
                income: '0',
                committed: '7300',
                requested: '0',
                available: '4200',
              },
            ],
          }),
        ],
      }),
    ],
  }),
];

const EXPENSE: Expense = {
  id: 'e-1',
  budgetId: 'mb',
  pathKey: 'VS-200-220',
  fiscalYearId: 'fy',
  kind: 'expense',
  amount: '900.00',
  currency: 'EUR',
  description: 'Lastenrad Anzahlung',
  applicationId: null,
  applicationTitle: null,
  transferId: null,
  actor: 'sub',
  actorName: 'Konrad Pfeiffer',
  invoiceDate: '2026-09-24',
  paymentDate: '2026-09-25',
  correspondent: 'Radhaus Müller GmbH',
  note: 'Anzahlung',
  referenceNumber: 'RE-2026-118',
  paymentMethod: 'ueberweisung',
  category: 'Anschaffung',
  invoiceId: null,
  invoiceNumber: null,
  parentExpenseId: null,
  childCount: 0,
  createdAt: '2026-09-25T08:14:00Z',
};

const INVOICE: Invoice = {
  id: 'inv',
  number: 'RE-2026-118',
  issueDate: '2026-09-24',
  dueDate: '2026-10-08',
  supplier: 'Radhaus Müller GmbH',
  netAmount: '2428.57',
  taxAmount: '461.43',
  grossAmount: '2890.00',
  currency: 'EUR',
  note: null,
  status: 'open',
  fileName: 'RE.pdf',
  hasFile: true,
  actor: null,
  createdAt: '2026-09-24T00:00:00Z',
  linkedBookings: [
    {
      id: 'e-1',
      budgetId: 'mb',
      pathKey: 'VS-200-220',
      budgetName: 'Maschinenbau',
      fiscalYearId: 'fy',
      kind: 'expense',
      amount: '900.00',
      description: 'Lastenrad Anzahlung',
      paymentDate: '2026-09-25',
      parentExpenseId: null,
      createdAt: '2026-09-25T08:14:00Z',
    },
  ],
};

async function setup(inputs: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  const edit = jest.fn();
  const remove = jest.fn();
  const addSub = jest.fn();
  const openFile = jest.fn();
  const view = await render(BookingDetailComponent, {
    inputs: {
      expense: EXPENSE,
      tree: TREE,
      costCentres: costCentreIndex(TREE),
      fyLabel: '2026',
      canManage: true,
      split: true,
      ...inputs,
    },
    on: { edit, remove, addSub, openFile },
    providers: [provideRouter([])],
  });
  return { view, edit, remove, addSub, openFile, user: userEvent.setup() };
}

describe('BookingDetailComponent', () => {
  it('shows the head, the payment, the details and the cost centre with its figures', async () => {
    const { view } = await setup();
    expect(screen.getByText('Buchung · HHJ 2026')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Lastenrad Anzahlung' })).toBeInTheDocument();
    expect(screen.getByText('Überweisung')).toBeInTheDocument();
    expect(screen.getByText('RE-2026-118')).toBeInTheDocument();
    // The cost centre below its root, with its fiscal year.
    expect(screen.getByText('Fachschaften › Maschinenbau')).toBeInTheDocument();
    expect(screen.getByText(/Konrad Pfeiffer/)).toBeInTheDocument();
    expect(screen.getByText('Anzahlung')).toBeInTheDocument();
    // The figures of the cost centre in the year of the booking.
    expect(screen.getByRole('img', { name: /Ausgegeben 4\.200,00/ })).toBeInTheDocument();
    expect(screen.getByText('VS-200-220')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Im Budget ansehen' });
    expect(link.getAttribute('href')).toBe('/budget?budget=top&ks=mb&fy=fy');
    expect(view.container.querySelector('.fd--split')).not.toBeNull();
  });

  it('leaves out what it does not know', async () => {
    await setup({
      expense: {
        ...EXPENSE,
        budgetId: 'gone',
        pathKey: null,
        paymentMethod: null,
        note: null,
        actorName: null,
        paymentDate: null,
        invoiceDate: null,
        correspondent: null,
        referenceNumber: null,
        category: null,
      },
      fyLabel: null,
      canManage: false,
    });
    expect(screen.getByText('Buchung')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(4);
    // No figures for a cost centre outside the tree, no edit for a reader.
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Buchung bearbeiten' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Unterbuchungen' })).toBeNull();
  });

  it('shows the linked application and invoice with the booked share', async () => {
    const app = {
      id: 'app-1',
      state: { id: 's', key: 'agenda', label: 'Auf Tagesordnung', color: '#2e7d32' },
      amount: '2890.00',
    } as unknown as Application;
    await setup({
      expense: { ...EXPENSE, applicationId: 'app-1', applicationTitle: 'Lastenrad', invoiceId: 'inv' },
      application: app,
      invoice: INVOICE,
    });
    const appLink = screen.getByRole('link', { name: /Lastenrad/ });
    expect(appLink.getAttribute('href')).toBe('/applications/app-1');
    expect(screen.getByText('Auf Tagesordnung')).toBeInTheDocument();
    const invLink = screen.getByRole('link', { name: /RE-2026-118 · Radhaus/ });
    expect(invLink.getAttribute('href')).toBe('/invoices?id=inv');
    expect(screen.getByText('Offen')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /900,00\s€ von 2\.890,00\s€ verbucht/ })).toBeInTheDocument();
  });

  it('names a linked invoice by its number until it loads, and an application by its title', async () => {
    await setup({
      expense: { ...EXPENSE, applicationId: 'app-1', applicationTitle: null, invoiceId: 'inv', invoiceNumber: 'RE-9' },
      application: { id: 'other' } as unknown as Application,
      invoice: { ...INVOICE, id: 'other' },
    });
    expect(screen.getByRole('link', { name: /Antrag/ })).toBeInTheDocument();
    expect(screen.getByText('RE-9')).toBeInTheDocument();
    expect(screen.queryByText(/verbucht/)).toBeNull();
  });

  it('lists the sub-bookings with their sum and runs their menus', async () => {
    const sub: Expense = { ...EXPENSE, id: 's-1', description: 'Rahmen', amount: '720.00', parentExpenseId: 'e-1', correspondent: null };
    const { edit, remove, addSub, user } = await setup({
      expense: { ...EXPENSE, childCount: 1 },
      subRows: [sub],
    });
    expect(screen.getByText('Rahmen')).toBeInTheDocument();
    expect(screen.getByText('Betrag der Buchung = Summe der Unterbuchungen')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Unterbuchung hinzufügen' }));
    expect(addSub).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Aktionen für „Rahmen“' }));
    await user.click(screen.getByRole('menuitem', { name: 'Bearbeiten' }));
    expect(edit).toHaveBeenCalledWith(sub);
    await user.click(screen.getByRole('button', { name: 'Aktionen für „Rahmen“' }));
    await user.click(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(remove).toHaveBeenCalledWith(sub);
  });

  it('shows a skeleton while the sub-bookings load, and a line when there are none', async () => {
    const { view } = await setup({ expense: { ...EXPENSE, childCount: 2 }, subLoading: true });
    expect(view.container.querySelector('app-skeleton')).not.toBeNull();
    view.fixture.componentRef.setInput('expense', EXPENSE);
    view.fixture.componentRef.setInput('subLoading', false);
    view.fixture.detectChanges();
    expect(screen.getByText('Keine Unterbuchungen.')).toBeInTheDocument();
  });

  it('runs the actions of the head and its menu', async () => {
    const { edit, remove, addSub, openFile, user } = await setup({
      expense: { ...EXPENSE, invoiceId: 'inv' },
      invoice: INVOICE,
    });
    await user.click(screen.getByRole('button', { name: 'Buchung bearbeiten' }));
    expect(edit).toHaveBeenCalledWith(expect.objectContaining({ id: 'e-1' }));
    const menu = () => screen.getByRole('button', { name: 'Weitere Aktionen' });
    await user.click(menu());
    await user.click(screen.getByRole('menuitem', { name: 'Unterbuchung hinzufügen' }));
    expect(addSub).toHaveBeenCalled();
    await user.click(menu());
    await user.click(screen.getByRole('menuitem', { name: 'Beleg öffnen' }));
    expect(openFile).toHaveBeenCalledWith(INVOICE);
    await user.click(menu());
    await user.click(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(remove).toHaveBeenCalled();
  });

  it('shows a labelled edit on a phone and names a sub-booking', async () => {
    const { view, edit, user } = await setup({
      phone: true,
      expense: { ...EXPENSE, parentExpenseId: 'p', kind: 'income' },
    });
    expect(screen.getByText('Unterbuchung · HHJ 2026')).toBeInTheDocument();
    expect(screen.getByText('Einnahme')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    expect(edit).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
    expect(screen.queryByRole('menuitem', { name: 'Unterbuchung hinzufügen' })).toBeNull();
    // An unknown menu item does nothing; the file item needs a loaded invoice.
    const cmp = view.fixture.componentInstance;
    cmp.onMenu({ id: 'file', label: '' });
    cmp.onMenu({ id: 'other', label: '' });
  });

  it('shows an overdrawn cost centre in the error tone', async () => {
    const over = JSON.parse(JSON.stringify(TREE)) as BudgetTreeNode[];
    over[0].children[0].children[0].byFiscalYear[0].available = '-50';
    await setup({ tree: over });
    expect(screen.getByText(/-50,00/).classList.contains('fd__neg')).toBe(true);
  });
});
