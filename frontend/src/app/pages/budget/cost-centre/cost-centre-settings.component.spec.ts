import { Subject, of, throwError } from 'rxjs';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { TestBed } from '@angular/core/testing';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget-tree.api';
import { BudgetPlanApi } from '../plan/budget-plan.api';
import { node } from '../plan/budget-plan.fixtures';
import { PALETTE } from '../budget-color.util';
import { CostCentreSettingsComponent } from './cost-centre-settings.component';

const KS = node({ id: 'ks', parentId: 'top', key: '800', name: 'Kultur', color: ' #112233 ', side: 'income' });

async function setup(over: Partial<BudgetTreeNode> = {}, fail = '', sided = true) {
  TestBed.resetTestingModule();
  const answer = () => (fail ? throwError(() => ({ status: 409, error: { code: fail } })) : of({}));
  const api = { updateNode: jest.fn((_id: string, _patch: object) => answer()) };
  const planApi = { setSide: jest.fn((_id: string, _side: string) => answer()) };
  const saved = jest.fn();
  const view = await render(CostCentreSettingsComponent, {
    inputs: { node: { ...KS, ...over }, sided, gremiumOptions: [{ value: 'g1', label: 'StuPa' }] },
    on: { saved },
    providers: [
      { provide: BudgetTreeApi, useValue: api },
      { provide: BudgetPlanApi, useValue: planApi },
    ],
  });
  const toast = TestBed.inject(ToastService);
  const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
  return { ...view, api, planApi, saved, field, success: jest.spyOn(toast, 'success'), error: jest.spyOn(toast, 'error') };
}

/** Replace the text of a field and leave the field. */
async function retype(field: HTMLInputElement, value: string): Promise<void> {
  await userEvent.clear(field);
  if (value) await userEvent.type(field, value);
  await userEvent.tab();
}
/** Choose an option of a select field. */
async function pick(label: RegExp, option: string): Promise<void> {
  await userEvent.click(screen.getByRole('combobox', { name: label }));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

describe('CostCentreSettingsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the fields of the Kostenstelle, the side only with a Haushaltsplan', async () => {
    const view = await setup();
    await waitFor(() => expect(view.field('Schlüssel').value).toBe('800'));
    expect(view.field('Name').value).toBe('Kultur');
    expect(screen.getByRole('combobox', { name: /Seite/ })).toHaveTextContent('Einnahme');
    expect(view.field('Farbe als Hex-Wert').value).toBe('#112233');
    expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('Ohne Gremium');
    expect(screen.getByRole('combobox', { name: /Entscheidendes Gremium/ })).toHaveTextContent('Wie übergeordnet');
    await setup({}, '', false);
    expect(screen.queryByRole('combobox', { name: /Seite/ })).toBeNull();
  });

  it('§F/finance/budget/000831: saves a changed key or name when the person leaves the field', async () => {
    const view = await setup();
    await retype(view.field('Name'), ' Kultur und Sport ');
    expect(view.api.updateNode).toHaveBeenCalledWith('ks', { name: 'Kultur und Sport' });
    expect(view.saved).toHaveBeenCalledTimes(1);
    expect(view.success).toHaveBeenCalledWith('Gespeichert.');
    await retype(view.field('Schlüssel'), '800');
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
    await retype(view.field('Schlüssel'), '810');
    expect(view.api.updateNode).toHaveBeenLastCalledWith('ks', { key: '810' });
  });

  it('§F/finance/budget/000831: takes the saved text again for an empty field and saves nothing', async () => {
    const view = await setup();
    await retype(view.field('Schlüssel'), '  ');
    await waitFor(() => expect(view.field('Schlüssel').value).toBe('800'));
    await retype(view.field('Name'), '');
    await waitFor(() => expect(view.field('Name').value).toBe('Kultur'));
    expect(view.api.updateNode).not.toHaveBeenCalled();
  });

  it('§F/finance/budget/000246: names the error of a key or a name and saves neither', async () => {
    const view = await setup();
    await retype(view.field('Schlüssel'), 'A-1');
    expect(screen.getByText('Nur Buchstaben und Ziffern, höchstens 64 Zeichen.')).toBeInTheDocument();
    expect(view.field('Schlüssel').value).toBe('A-1');
    const name = view.field('Name');
    await userEvent.click(name);
    await userEvent.paste('x'.repeat(200));
    await userEvent.tab();
    expect(screen.getByText('Höchstens 200 Zeichen.')).toBeInTheDocument();
    expect(view.api.updateNode).not.toHaveBeenCalled();
  });

  it('the switch waits while a save runs, so two presses never race', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(pending);
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    await userEvent.click(active);
    view.fixture.detectChanges();
    expect(active).toBeDisabled();
    await userEvent.click(active);
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
    pending.next({});
    pending.complete();
    view.fixture.detectChanges();
    expect(active).toBeEnabled();
  });

  it('saves the colour, the Gremien and the switch', async () => {
    const view = await setup();
    await userEvent.click(screen.getByRole('button', { name: `Farbe ${PALETTE[0]}` }));
    await userEvent.click(screen.getByRole('button', { name: 'Farbe entfernen' }));
    await pick(/Sichtbar für Gremium/, 'StuPa');
    await pick(/Entscheidendes Gremium/, 'StuPa');
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([
      { color: PALETTE[0] },
      { color: '' },
      { viewGremiumId: 'g1' },
      { decisionGremiumId: 'g1' },
      { active: false },
    ]);
  });

  it('saves no colour that did not change', async () => {
    const view = await setup({ color: null });
    expect(view.field('Farbe als Hex-Wert').value).toBe('');
    await userEvent.click(view.field('Farbe als Hex-Wert'));
    await userEvent.tab();
    expect(view.api.updateNode).not.toHaveBeenCalled();
  });

  it('removes a Gremium with the empty choice', async () => {
    const view = await setup({ viewGremiumId: 'g1' });
    await waitFor(() => expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('StuPa'));
    await pick(/Sichtbar für Gremium/, 'Ohne Gremium');
    expect(view.api.updateNode).toHaveBeenCalledWith('ks', { viewGremiumId: null });
    await pick(/Entscheidendes Gremium/, 'Wie übergeordnet');
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
  });

  it('§F/finance/budget/000795: saves another side through the plan API', async () => {
    const view = await setup();
    await pick(/Seite/, 'Einnahme');
    expect(view.planApi.setSide).not.toHaveBeenCalled();
    await pick(/Seite/, 'Ausgabe');
    expect(view.planApi.setSide).toHaveBeenCalledWith('ks', 'expense');
    expect(view.saved).toHaveBeenCalledTimes(1);
    expect(view.success).toHaveBeenCalledWith('Gespeichert.');
  });

  it('§F/finance/budget/000795: a refused side shows its reason and the saved side again', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.planApi.setSide.mockReturnValueOnce(pending);
    await pick(/Seite/, 'Ausgabe');
    expect(screen.getByRole('combobox', { name: /Seite/ })).toHaveTextContent('Ausgabe');
    pending.error({ status: 409, error: { code: 'side_in_plan' } });
    expect(view.error).toHaveBeenCalledWith('Die Seite lässt sich nicht ändern, weil die Kostenstelle einen Ansatz oder einen Vermerk in einem Plan hat.');
    await waitFor(() => expect(screen.getByRole('combobox', { name: /Seite/ })).toHaveTextContent('Einnahme'));
  });

  it('shows the reason of a refused save and takes the saved values again', async () => {
    const view = await setup({}, 'budget_key_exists');
    await retype(view.field('Schlüssel'), '900');
    expect(view.error).toHaveBeenCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
    await waitFor(() => expect(view.field('Schlüssel').value).toBe('800'));
    expect(view.saved).toHaveBeenCalledTimes(1);
  });

  it('takes the empty colour again after a refused save of a Kostenstelle without one', async () => {
    const view = await setup({ color: null, side: undefined }, 'x');
    await userEvent.click(screen.getByRole('button', { name: `Farbe ${PALETTE[0]}` }));
    expect(view.error).toHaveBeenCalledWith('Die Kostenstelle konnte nicht gespeichert werden.');
    await waitFor(() => expect(view.field('Farbe als Hex-Wert').value).toBe(''));
  });
});
