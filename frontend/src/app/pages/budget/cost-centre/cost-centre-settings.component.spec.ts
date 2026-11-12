import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import { ToastService } from '@stupa-makers/ui-kit';
import { TestBed } from '@angular/core/testing';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget-tree.api';
import { BudgetPlanApi } from '../plan/budget-plan.api';
import { node } from '../plan/budget-plan.fixtures';
import { CostCentreSettingsComponent } from './cost-centre-settings.component';

const KS = node({ id: 'ks', parentId: 'top', key: '800', name: 'Kultur', color: ' #112233 ', side: 'income' });

async function setup(over: Partial<BudgetTreeNode> = {}, fail = '') {
  const answer = () => (fail ? throwError(() => ({ status: 409, error: { code: fail } })) : of({}));
  const api = { updateNode: jest.fn((_id: string, _patch: object) => answer()) };
  const planApi = { setSide: jest.fn(answer) };
  const saved = jest.fn();
  const view = await render(CostCentreSettingsComponent, {
    inputs: { node: { ...KS, ...over }, sided: true, gremiumOptions: [{ value: 'g1', label: 'StuPa' }] },
    on: { saved },
    providers: [
      { provide: BudgetTreeApi, useValue: api },
      { provide: BudgetPlanApi, useValue: planApi },
    ],
  });
  return { ...view, api, planApi, saved, c: view.fixture.componentInstance, toast: TestBed.inject(ToastService) };
}

describe('CostCentreSettingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the fields of the Kostenstelle, the side only with a Haushaltsplan', async () => {
    const view = await setup();
    expect(screen.getByLabelText('Schlüssel')).toBeInTheDocument();
    expect([view.c.key(), view.c.name()]).toEqual(['800', 'Kultur']);
    expect(view.container.querySelector('.ccs__side')).not.toBeNull();
    expect(view.c.colour()).toBe('#112233');
    view.fixture.componentRef.setInput('sided', false);
    view.fixture.detectChanges();
    expect(view.container.querySelector('.ccs__side')).toBeNull();
  });

  it('saves a changed key or name when the person leaves the field', async () => {
    const { c, api, saved } = await setup();
    c.name.set(' Kultur und Sport ');
    c.saveText('name');
    expect(api.updateNode).toHaveBeenCalledWith('ks', { name: 'Kultur und Sport' });
    expect(saved).toHaveBeenCalledTimes(1);
    c.key.set('800');
    c.saveText('key');
    expect(api.updateNode).toHaveBeenCalledTimes(1);
  });

  it('takes the saved text again for an empty field and saves nothing', async () => {
    const { c, api } = await setup();
    c.key.set('  ');
    c.saveText('key');
    expect(c.key()).toBe('800');
    expect(api.updateNode).not.toHaveBeenCalled();
  });

  it('saves the colour, the Gremien and the switch only when they change', async () => {
    const { c, api } = await setup();
    c.saveColour('#112233');
    c.saveGremium('viewGremiumId', '');
    expect(api.updateNode).not.toHaveBeenCalled();
    c.saveColour('');
    c.saveGremium('viewGremiumId', 'g1');
    c.saveGremium('decisionGremiumId', 'g1');
    c.save({ active: false });
    expect(api.updateNode.mock.calls.map((call) => call[1])).toEqual([
      { color: '' },
      { viewGremiumId: 'g1' },
      { decisionGremiumId: 'g1' },
      { active: false },
    ]);
  });

  it('removes a Gremium with the empty choice', async () => {
    const { c, api } = await setup({ viewGremiumId: 'g1' });
    c.saveGremium('viewGremiumId', null);
    expect(api.updateNode).toHaveBeenCalledWith('ks', { viewGremiumId: null });
  });

  it('has no colour for a Kostenstelle without one', async () => {
    const { c, api } = await setup({ color: null });
    expect(c.colour()).toBe('');
    c.saveColour('');
    expect(api.updateNode).not.toHaveBeenCalled();
  });

  it('saves another side through the plan API', async () => {
    const { c, planApi, saved } = await setup();
    c.saveSide('income');
    c.saveSide(null);
    expect(planApi.setSide).not.toHaveBeenCalled();
    c.saveSide('expense');
    expect(planApi.setSide).toHaveBeenCalledWith('ks', 'expense');
    expect(saved).toHaveBeenCalledTimes(1);
  });

  it('shows the reason of a refused save and takes the saved values again', async () => {
    const { c, toast, saved } = await setup({}, 'budget_key_exists');
    const error = jest.spyOn(toast, 'error');
    c.key.set('900');
    c.name.set('Neu');
    c.colour.set('#000000');
    c.saveText('key');
    expect(error).toHaveBeenCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
    expect([c.key(), c.name(), c.colour()]).toEqual(['800', 'Kultur', '#112233']);
    expect(saved).toHaveBeenCalledTimes(1);
  });

  it('takes the empty colour again after a refused save of a Kostenstelle without one', async () => {
    const { c } = await setup({ color: null }, 'x');
    c.colour.set('#000000');
    c.saveColour('#000000');
    expect(c.colour()).toBe('');
  });
});
