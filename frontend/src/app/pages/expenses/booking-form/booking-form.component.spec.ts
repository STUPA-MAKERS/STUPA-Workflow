import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { BudgetTreeNode, Expense, Invoice } from '../../budget/budget-tree.api';
import { costCentreIndex } from '../../budget/expense-display.util';
import { ExpenseDialogsState } from '../expense-dialogs.state';
import { ExpenseSubBookingsState } from '../expense-sub-bookings.state';
import { ExpenseTransfersState } from '../expense-transfers.state';
import { ExpensesListState } from '../expenses-list.state';
import { BookingFormComponent } from './booking-form.component';

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
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [
      {
        id: 'mb',
        parentId: 'top',
        gremiumId: null,
        key: '220',
        pathKey: 'VS-220',
        name: 'Maschinenbau',
        currency: 'EUR',
        active: true,
        color: '#f28c28',
        acceptedStateKeys: [],
        deniedStateKeys: [],
        hiddenInBudget: false,
        viewGremiumId: null,
        fiscalStartMonth: 1,
        fiscalStartDay: 1,
        byFiscalYear: [],
        children: [],
      },
    ],
  },
];

const EXPENSE: Expense = {
  id: 'e-1',
  budgetId: 'mb',
  pathKey: 'VS-220',
  fiscalYearId: 'fy',
  kind: 'expense',
  amount: '900.00',
  currency: 'EUR',
  description: 'Lastenrad Anzahlung',
  applicationId: null,
  applicationTitle: null,
  transferId: null,
  actor: null,
  actorName: 'Konrad Pfeiffer',
  invoiceDate: null,
  paymentDate: null,
  correspondent: null,
  note: null,
  referenceNumber: null,
  paymentMethod: 'bar',
  category: null,
  invoiceId: null,
  invoiceNumber: null,
  parentExpenseId: null,
  childCount: 0,
  createdAt: '2026-09-25T08:14:00Z',
};

/** What the host hands to the form. A test sets it before the render. */
let CONFIG: { mode: 'create' | 'edit'; expense: Expense; inputs: Record<string, unknown> } = {
  mode: 'create',
  expense: EXPENSE,
  inputs: {},
};

/** The form inside the page state modules, as the bookings page builds them. */
@Component({
  standalone: true,
  imports: [BookingFormComponent],
  template: `
    <app-booking-form
      [state]="dialogs"
      [mode]="mode"
      [tree]="tree"
      [costCentres]="costCentres"
      [fyLabel]="$any(inputs['fyLabel'] === undefined ? '2026' : inputs['fyLabel'])"
      [subRows]="$any(inputs['subRows'] ?? [])"
      [layout]="$any(inputs['layout'] ?? 'pane')"
      (remove)="handlers.remove()"
      (addSub)="handlers.addSub()"
      (editSub)="handlers.editSub($event)"
      (removeSub)="handlers.removeSub($event)"
    />
  `,
})
class HostComponent {
  readonly list = new ExpensesListState();
  readonly sub = new ExpenseSubBookingsState(this.list);
  readonly transfers = new ExpenseTransfersState(this.list);
  readonly dialogs = new ExpenseDialogsState(this.list, this.sub, this.transfers);
  readonly mode = CONFIG.mode;
  readonly inputs = CONFIG.inputs;
  readonly tree = TREE;
  readonly costCentres = costCentreIndex(TREE);
  readonly handlers = {
    remove: jest.fn(),
    addSub: jest.fn(),
    editSub: jest.fn(),
    removeSub: jest.fn(),
  };
}

async function setup(mode: 'create' | 'edit', inputs: Record<string, unknown> = {}) {
  localStorage.setItem('ap.locale', 'de');
  CONFIG = { mode, expense: (inputs['expense'] as Expense | undefined) ?? EXPENSE, inputs };
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
  if (mode === 'create') host.dialogs.openCreate();
  else host.dialogs.openEdit(CONFIG.expense);
  view.fixture.detectChanges();
  const form = view.fixture.debugElement.children[0].componentInstance as BookingFormComponent;
  return { view, http, dialogs: host.dialogs, form, ...host.handlers, user: userEvent.setup() };
}

/** The first render of the form compiles the whole form with its controls. Under the
 *  load of a parallel run that takes longer than the default 5 s of jest. */
const SLOW = 15000;

const INVOICE: Invoice = {
  id: 'inv',
  number: 'RE-2026-0412',
  issueDate: '2026-09-12',
  dueDate: null,
  supplier: 'Soundwerk Reutlingen GmbH',
  netAmount: null,
  taxAmount: null,
  grossAmount: '1250.00',
  currency: 'EUR',
  note: null,
  status: 'open',
  fileName: null,
  hasFile: false,
  actor: null,
  createdAt: '2026-09-12T08:00:00Z',
};

/** "Label Value" of each locked field. */
const lockedTexts = (root: Element) =>
  [...root.querySelectorAll('app-locked-field')].map((l) =>
    [...l.querySelectorAll('.lfld__label, .lfld__value')]
      .map((c) => c.textContent?.replace(/\s+/g, ' ').trim())
      .join(' '),
  );

const tick = () => new Promise((r) => setTimeout(r));

describe('BookingFormComponent', () => {
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

  it(
    'builds a new booking: kind, cost centre from the list, fiscal year and payment method',
    async () => {
      const { dialogs, http, user, view } = await setup('create');
      expect(screen.getByRole('heading', { name: 'Buchung hinzufügen' })).toBeInTheDocument();
      // The sections of the board, no subtitle.
      for (const name of ['Zuordnung', 'Beleg', 'Zahlung'])
        expect(screen.getByRole('group', { name })).toBeInTheDocument();
      expect(view.container.querySelector('.ff__subtitle, .mf__subtitle')).toBeNull();
      await user.click(screen.getByRole('radio', { name: 'Einnahme' }));
      expect(dialogs.newKind()).toBe('income');
      // Income has no application search.
      expect(screen.queryByRole('combobox', { name: 'Antrag' })).toBeNull();
      await user.click(screen.getByRole('radio', { name: 'Ausgabe' }));
      expect(dialogs.newKind()).toBe('expense');
      expect(screen.getByRole('combobox', { name: 'Antrag' })).toBeInTheDocument();

      const pick = screen.getByRole('button', { name: /^Kostenstelle Kostenstelle wählen/ });
      await user.click(pick);
      await tick();
      view.fixture.detectChanges();
      expect(pick.getAttribute('aria-expanded')).toBe('true');
      // Opening the list asks for the years of the top budgets, for the free amounts.
      http.expectOne((r) => r.url.endsWith('/budgets/top/fiscal-years')).flush([]);
      await user.click(screen.getByRole('option', { name: /Maschinenbau/ }));
      expect(dialogs.newBudgetId()).toBe('mb');
      http
        .expectOne((r) => r.url.endsWith('/budgets/top/fiscal-years'))
        .flush([
          {
            id: 'fy',
            budgetId: 'top',
            year: 2026,
            display: '2026',
            startDate: '',
            endDate: '',
            active: true,
          },
        ]);
      expect(dialogs.newFiscalYearId()).toBe('fy');

      await user.click(screen.getByRole('radio', { name: 'Bar' }));
      expect(dialogs.newPaymentMethod()).toBe('bar');
      expect(screen.getByRole('radio', { name: 'Bar' }).getAttribute('aria-checked')).toBe('true');
      await user.click(screen.getByRole('radio', { name: 'Keine Angabe' }));
      expect(dialogs.newPaymentMethod()).toBe('');
    },
    SLOW,
  );

  it('locks the fields a picked invoice filled, and a linked application gives the cost centre', async () => {
    const { dialogs, view } = await setup('create');
    dialogs.invoices.set([INVOICE]);
    dialogs.onPickInvoice('inv');
    view.fixture.detectChanges();
    const locked = lockedTexts(view.container);
    expect(locked).toEqual([
      'Empfänger/Zahler Soundwerk Reutlingen GmbH',
      'Belegnummer RE-2026-0412',
      'Rechnungsdatum 12.09.2026',
    ]);
    // Taken from the invoice: the selection surface of the kit locked field.
    expect(view.container.querySelectorAll('.lfld--filled')).toHaveLength(3);
    expect(screen.queryByRole('textbox', { name: 'Belegnummer' })).toBeNull();
    // The payment date stays a field.
    expect(screen.getByText('Zahldatum')).toBeInTheDocument();
    // Without the invoice the fields are fields again, with the values kept.
    dialogs.onPickInvoice('');
    view.fixture.detectChanges();
    expect(view.container.querySelectorAll('app-locked-field')).toHaveLength(0);
    expect(dialogs.newReferenceNumber()).toBe('RE-2026-0412');

    dialogs.newApplicationId.set('app');
    dialogs.appQuery.set('Lastenrad');
    view.fixture.detectChanges();
    expect(screen.queryByRole('button', { name: /^Kostenstelle/ })).toBeNull();
    expect(screen.getAllByText('Aus dem Antrag')).toHaveLength(2);
    expect(screen.getByText('Lastenrad')).toBeInTheDocument();
  });

  it('lists the application hits below the search and picks one', async () => {
    const { dialogs, view, user } = await setup('create');
    dialogs.appCandidates.set([{ id: 'a1', title: 'Lastenrad' }]);
    view.fixture.detectChanges();
    expect(screen.getByRole('combobox', { name: 'Antrag' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    await user.click(screen.getByRole('option', { name: 'Lastenrad' }));
    expect(dialogs.newApplicationId()).toBe('a1');
    view.fixture.detectChanges();
    await user.click(screen.getByRole('button', { name: 'Verknüpfung lösen' }));
    expect(dialogs.newApplicationId()).toBe('');
  });

  it('cancels and submits a new booking with the buttons of the foot', async () => {
    const { dialogs, user, view } = await setup('create');
    const save = screen.getByRole('button', { name: 'Buchung speichern' });
    expect(save).toBeDisabled();
    const submit = jest.spyOn(dialogs, 'create').mockImplementation(() => undefined);
    dialogs.newDescription.set('DJ');
    dialogs.newAmount.set('10');
    dialogs.newBudgetId.set('mb');
    dialogs.newFiscalYearId.set('fy');
    view.fixture.detectChanges();
    expect(save).toBeEnabled();
    await user.click(save);
    expect(submit).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(dialogs.createOpen()).toBe(false);
  });

  it('closes with the round button of the head', async () => {
    const { dialogs, user } = await setup('create');
    await user.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(dialogs.createOpen()).toBe(false);
  });

  it('locks the fixed values of a bound booking and shows its sub-bookings in the edit', async () => {
    const sub: Expense = {
      ...EXPENSE,
      id: 's',
      description: 'Rahmen',
      parentExpenseId: 'e-1',
      paymentDate: '2026-09-25',
      correspondent: 'Radhaus',
    };
    const { addSub, editSub, removeSub, remove, user, view } = await setup('edit', {
      expense: { ...EXPENSE, applicationId: 'a', applicationTitle: 'Lastenrad', childCount: 1 },
      subRows: [sub],
    });
    expect(screen.getByRole('heading', { name: 'Buchung bearbeiten' })).toBeInTheDocument();
    // No subtitle.
    expect(screen.queryByText(/erfasst von Konrad Pfeiffer/)).toBeNull();
    // The kind is fixed.
    expect(screen.getByRole('radio', { name: 'Ausgabe' })).toBeDisabled();
    const locked = lockedTexts(view.container);
    expect(locked).toEqual([
      'Betrag = Summe der Unterbuchungen 900,00 €',
      'Kostenstelle Maschinenbau',
      'Haushaltsjahr 2026',
      'Antrag Lastenrad',
    ]);
    expect(screen.getByText(/Rahmen/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Unterbuchung hinzufügen' }));
    expect(addSub).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Aktionen für „Rahmen“' }));
    await user.click(screen.getByRole('menuitem', { name: 'Bearbeiten' }));
    expect(editSub).toHaveBeenCalledWith(sub);
    await user.click(screen.getByRole('button', { name: 'Aktionen für „Rahmen“' }));
    await user.click(screen.getByRole('menuitem', { name: 'Löschen' }));
    expect(removeSub).toHaveBeenCalledWith(sub);
    await user.click(screen.getByRole('button', { name: 'Löschen' }));
    expect(remove).toHaveBeenCalled();
  });

  it('moves a standalone booking to another cost centre in the edit', async () => {
    const { dialogs, user, form, view, http } = await setup('edit', {
      expense: { ...EXPENSE, actorName: null },
    });
    await user.click(screen.getByRole('button', { name: /^Kostenstelle .*Maschinenbau/ }));
    await tick();
    view.fixture.detectChanges();
    http.expectOne((r) => r.url.endsWith('/budgets/top/fiscal-years')).flush([]);
    await user.click(screen.getByRole('option', { name: /Gesamthaushalt/ }));
    expect(dialogs.editBudgetId()).toBe('top');
    await user.click(screen.getByRole('radio', { name: 'Karte' }));
    expect(dialogs.editPaymentMethod()).toBe('karte');
    // A pick without an id changes nothing.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (form as any).pickCostCentre('');
    expect(dialogs.editBudgetId()).toBe('top');
    const save = jest.spyOn(dialogs, 'saveEdit').mockImplementation(() => undefined);
    await user.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(save).toHaveBeenCalledTimes(1);
    form.close();
    expect(dialogs.editing()).toBeNull();
  });

  it('locks the cost centre of a sub-booking and leaves out its sub-bookings', async () => {
    const { view } = await setup('edit', {
      expense: { ...EXPENSE, parentExpenseId: 'p' },
      fyLabel: null,
    });
    const locked = lockedTexts(view.container);
    expect(locked).toEqual(['Kostenstelle Maschinenbau', 'Haushaltsjahr —']);
    expect(screen.queryByRole('group', { name: 'Unterbuchungen' })).toBeNull();
  });

  it('leaves out its head in the bottom sheet and makes the delete an icon', async () => {
    const { view } = await setup('edit', { layout: 'sheet' });
    expect(screen.queryByRole('heading', { name: 'Buchung bearbeiten' })).toBeNull();
    expect(view.container.querySelector('.mf--sheet')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'Löschen' }).textContent?.trim()).toBe('');
  });

  it('names the save button short in the bottom sheet', async () => {
    await setup('create', { layout: 'sheet' });
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeInTheDocument();
  });
});
