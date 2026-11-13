import { Subject, of, throwError } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { BudgetTreeApi } from '../budget-tree.api';
import { BudgetPlanApi } from '../plan/budget-plan.api';
import { plan, planTreeOf, QSM, TOP } from '../plan/budget-plan.fixtures';
import { CostCentreCreateComponent } from './cost-centre-create.component';

async function setup(inputs: Record<string, unknown> = {}, fail = '') {
  TestBed.resetTestingModule();
  const refuse = () => throwError(() => ({ status: 409, error: { code: fail } }));
  const api = { createNode: jest.fn((..._args: unknown[]) => (fail ? refuse() : of({ id: 'new' }))) };
  const planApi = { createNode: jest.fn((..._args: unknown[]) => (fail ? refuse() : of(plan()))) };
  const created = jest.fn();
  const closed = jest.fn();
  const view = await render(CostCentreCreateComponent, {
    inputs: { open: true, top: TOP, parentNodes: [planTreeOf(TOP)], ...inputs },
    on: { created, closed },
    providers: [
      { provide: BudgetTreeApi, useValue: api },
      { provide: BudgetPlanApi, useValue: planApi },
    ],
  });
  const toast = TestBed.inject(ToastService);
  const dialog = screen.getByRole('dialog', { name: 'Kostenstelle anlegen' });
  return {
    ...view,
    api,
    planApi,
    created,
    closed,
    dialog,
    success: jest.spyOn(toast, 'success'),
    error: jest.spyOn(toast, 'error'),
    submit: within(dialog).getByRole('button', { name: 'Anlegen' }),
    field: (name: string) => dialog.querySelector<HTMLInputElement>(`[name="${name}"] input, input[name="${name}"]`) as HTMLInputElement,
    parent: () => dialog.querySelector('[data-cc-trigger]') as HTMLElement,
  };
}

type View = Awaited<ReturnType<typeof setup>>;

async function fill(view: View, key: string, name: string): Promise<void> {
  await userEvent.type(view.field('ccKey'), key);
  await userEvent.type(view.field('ccName'), name);
}
async function pickSide(view: View, side: string): Promise<void> {
  await userEvent.click(within(view.dialog).getByRole('combobox', { name: /Seite/ }));
  await userEvent.click(await screen.findByRole('option', { name: side }));
}
async function pickParent(view: View, name: RegExp): Promise<void> {
  await userEvent.click(view.parent());
  await userEvent.click(await screen.findByRole('option', { name }));
}

describe('CostCentreCreateComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('starts each opening with an empty form under the given parent', async () => {
    const view = await setup();
    expect(view.parent()).toHaveTextContent('VS-Mittel');
    expect(view.submit).toBeDisabled();
    await fill(view, 'X', 'Y');
    view.fixture.componentRef.setInput('open', false);
    view.fixture.componentRef.setInput('parent', 'staff');
    view.fixture.detectChanges();
    view.fixture.componentRef.setInput('open', true);
    view.fixture.detectChanges();
    const dialog = screen.getByRole('dialog', { name: 'Kostenstelle anlegen' });
    await waitFor(() => expect(dialog.querySelector<HTMLInputElement>('[name="ccKey"] input')?.value).toBe(''));
    expect(dialog.querySelector('[data-cc-trigger]')).toHaveTextContent('Personal');
  });

  it('has no parent without a budget and creates nothing', async () => {
    const view = await setup({ top: null, parentNodes: [] });
    await fill(view, '1', 'A');
    expect(view.submit).toBeDisabled();
    expect(view.api.createNode).not.toHaveBeenCalled();
  });

  it('§F/finance/budget/000795: asks for the side of a direct child of a budget with a Haushaltsplan', async () => {
    const view = await setup();
    await fill(view, '810', 'Werkstatt');
    expect(within(view.dialog).getByRole('combobox', { name: /Seite/ })).toHaveAttribute('aria-required', 'true');
    expect(view.submit).toBeDisabled();
    await pickSide(view, 'Ausgabe');
    expect(view.submit).toBeEnabled();
    await userEvent.click(view.submit);
    expect(view.api.createNode).toHaveBeenCalledWith({ parentId: 'vsm', key: '810', name: 'Werkstatt', side: 'expense', currency: 'EUR' });
  });

  it('§F/finance/budget/000795: a Kostenstelle below another one has no side', async () => {
    const view = await setup();
    await fill(view, '810', 'Werkstatt');
    await pickParent(view, /Personal/);
    expect(within(view.dialog).queryByRole('combobox', { name: /Seite/ })).toBeNull();
    await userEvent.click(view.submit);
    expect(view.api.createNode).toHaveBeenCalledWith(expect.objectContaining({ parentId: 'staff', side: null }));
  });

  it('§F/finance/budget/000246: refuses a key with other characters and a name that is too long', async () => {
    const view = await setup({ top: QSM, parentNodes: [QSM] });
    await fill(view, 'A-1', 'Werkstatt');
    expect(within(view.dialog).getByText('Nur Buchstaben und Ziffern, höchstens 64 Zeichen.')).toBeInTheDocument();
    expect(view.submit).toBeDisabled();
    await userEvent.clear(view.field('ccKey'));
    await userEvent.type(view.field('ccKey'), 'A1');
    expect(view.submit).toBeEnabled();
    await userEvent.click(view.field('ccName'));
    await userEvent.paste('x'.repeat(200));
    expect(within(view.dialog).getByText('Höchstens 200 Zeichen.')).toBeInTheDocument();
    expect(view.submit).toBeDisabled();
  });

  it('creates the Kostenstelle with trimmed texts and tells its id', async () => {
    const view = await setup({ top: QSM, parentNodes: [QSM] });
    await fill(view, ' 810 ', ' Werkstatt ');
    await userEvent.keyboard('{Enter}');
    expect(view.api.createNode).toHaveBeenCalledWith({ parentId: 'qsm', key: '810', name: 'Werkstatt', side: null, currency: 'EUR' });
    expect(view.created).toHaveBeenCalledWith({ id: 'new', plan: null });
    expect(view.success).toHaveBeenCalledWith('Kostenstelle angelegt.');
    expect(view.dialog.querySelector('[name="ccAmount"]')).toBeNull();
  });

  it('§F/finance/budget/000829: creates the Kostenstelle in a draft version together with its Ansatz', async () => {
    const view = await setup({ versionId: 'v1', amountLabel: 'Ansatz' });
    await fill(view, '810', 'Werkstatt');
    await pickSide(view, 'Einnahme');
    await userEvent.click(view.submit);
    expect(view.planApi.createNode).toHaveBeenLastCalledWith('v1', { parentId: 'vsm', key: '810', name: 'Werkstatt', side: 'income', amount: '0' });
    const amount = view.field('ccAmount');
    await userEvent.clear(amount);
    await userEvent.click(view.submit);
    expect(view.planApi.createNode).toHaveBeenLastCalledWith('v1', expect.objectContaining({ amount: '0' }));
    await userEvent.type(amount, '250');
    await userEvent.click(view.submit);
    expect(view.planApi.createNode).toHaveBeenLastCalledWith('v1', expect.objectContaining({ amount: '250' }));
    expect(view.created).toHaveBeenLastCalledWith({ id: null, plan: plan() });
  });

  it('§F/finance/budget/000829: text that is no amount blocks the button', async () => {
    const view = await setup({ versionId: 'v1', top: QSM, parentNodes: [QSM] });
    await fill(view, '810', 'Werkstatt');
    expect(view.submit).toBeEnabled();
    await userEvent.type(view.field('ccAmount'), 'abc');
    expect(view.submit).toBeDisabled();
    await userEvent.clear(view.field('ccAmount'));
    await userEvent.type(view.field('ccAmount'), '5');
    expect(view.submit).toBeEnabled();
  });

  it('§F/finance/budget/000794: an Ansatz below 0 or above the largest amount blocks the button', async () => {
    const view = await setup({ versionId: 'v1', top: QSM, parentNodes: [QSM] });
    await fill(view, '810', 'Werkstatt');
    view.fixture.componentInstance.setAmount('-5');
    view.fixture.detectChanges();
    expect(view.submit).toBeDisabled();
    view.fixture.componentInstance.setAmount('99999999999');
    view.fixture.detectChanges();
    expect(view.submit).toBeDisabled();
    view.fixture.componentInstance.setAmount(null);
    view.fixture.detectChanges();
    expect(view.submit).toBeEnabled();
  });

  it('§F/finance/budget/000794: the first child starts with the Ansatz of its parent', async () => {
    const view = await setup({ versionId: 'v1', parent: 'grants', firstChildAmounts: new Map([['grants', '30.00']]) });
    await waitFor(() => expect(view.field('ccAmount').value).toBe('30,00'));
    await pickParent(view, /Personal/);
    await waitFor(() => expect(view.field('ccAmount').value).toBe('0,00'));
    await pickParent(view, /Zuschüsse/);
    await waitFor(() => expect(view.field('ccAmount').value).toBe('30,00'));
  });

  it('sends nothing a second time while a request runs', async () => {
    const view = await setup({ top: QSM, parentNodes: [QSM] });
    const pending = new Subject<{ id: string }>();
    view.api.createNode.mockReturnValueOnce(pending);
    await fill(view, '1', 'A');
    await userEvent.click(view.submit);
    expect(view.submit).toBeDisabled();
    await userEvent.type(view.field('ccName'), '{Enter}');
    expect(view.api.createNode).toHaveBeenCalledTimes(1);
  });

  it('shows the reason of a refused create, with and without a version', async () => {
    const first = await setup({ top: QSM, parentNodes: [QSM] }, 'budget_key_exists');
    await fill(first, '1', 'A');
    await userEvent.click(first.submit);
    expect(first.error).toHaveBeenCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
    expect(first.created).not.toHaveBeenCalled();
    expect(first.submit).toBeEnabled();
    first.fixture.destroy();
    const second = await setup({ top: QSM, parentNodes: [QSM], versionId: 'v1' }, 'other');
    await fill(second, '1', 'A');
    await userEvent.click(second.submit);
    expect(second.error).toHaveBeenCalledWith('Die Kostenstelle konnte nicht gespeichert werden.');
  });

  it('closes from the cancel button', async () => {
    const view = await setup();
    await userEvent.click(within(view.dialog).getByRole('button', { name: 'Abbrechen' }));
    expect(view.closed).toHaveBeenCalled();
  });
});
