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
  const api = { updateNode: jest.fn((_id: string, _patch: object) => answer()), changed: new Subject<void>() };
  const planApi = { setSide: jest.fn((_id: string, _side: string) => answer()) };
  const saved = jest.fn();
  const sideSaved = jest.fn();
  const view = await render(CostCentreSettingsComponent, {
    inputs: { node: { ...KS, ...over }, sided, gremiumOptions: [{ value: 'g1', label: 'StuPa' }] },
    on: { saved, sideSaved },
    providers: [
      { provide: BudgetTreeApi, useValue: api },
      { provide: BudgetPlanApi, useValue: planApi },
    ],
  });
  const toast = TestBed.inject(ToastService);
  const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
  return { ...view, api, planApi, saved, sideSaved, field, success: jest.spyOn(toast, 'success'), error: jest.spyOn(toast, 'error') };
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
    expect(view.sideSaved).not.toHaveBeenCalled();
    expect(view.success).toHaveBeenCalledWith('Gespeichert.');
    await retype(view.field('Schlüssel'), '800');
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
    await retype(view.field('Schlüssel'), '810');
    expect(view.api.updateNode).toHaveBeenLastCalledWith('ks', { key: '810' });
  });

  it('§F/finance/budget/000849: keeps the text a person types while the page reads the tree again', async () => {
    const view = await setup();
    await userEvent.clear(view.field('Schlüssel'));
    await userEvent.type(view.field('Schlüssel'), '59');
    view.fixture.componentRef.setInput('node', { ...KS });
    view.fixture.detectChanges();
    await userEvent.type(view.field('Schlüssel'), '8');
    expect(view.field('Schlüssel').value).toBe('598');
    view.fixture.componentRef.setInput('node', { ...KS, name: 'Kultur und Sport' });
    view.fixture.detectChanges();
    await waitFor(() => expect(view.field('Name').value).toBe('Kultur und Sport'));
    expect(view.field('Schlüssel').value).toBe('598');
    await userEvent.tab();
    expect(view.api.updateNode).toHaveBeenCalledWith('ks', { key: '598' });
  });

  it('§F/finance/budget/000831: another Kostenstelle with the same values shows its saved values', async () => {
    const view = await setup();
    await retype(view.field('Schlüssel'), '8 1');
    await retype(view.field('Farbe als Hex-Wert'), '#12');
    view.fixture.componentRef.setInput('node', { ...KS, id: 'other' });
    view.fixture.detectChanges();
    await waitFor(() => expect(view.field('Schlüssel').value).toBe('800'));
    expect(view.field('Farbe als Hex-Wert').value).toBe('#112233');
    expect(view.api.updateNode).not.toHaveBeenCalled();
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

  it('§F/finance/budget/000849: the switch keeps the focus, and a press while a save runs waits for it', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(pending);
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    active.focus();
    await userEvent.keyboard(' ');
    view.fixture.detectChanges();
    expect(active).toBeEnabled();
    expect(document.activeElement).toBe(active);
    expect(active).toHaveAttribute('aria-checked', 'false');
    await userEvent.keyboard(' ');
    expect(active).toHaveAttribute('aria-checked', 'true');
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
    pending.next({});
    pending.complete();
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([{ active: false }, { active: true }]);
    await userEvent.keyboard(' ');
    await userEvent.keyboard(' ');
    expect(view.api.updateNode).toHaveBeenCalledTimes(4);
  });

  it('§F/finance/budget/000831: a save tells the page whether the server took it', async () => {
    const taken = await setup();
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    expect(taken.saved).toHaveBeenCalledWith(true);
    const refused = await setup({}, 'key_taken');
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    expect(refused.saved).toHaveBeenCalledWith(false);
  });

  it('§F/finance/budget/000831: a refused switch shows the saved state again', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(pending);
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    await userEvent.click(active);
    view.fixture.detectChanges();
    expect(active).toHaveAttribute('aria-checked', 'false');
    pending.error({ status: 409, error: { code: 'x' } });
    view.fixture.detectChanges();
    expect(active).toHaveAttribute('aria-checked', 'true');
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
  });

  it('§F/finance/budget/000849: the switch keeps the second press while the tree holds the first', async () => {
    const view = await setup();
    const first = new Subject<object>();
    const second = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first).mockReturnValueOnce(second);
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    await userEvent.click(active);
    await userEvent.click(active);
    first.next({});
    first.complete();
    view.fixture.componentRef.setInput('node', { ...KS, active: false });
    view.fixture.detectChanges();
    expect(active).toHaveAttribute('aria-checked', 'true');
    second.next({});
    second.complete();
    view.fixture.componentRef.setInput('node', { ...KS, active: true });
    view.fixture.detectChanges();
    expect(active).toHaveAttribute('aria-checked', 'true');
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([{ active: false }, { active: true }]);
  });

  it('§F/finance/budget/000831: a refused Gremium shows the saved one again', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(pending);
    await pick(/Sichtbar für Gremium/, 'StuPa');
    await waitFor(() => expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('StuPa'));
    pending.error({ status: 409, error: { code: 'x' } });
    await waitFor(() => expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('Ohne Gremium'));
  });

  it('§F/finance/budget/000849: a refused key keeps the text that the person types in the name', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(pending);
    await retype(view.field('Schlüssel'), '900');
    await userEvent.type(view.field('Name'), ' XY');
    pending.error({ status: 409, error: { code: 'budget_key_exists' } });
    await waitFor(() => expect(view.field('Schlüssel').value).toBe('800'));
    expect(view.field('Name').value).toBe('Kultur XY');
  });

  it('§F/finance/budget/000849: each press that waits is saved for its own Kostenstelle', async () => {
    const view = await setup();
    const name = new Subject<object>();
    const press = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(name).mockReturnValueOnce(press);
    await retype(view.field('Name'), 'Kultur neu');
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    view.fixture.componentRef.setInput('node', { ...KS, id: 'other' });
    view.fixture.detectChanges();
    expect(screen.getByRole('switch', { name: 'Aktiv' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    name.next({});
    name.complete();
    expect(view.api.updateNode).toHaveBeenLastCalledWith('ks', { active: false });
    press.error({ status: 409, error: { code: 'x' } });
    view.fixture.detectChanges();
    expect(view.api.updateNode.mock.calls.slice(1)).toEqual([
      ['ks', { active: false }],
      ['other', { active: false }],
    ]);
    expect(screen.getByRole('switch', { name: 'Aktiv' })).toHaveAttribute('aria-checked', 'false');
  });

  it('§F/finance/budget/000849: a refused save of the Kostenstelle before leaves the fields of the selected one', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(pending);
    await retype(view.field('Schlüssel'), '900');
    view.fixture.componentRef.setInput('node', { ...KS, id: 'other' });
    view.fixture.detectChanges();
    await waitFor(() => expect(view.field('Schlüssel').value).toBe('800'));
    await userEvent.type(view.field('Schlüssel'), '7');
    pending.error({ status: 409, error: { code: 'budget_key_exists' } });
    view.fixture.detectChanges();
    expect(view.field('Schlüssel').value).toBe('8007');
  });

  it('§F/finance/budget/000849: a choice that is set back while its save runs is saved again, one save at a time', async () => {
    const view = await setup();
    const first = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first);
    await pick(/Sichtbar für Gremium/, 'StuPa');
    await pick(/Sichtbar für Gremium/, 'Ohne Gremium');
    await retype(view.field('Name'), 'Kultur neu');
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
    first.next({});
    first.complete();
    view.fixture.componentRef.setInput('node', { ...KS, viewGremiumId: 'g1', name: 'Kultur neu' });
    view.fixture.detectChanges();
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([
      { viewGremiumId: 'g1' },
      { viewGremiumId: null },
      { name: 'Kultur neu' },
    ]);
    expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('Ohne Gremium');
    view.fixture.componentRef.setInput('node', { ...KS, name: 'Kultur neu' });
    view.fixture.detectChanges();
    view.fixture.componentRef.setInput('node', { ...KS, viewGremiumId: 'g1', name: 'Kultur neu' });
    view.fixture.detectChanges();
    await waitFor(() => expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('StuPa'));
  });

  it('§F/finance/budget/000849: a name keeps the last text when the tree of the save before comes after the last save', async () => {
    const view = await setup();
    await retype(view.field('Name'), 'Kultur a');
    await retype(view.field('Name'), 'Kultur b');
    view.fixture.componentRef.setInput('node', { ...KS, name: 'Kultur a' });
    view.fixture.detectChanges();
    expect(view.field('Name').value).toBe('Kultur b');
    view.fixture.componentRef.setInput('node', { ...KS, name: 'Kultur b' });
    view.fixture.detectChanges();
    expect(view.field('Name').value).toBe('Kultur b');
  });

  it('§F/finance/budget/000849: the third press is saved while the tree holds the state of the first', async () => {
    const view = await setup();
    const first = new Subject<object>();
    const second = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first).mockReturnValueOnce(second);
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    await userEvent.click(active);
    await userEvent.click(active);
    first.next({});
    first.complete();
    view.fixture.componentRef.setInput('node', { ...KS, active: false });
    view.fixture.detectChanges();
    await userEvent.click(active);
    second.next({});
    second.complete();
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([{ active: false }, { active: true }, { active: false }]);
    expect(active).toHaveAttribute('aria-checked', 'false');
  });

  it('§F/finance/budget/000849: a Gremium that is removed and set again while the save runs is saved again', async () => {
    const view = await setup({ viewGremiumId: 'g1' });
    await waitFor(() => expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('StuPa'));
    const first = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first);
    await pick(/Sichtbar für Gremium/, 'Ohne Gremium');
    await pick(/Sichtbar für Gremium/, 'StuPa');
    first.next({});
    first.complete();
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([{ viewGremiumId: null }, { viewGremiumId: 'g1' }]);
    expect(screen.getByRole('combobox', { name: /Sichtbar für Gremium/ })).toHaveTextContent('StuPa');
  });

  it('§F/finance/budget/000849: the fourth press is saved when the trees of the first two saves come during the third', async () => {
    const view = await setup();
    const saves = [new Subject<object>(), new Subject<object>(), new Subject<object>()];
    saves.forEach((save) => view.api.updateNode.mockReturnValueOnce(save));
    const end = (save: Subject<object>) => {
      save.next({});
      save.complete();
    };
    const tree = (active: boolean) => {
      view.fixture.componentRef.setInput('node', { ...KS, active });
      view.fixture.detectChanges();
    };
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    await userEvent.click(active);
    await userEvent.click(active);
    end(saves[0]);
    await userEvent.click(active);
    end(saves[1]);
    tree(false);
    tree(true);
    await userEvent.click(active);
    end(saves[2]);
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([
      { active: false },
      { active: true },
      { active: false },
      { active: true },
    ]);
    expect(active).toHaveAttribute('aria-checked', 'true');
  });

  it('§F/finance/budget/000849: a Kostenstelle that the person left and selects again counts with its tree value', async () => {
    const view = await setup();
    await retype(view.field('Name'), 'Neu');
    view.fixture.componentRef.setInput('node', { ...KS, id: 'other', name: 'B' });
    view.fixture.detectChanges();
    view.fixture.componentRef.setInput('node', { ...KS, name: 'Kultur' });
    view.fixture.detectChanges();
    await waitFor(() => expect(view.field('Name').value).toBe('Kultur'));
    await retype(view.field('Name'), 'Neu');
    expect(view.api.updateNode.mock.calls).toEqual([
      ['ks', { name: 'Neu' }],
      ['ks', { name: 'Neu' }],
    ]);
  });

  it('§F/finance/budget/000849: a value that another person set back is saved again', async () => {
    const view = await setup();
    await retype(view.field('Name'), 'Neu');
    view.fixture.componentRef.setInput('node', { ...KS, name: 'Neu' });
    view.fixture.detectChanges();
    view.fixture.componentRef.setInput('node', { ...KS, name: 'Kultur' });
    view.fixture.detectChanges();
    await waitFor(() => expect(view.field('Name').value).toBe('Kultur'));
    await retype(view.field('Name'), 'Neu');
    expect(view.api.updateNode.mock.calls).toEqual([
      ['ks', { name: 'Neu' }],
      ['ks', { name: 'Neu' }],
    ]);
  });

  it('§F/finance/budget/000849: a refused save leaves the choice that waits in its switch', async () => {
    const view = await setup();
    const first = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first).mockReturnValueOnce(new Subject<object>());
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    await userEvent.click(active);
    await userEvent.click(active);
    await userEvent.click(active);
    first.error({ status: 409, error: { code: 'x' } });
    view.fixture.detectChanges();
    expect(active).toHaveAttribute('aria-checked', 'false');
    expect(view.api.updateNode.mock.calls.map((call) => call[1])).toEqual([{ active: false }, { active: false }]);
  });

  it('§F/finance/budget/000849: a choice that is back at the saved value sends nothing for a Kostenstelle that the person left', async () => {
    const view = await setup();
    const first = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first);
    await retype(view.field('Name'), 'Neu');
    const active = screen.getByRole('switch', { name: 'Aktiv' });
    await userEvent.click(active);
    await userEvent.click(active);
    view.fixture.componentRef.setInput('node', { ...KS, id: 'other' });
    view.fixture.detectChanges();
    first.next({});
    first.complete();
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
  });

  it('§F/finance/budget/000831: a refused text that the section takes again at its close shows its cause once', async () => {
    const view = await setup();
    const first = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first);
    await retype(view.field('Name'), 'Neu');
    view.fixture.destroy();
    first.error({ status: 409, error: { code: 'x' } });
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
  });

  it('§F/finance/budget/000849: a field that the person left without a change sends nothing after another Kostenstelle is selected', async () => {
    const view = await setup();
    const first = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(first);
    await userEvent.click(screen.getByRole('switch', { name: 'Aktiv' }));
    await userEvent.click(view.field('Name'));
    await userEvent.tab();
    view.fixture.componentRef.setInput('node', { ...KS, id: 'other' });
    view.fixture.detectChanges();
    first.next({});
    first.complete();
    expect(view.api.updateNode).toHaveBeenCalledTimes(1);
  });

  it('§F/finance/budget/000850: a typed key is saved when the section goes off the page', async () => {
    const view = await setup();
    await userEvent.type(view.field('Schlüssel'), '9');
    view.fixture.destroy();
    expect(view.api.updateNode).toHaveBeenCalledWith('ks', { key: `${KS.key}9` });
  });

  it('§F/finance/budget/000850: a typed text is saved when the section goes off the page', async () => {
    const view = await setup();
    const reread = jest.fn();
    view.api.changed.subscribe(reread);
    const pending = new Subject<object>();
    view.api.updateNode.mockReturnValueOnce(pending);
    await userEvent.type(view.field('Name'), ' Y');
    view.fixture.destroy();
    expect(view.api.updateNode).toHaveBeenCalledWith('ks', { name: 'Kultur Y' });
    pending.next({});
    pending.complete();
    expect(reread).toHaveBeenCalledTimes(1);
    expect(view.saved).not.toHaveBeenCalled();
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

  it('saves no side and no Gremium that did not change', async () => {
    const view = await setup({ viewGremiumId: 'g1' });
    const settings = view.fixture.componentInstance;
    settings.saveSide(null);
    settings.saveSide(settings.node().side ?? null);
    settings.saveGremium('viewGremiumId', 'g1');
    settings.saveGremium('decisionGremiumId', null);
    settings.saveGremium('decisionGremiumId', '');
    expect(view.planApi.setSide).not.toHaveBeenCalled();
    expect(view.api.updateNode).not.toHaveBeenCalled();
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
    expect(view.sideSaved).toHaveBeenCalledTimes(1);
    expect(view.success).toHaveBeenCalledWith('Gespeichert.');
  });

  it('§F/finance/budget/000795 §F/finance/budget/000816: a refused side shows its reason and the saved side again', async () => {
    const view = await setup();
    const pending = new Subject<object>();
    view.planApi.setSide.mockReturnValueOnce(pending);
    await pick(/Seite/, 'Ausgabe');
    expect(screen.getByRole('combobox', { name: /Seite/ })).toHaveTextContent('Ausgabe');
    pending.error({ status: 409, error: { code: 'side_in_plan' } });
    expect(view.error).toHaveBeenCalledWith('Die Seite lässt sich nicht ändern, weil die Kostenstelle einen Ansatz oder einen Vermerk in einem Plan hat.');
    await waitFor(() => expect(screen.getByRole('combobox', { name: /Seite/ })).toHaveTextContent('Einnahme'));
    expect(view.sideSaved).not.toHaveBeenCalled();
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
