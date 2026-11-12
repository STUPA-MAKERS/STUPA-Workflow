import { of, throwError } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import { BudgetTreeApi } from '../budget-tree.api';
import { BudgetPlanApi } from '../plan/budget-plan.api';
import { plan, QSM, TOP } from '../plan/budget-plan.fixtures';
import { CostCentreCreateComponent } from './cost-centre-create.component';

const submitEvent = () => ({ preventDefault: jest.fn() }) as unknown as Event;

async function setup(inputs: Record<string, unknown> = {}, fail = '') {
  const refuse = () => throwError(() => ({ status: 409, error: { code: fail } }));
  const api = { createNode: jest.fn(() => (fail ? refuse() : of({ id: 'new' }))) };
  const planApi = { createNode: jest.fn(() => (fail ? refuse() : of(plan()))) };
  const created = jest.fn();
  const closed = jest.fn();
  const view = await render(CostCentreCreateComponent, {
    inputs: { open: true, top: TOP, parents: [{ value: 'vsm', label: 'VS-Mittel' }], ...inputs },
    on: { created, closed },
    providers: [
      { provide: BudgetTreeApi, useValue: api },
      { provide: BudgetPlanApi, useValue: planApi },
    ],
  });
  return { ...view, api, planApi, created, closed, c: view.fixture.componentInstance, toast: TestBed.inject(ToastService) };
}

describe('CostCentreCreateComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('starts each opening with an empty form under the budget', async () => {
    const view = await setup();
    expect(screen.getByRole('dialog', { name: 'Kostenstelle anlegen' })).toBeInTheDocument();
    expect(view.c.parentId()).toBe('vsm');
    expect(view.c.valid()).toBe(false);
    expect(view.c.parentOptions()).toEqual([{ value: 'vsm', label: 'VS-Mittel' }]);
    view.c.key.set('X');
    view.fixture.componentRef.setInput('open', false);
    view.fixture.detectChanges();
    expect(view.c.key()).toBe('X');
    view.fixture.componentRef.setInput('parent', 'staff');
    view.fixture.componentRef.setInput('open', true);
    view.fixture.detectChanges();
    expect([view.c.key(), view.c.parentId()]).toEqual(['', 'staff']);
  });

  it('has no parent without a budget', async () => {
    const { c, api } = await setup({ top: null });
    expect(c.parentId()).toBe('');
    c.submit(submitEvent());
    expect(api.createNode).not.toHaveBeenCalled();
  });

  it('asks for the side of a direct child of a budget with a Haushaltsplan', async () => {
    const view = await setup();
    view.c.key.set('810');
    view.c.name.set('Werkstatt');
    view.fixture.detectChanges();
    expect(view.c.sided()).toBe(true);
    expect(view.c.valid()).toBe(false);
    expect(view.container.ownerDocument.querySelector('.ccc__side')).not.toBeNull();
    view.c.side.set('expense');
    expect(view.c.valid()).toBe(true);
    view.c.parentId.set('staff');
    view.c.side.set(null);
    expect(view.c.valid()).toBe(true);
  });

  it('creates the Kostenstelle and tells its id', async () => {
    const { c, api, created, toast } = await setup({ top: QSM, parents: [] });
    const success = jest.spyOn(toast, 'success');
    c.submit(submitEvent());
    expect(api.createNode).not.toHaveBeenCalled();
    c.key.set(' 810 ');
    c.name.set(' Werkstatt ');
    c.side.set('income');
    c.submit(submitEvent());
    expect(api.createNode).toHaveBeenCalledWith({ parentId: 'qsm', key: '810', name: 'Werkstatt', side: null, currency: 'EUR' });
    expect(created).toHaveBeenCalledWith({ id: 'new', plan: null });
    expect(success).toHaveBeenCalledWith('Kostenstelle angelegt.');
    expect(c.busy()).toBe(false);
  });

  it('creates the Kostenstelle in a draft version together with its Ansatz', async () => {
    const view = await setup({ versionId: 'v1', amountLabel: 'Ansatz' });
    const { c, planApi, created } = view;
    expect(view.container.ownerDocument.querySelector('[name="ccAmount"]')).not.toBeNull();
    c.key.set('810');
    c.name.set('Werkstatt');
    c.side.set('expense');
    c.amount.set('');
    c.submit(submitEvent());
    expect(planApi.createNode).toHaveBeenLastCalledWith('v1', { parentId: 'vsm', key: '810', name: 'Werkstatt', side: 'expense', amount: '0' });
    c.amount.set('250');
    c.submit(submitEvent());
    expect(planApi.createNode).toHaveBeenLastCalledWith('v1', expect.objectContaining({ amount: '250' }));
    expect(created).toHaveBeenCalledWith({ id: null, plan: plan() });
  });

  it('sends nothing while a request runs', async () => {
    const { c, api } = await setup({ top: QSM });
    c.key.set('1');
    c.name.set('A');
    c.busy.set(true);
    c.submit(submitEvent());
    expect(api.createNode).not.toHaveBeenCalled();
  });

  it('shows the reason of a refused create, with and without a version', async () => {
    const first = await setup({ top: QSM }, 'budget_key_exists');
    const error = jest.spyOn(first.toast, 'error');
    first.c.key.set('1');
    first.c.name.set('A');
    first.c.submit(submitEvent());
    expect(error).toHaveBeenCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
    expect(first.created).not.toHaveBeenCalled();
    expect(first.c.busy()).toBe(false);
    TestBed.resetTestingModule();
    const second = await setup({ top: QSM, versionId: 'v1' }, 'other');
    const error2 = jest.spyOn(second.toast, 'error');
    second.c.key.set('1');
    second.c.name.set('A');
    second.c.submit(submitEvent());
    expect(error2).toHaveBeenCalledWith('Die Kostenstelle konnte nicht gespeichert werden.');
  });

  it('closes from the cancel button', async () => {
    const { closed } = await setup();
    screen.getByRole('button', { name: 'Abbrechen' }).click();
    expect(closed).toHaveBeenCalled();
  });
});
