import { type Observable, Subject, of, throwError } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../../budget/budget-tree.api';
import { BudgetPlanApi, type PlanSteps, type PlanSwitchChange } from '../../budget/plan/budget-plan.api';
import { FY25, FY26, QSM, TOP, fy, node, plan, version } from '../../budget/plan/budget-plan.fixtures';
import { AdminApiService } from '../admin-api.service';
import { AdminBudgetsComponent } from './admin-budgets.component';

const problem = (status: number, code = '') => ({ status, error: { code } });
const refuse = (status: number, code = ''): Observable<never> => throwError(() => problem(status, code));
const STEPS = [
  { name: 'Beschluss', gremiumId: 'g1' },
  { name: 'Genehmigung', gremiumId: null },
];
/** VS-Mittel with a side on each Kostenstelle directly below it. */
const VSM: BudgetTreeNode = { ...TOP, children: TOP.children.filter((c) => c.id !== 'noside') };
/** A budget without a plan: one Kostenstelle without a side, one with a side. */
const KSM: BudgetTreeNode = node({
  id: 'ksm',
  name: 'Kultur',
  children: [node({ id: 'k1', parentId: 'ksm', name: 'Feste' }), node({ id: 'k2', parentId: 'ksm', name: 'Reisen', side: 'expense' })],
});
const CHANGE: PlanSwitchChange = {
  fiscalYearId: 'fy-26',
  year: '2026/27',
  budgetId: 'k1',
  pathKey: 'KSM-K1',
  name: 'Feste',
  allocated: '100',
  planned: '0',
};

interface Opts {
  tree?: Observable<readonly BudgetTreeNode[]>;
  perms?: readonly string[];
  gremienFail?: boolean;
  years?: readonly FiscalYear[];
}

async function setup(opts: Opts = {}) {
  TestBed.resetTestingModule();
  const perms = opts.perms ?? ['budget.structure'];
  const ok = (..._args: unknown[]): Observable<unknown> => of({});
  const api = {
    tree: jest.fn(() => opts.tree ?? of([VSM, QSM, KSM])),
    createNode: jest.fn(ok),
    updateNode: jest.fn(ok),
    deleteNode: jest.fn(ok),
    listFiscalYears: jest.fn((_id: string): Observable<readonly FiscalYear[]> => of(opts.years ?? [FY25, FY26])),
    createFiscalYear: jest.fn(ok),
    updateFiscalYear: jest.fn(ok),
    setFiscalYearClosed: jest.fn(ok),
    deleteFiscalYear: jest.fn(ok),
  };
  const planApi = {
    steps: jest.fn((id: string): Observable<PlanSteps> => of({ budgetId: id, steps: id === 'vsm' ? STEPS : [] })),
    setSteps: jest.fn(ok),
    setPlanSwitch: jest.fn(ok),
    setSide: jest.fn(ok),
    switchPreview: jest.fn((id: string) => of({ budgetId: id, changes: [] as readonly PlanSwitchChange[] })),
    plan: jest.fn((..._args: unknown[]): Observable<unknown> => refuse(404, 'plan_not_found')),
  };
  const view = await render(AdminBudgetsComponent, {
    providers: [
      provideRouter([]),
      { provide: BudgetTreeApi, useValue: api },
      { provide: BudgetPlanApi, useValue: planApi },
      { provide: AuthService, useValue: { can: (p: string) => perms.includes(p) } },
      {
        provide: AdminApiService,
        useValue: { listGremienOptions: () => (opts.gremienFail ? refuse(500) : of([{ id: 'g1', name: 'StuPa' }])) },
      },
    ],
  });
  const toast = TestBed.inject(ToastService);
  return { ...view, api, planApi, success: jest.spyOn(toast, 'success'), error: jest.spyOn(toast, 'error') };
}

const field = (scope: HTMLElement, name: string) => scope.querySelector<HTMLInputElement>(`[name="${name}"] input`) as HTMLInputElement;
const labelled = (scope: HTMLElement, label: string) => within(scope).getByLabelText(new RegExp(`^${label}`)) as HTMLInputElement;
const button = (scope: HTMLElement, name: string | RegExp) => within(scope).getByRole('button', { name });

/** Replace the text of a field. */
async function retype(input: HTMLInputElement, value: string): Promise<void> {
  await userEvent.clear(input);
  if (value) await userEvent.type(input, value);
}
/** Choose an option of a select field of a dialog. */
async function pick(scope: HTMLElement, label: string | RegExp, option: string): Promise<void> {
  await userEvent.click(within(scope).getByRole('combobox', { name: label }));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}
/** Open the edit form of a budget with a press on its row. */
async function openEdit(name: string): Promise<HTMLElement> {
  await userEvent.click(screen.getByText(name));
  return screen.findByRole('dialog', { name: 'Budget bearbeiten' });
}
/** Press an item of the menu of a row. */
async function rowMenu(row: string, item: string): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: `Aktionen: ${row}` }));
  await userEvent.click(await screen.findByRole('menuitem', { name: item }));
}
/** Open the fiscal years of VS-Mittel. */
async function openYears(row = 'VS-Mittel'): Promise<HTMLElement> {
  await rowMenu(row, 'Haushaltsjahre');
  return screen.findByRole('dialog', { name: `Haushaltsjahre: ${row}` });
}

describe('AdminBudgetsComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    jest.useFakeTimers({
      now: new Date('2026-11-12T10:00:00Z'),
      doNotFake: [
        'hrtime',
        'nextTick',
        'performance',
        'queueMicrotask',
        'requestAnimationFrame',
        'cancelAnimationFrame',
        'requestIdleCallback',
        'cancelIdleCallback',
        'setImmediate',
        'clearImmediate',
        'setInterval',
        'clearInterval',
        'setTimeout',
        'clearTimeout',
      ],
    });
  });
  afterEach(() => jest.useRealTimers());

  describe('list', () => {
    it('§F/finance/budget/000828: lists only the top-level budgets, each with its start and its plan switch', async () => {
      const view = await setup({ tree: of([VSM, { ...QSM, active: false }]) });
      expect(screen.getByText('VS-Mittel')).toBeInTheDocument();
      expect(screen.queryByText('Beiträge')).toBeNull();
      expect(screen.getAllByText('01.03.')).toHaveLength(2);
      expect(screen.getByText('Mit Haushaltsplan')).toBeInTheDocument();
      expect(screen.getByText('Ohne Haushaltsplan')).toBeInTheDocument();
      expect(screen.getByText('Inaktiv')).toBeInTheDocument();
      expect(screen.getAllByRole('columnheader').map((h) => h.textContent?.trim())).toEqual([
        'Budget',
        'Beginn des Haushaltsjahrs',
        'Haushaltsplan',
        'Aktionen',
      ]);
      expect(await axe(view.container)).toHaveNoViolations();
    });

    it('shows the load error and reads the list again on the retry', async () => {
      const view = await setup({ tree: refuse(500), gremienFail: true });
      expect(screen.queryByText('VS-Mittel')).toBeNull();
      view.api.tree.mockReturnValueOnce(of([VSM]));
      (view.fixture.debugElement.query(By.directive(LoadErrorComponent)).componentInstance as LoadErrorComponent).retry.emit();
      view.fixture.detectChanges();
      expect(screen.getByText('VS-Mittel')).toBeInTheDocument();
      const dialog = await openEdit('VS-Mittel');
      await userEvent.click(within(dialog).getByRole('combobox', { name: 'Sichtbar für Gremium' }));
      expect(screen.queryByRole('option', { name: 'StuPa' })).toBeNull();
    });

    it('shows the empty state without a budget', async () => {
      await setup({ tree: of([]) });
      expect(screen.getByText('Noch keine Budgets angelegt.')).toBeInTheDocument();
    });
  });

  describe('create', () => {
    it('creates a budget with the start of its fiscal year', async () => {
      const view = await setup();
      await userEvent.click(screen.getByRole('button', { name: 'Budget anlegen' }));
      const dialog = await screen.findByRole('dialog', { name: 'Budget anlegen' });
      const create = button(dialog, 'Anlegen');
      expect(create).toBeDisabled();
      await userEvent.type(field(dialog, 'topKey'), 'Q-S');
      await userEvent.type(field(dialog, 'topName'), ' QS-Mittel ');
      expect(within(dialog).getByText('Nur Buchstaben und Ziffern, höchstens 64 Zeichen.')).toBeInTheDocument();
      expect(create).toBeDisabled();
      await retype(field(dialog, 'topKey'), ' QS ');
      await retype(labelled(dialog, 'Tag'), '40');
      await retype(labelled(dialog, 'Monat'), '10');
      expect(within(dialog).getByText('Ein Tag von 1 bis 28.')).toBeInTheDocument();
      expect(create).toBeDisabled();
      await retype(labelled(dialog, 'Tag'), '28');
      await userEvent.click(create);
      expect(view.api.createNode).toHaveBeenCalledWith({ key: 'QS', name: 'QS-Mittel', fiscalStartDay: 28, fiscalStartMonth: 10 });
      expect(view.success).toHaveBeenCalledWith('Budget angelegt.');
      expect(view.api.tree).toHaveBeenCalledTimes(2);
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget anlegen' })).toBeNull());
    });

    it('names the cause of a refused create, keeps the dialog and creates with Enter', async () => {
      const view = await setup();
      view.api.createNode.mockReturnValueOnce(refuse(409, 'budget_key_exists'));
      await userEvent.click(screen.getByRole('button', { name: 'Budget anlegen' }));
      const dialog = await screen.findByRole('dialog', { name: 'Budget anlegen' });
      await userEvent.type(field(dialog, 'topKey'), 'VS');
      await userEvent.type(field(dialog, 'topName'), 'X{Enter}');
      expect(view.error).toHaveBeenCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
      expect(screen.getByRole('dialog', { name: 'Budget anlegen' })).toBeInTheDocument();
      await userEvent.click(button(dialog, 'Abbrechen'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget anlegen' })).toBeNull());
    });

    it('creates nothing a second time while the create runs', async () => {
      const view = await setup();
      view.api.createNode.mockReturnValueOnce(new Subject<unknown>());
      await userEvent.click(screen.getByRole('button', { name: 'Budget anlegen' }));
      const dialog = await screen.findByRole('dialog', { name: 'Budget anlegen' });
      await userEvent.type(field(dialog, 'topKey'), 'VS');
      await userEvent.type(field(dialog, 'topName'), 'X{Enter}');
      await userEvent.type(field(dialog, 'topName'), '{Enter}');
      expect(view.api.createNode).toHaveBeenCalledTimes(1);
    });
  });

  describe('edit', () => {
    it('§F/finance/budget/000827: a press on a row opens the form of the budget with its sides and steps', async () => {
      await setup({ tree: of([{ ...VSM, color: ' #112233 ', viewGremiumId: 'g1', decisionGremiumId: 'g1' }]) });
      const dialog = await openEdit('VS-Mittel');
      await waitFor(() => expect(field(dialog, 'editKey').value).toBe('vsm'));
      expect(field(dialog, 'editName').value).toBe('VS-Mittel');
      expect(labelled(dialog, 'Farbe als Hex-Wert').value).toBe('#112233');
      expect(labelled(dialog, 'Tag').value).toBe('1');
      expect(labelled(dialog, 'Monat').value).toBe('3');
      expect(within(dialog).getByRole('switch', { name: 'Aktiv' })).toBeChecked();
      expect(within(dialog).getByRole('switch', { name: 'Haushaltsplan führen' })).toBeChecked();
      expect(within(dialog).getByRole('combobox', { name: 'Sichtbar für Gremium' })).toHaveTextContent('StuPa');
      expect(within(dialog).getByRole('combobox', { name: 'Entscheidendes Gremium' })).toHaveTextContent('StuPa');
      for (const heading of ['Budget', 'Beginn des Haushaltsjahrs', 'Gremien', 'Haushaltsplan', 'Seite der Kostenstellen', 'Schritte bis zum Inkrafttreten'])
        expect(within(dialog).getByRole('heading', { name: heading })).toBeInTheDocument();
      expect(within(dialog).getByRole('combobox', { name: /Beiträge/ })).toHaveTextContent('Einnahme');
      expect(within(dialog).getByRole('combobox', { name: /Zuschüsse/ })).toHaveTextContent('Ausgabe');
      expect(labelled(dialog, 'Name von Schritt 1').value).toBe('Beschluss');
      expect(labelled(dialog, 'Name von Schritt 2').value).toBe('Genehmigung');
      expect(within(dialog).getByRole('combobox', { name: 'Gremium von Schritt 1' })).toHaveTextContent('StuPa');
      expect(within(dialog).getByRole('combobox', { name: 'Gremium von Schritt 2' })).toHaveTextContent('Ohne Gremium');
    });

    it('a budget without a plan shows neither sides nor steps, and Abbrechen closes the form', async () => {
      const view = await setup();
      const dialog = await openEdit('QS-Mittel');
      expect(within(dialog).getByRole('switch', { name: 'Haushaltsplan führen' })).not.toBeChecked();
      expect(within(dialog).queryByRole('heading', { name: 'Schritte bis zum Inkrafttreten' })).toBeNull();
      expect(within(dialog).queryByRole('heading', { name: 'Seite der Kostenstellen' })).toBeNull();
      await userEvent.click(button(dialog, 'Abbrechen'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget bearbeiten' })).toBeNull());
      expect(view.api.updateNode).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000827: a failed read of the steps shows the error, offers no step and keeps the stored steps', async () => {
      const view = await setup();
      view.planApi.steps.mockReturnValueOnce(refuse(500));
      const first = await openEdit('VS-Mittel');
      const loadError = () => view.fixture.debugElement.queryAll(By.directive(LoadErrorComponent)).map((d) => (d.componentInstance as LoadErrorComponent).message());
      expect(loadError()).toContain('Die Schritte konnten nicht geladen werden.');
      expect(within(first).queryByText('Keine Schritte')).toBeNull();
      expect(within(first).queryByRole('button', { name: 'Schritt hinzufügen' })).toBeNull();
      await userEvent.click(button(first, 'Speichern'));
      await waitFor(() => expect(view.api.updateNode).toHaveBeenCalled());
      expect(view.planApi.setSteps).not.toHaveBeenCalled();
      const again = await openEdit('VS-Mittel');
      view.planApi.steps.mockReturnValueOnce(refuse(500));
      view.fixture.componentInstance.loadSteps();
      view.fixture.detectChanges();
      expect(within(again).queryByRole('button', { name: 'Schritt hinzufügen' })).toBeNull();
      const stepsError = view.fixture.debugElement
        .queryAll(By.directive(LoadErrorComponent))
        .map((d) => d.componentInstance as LoadErrorComponent)
        .find((c) => c.message() === 'Die Schritte konnten nicht geladen werden.');
      stepsError?.retry.emit();
      view.fixture.detectChanges();
      expect(within(again).getByRole('button', { name: 'Schritt hinzufügen' })).toBeInTheDocument();
      const first2 = again;
      await userEvent.click(button(first2, 'Abbrechen'));
      view.fixture.componentInstance.loadSteps();
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget bearbeiten' })).toBeNull());
      const late = new Subject<PlanSteps>();
      view.planApi.steps.mockReturnValueOnce(late);
      const second = await openEdit('VS-Mittel');
      await userEvent.click(button(second, 'Abbrechen'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget bearbeiten' })).toBeNull());
      const third = await openEdit('Kultur');
      await userEvent.click(within(third).getByRole('switch', { name: 'Haushaltsplan führen' }));
      late.next({ budgetId: 'vsm', steps: [{ name: 'Alt', gremiumId: null }] });
      view.fixture.detectChanges();
      expect(within(third).getByText('Keine Schritte')).toBeInTheDocument();
    });

    it('§F/finance/budget/000827: adds, names, moves and removes the steps, and saves them in their order', async () => {
      const view = await setup();
      const dialog = await openEdit('VS-Mittel');
      await userEvent.click(button(dialog, 'Schritt hinzufügen'));
      await userEvent.type(labelled(dialog, 'Name von Schritt 3'), ' Anzeige ');
      await pick(dialog, 'Gremium von Schritt 3', 'StuPa');
      const third = labelled(dialog, 'Name von Schritt 3').closest('li') as HTMLElement;
      await userEvent.click(button(third, 'Nach oben'));
      await waitFor(() => expect(labelled(dialog, 'Name von Schritt 2').value.trim()).toBe('Anzeige'));
      await userEvent.click(button(dialog, 'Schritt 1 entfernen'));
      await waitFor(() => expect(labelled(dialog, 'Name von Schritt 1').value.trim()).toBe('Anzeige'));
      await userEvent.click(button(labelled(dialog, 'Name von Schritt 1').closest('li') as HTMLElement, 'Nach unten'));
      await waitFor(() => expect(labelled(dialog, 'Name von Schritt 2').value.trim()).toBe('Anzeige'));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.planApi.setSteps).toHaveBeenCalledWith('vsm', [
        { name: 'Genehmigung', gremiumId: null },
        { name: 'Anzeige', gremiumId: 'g1' },
      ]);
      expect(view.planApi.setPlanSwitch).not.toHaveBeenCalled();
      expect(view.planApi.setSide).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000827: a step without a name shows what is missing, and ten steps take no eleventh', async () => {
      const view = await setup();
      view.planApi.steps.mockReturnValueOnce(of({ budgetId: 'vsm', steps: Array.from({ length: 9 }, (_, i) => ({ name: `S${i}`, gremiumId: null })) }));
      const dialog = await openEdit('VS-Mittel');
      await userEvent.click(button(dialog, 'Schritt hinzufügen'));
      expect(within(dialog).queryByRole('button', { name: 'Schritt hinzufügen' })).toBeNull();
      expect(within(dialog).queryByText('Pflichtfeld')).toBeNull();
      await userEvent.click(button(dialog, 'Speichern'));
      expect(within(dialog).getByText('Pflichtfeld')).toBeInTheDocument();
      expect(view.api.updateNode).not.toHaveBeenCalled();
      expect(screen.getByRole('dialog', { name: 'Budget bearbeiten' })).toBeInTheDocument();
    });

    it('"Speichern" names an empty or wrong key, name and colour and saves nothing', async () => {
      const view = await setup();
      const dialog = await openEdit('VS-Mittel');
      await retype(field(dialog, 'editKey'), '');
      await retype(field(dialog, 'editName'), ' ');
      expect(within(dialog).queryByText('Pflichtfeld')).toBeNull();
      const save = button(dialog, 'Speichern');
      expect(save).toBeEnabled();
      await userEvent.click(save);
      expect(within(dialog).getAllByText('Pflichtfeld')).toHaveLength(2);
      await retype(field(dialog, 'editKey'), 'V-S');
      expect(within(dialog).getByText('Nur Buchstaben und Ziffern, höchstens 64 Zeichen.')).toBeInTheDocument();
      await userEvent.click(field(dialog, 'editName'));
      await userEvent.paste('x'.repeat(201));
      expect(within(dialog).getByText('Höchstens 200 Zeichen.')).toBeInTheDocument();
      await retype(field(dialog, 'editKey'), 'VS');
      await retype(field(dialog, 'editName'), 'VS');
      await retype(labelled(dialog, 'Farbe als Hex-Wert'), '#12');
      await userEvent.click(save);
      expect(view.api.updateNode).not.toHaveBeenCalled();
    });

    it('saves only the settings when the plan switch, the sides and the steps did not change', async () => {
      const view = await setup();
      const dialog = await openEdit('VS-Mittel');
      await retype(field(dialog, 'editName'), ' VS ');
      await userEvent.type(field(dialog, 'editName'), '{Enter}');
      expect(view.api.updateNode).toHaveBeenCalledWith('vsm', { key: 'vsm', name: 'VS', color: '', active: true, viewGremiumId: null });
      expect(view.planApi.setPlanSwitch).not.toHaveBeenCalled();
      expect(view.planApi.setSteps).not.toHaveBeenCalled();
      expect(view.planApi.setSide).not.toHaveBeenCalled();
      expect(view.planApi.switchPreview).not.toHaveBeenCalled();
      expect(view.success).toHaveBeenCalledWith('Gespeichert.');
      expect(view.api.tree).toHaveBeenCalledTimes(2);
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget bearbeiten' })).toBeNull());
    });

    it('saves the colour, the switch "Aktiv", the Gremien and the start of the fiscal year', async () => {
      const view = await setup({ tree: of([{ ...QSM, decisionGremiumId: 'g1' }]) });
      const dialog = await openEdit('QS-Mittel');
      await retype(labelled(dialog, 'Farbe als Hex-Wert'), '#112233');
      await userEvent.click(within(dialog).getByRole('switch', { name: 'Aktiv' }));
      await pick(dialog, 'Sichtbar für Gremium', 'StuPa');
      await pick(dialog, 'Entscheidendes Gremium', 'Ohne Gremium');
      await retype(labelled(dialog, 'Tag'), '15');
      await retype(labelled(dialog, 'Monat'), '13');
      expect(within(dialog).getByText('Ein Monat von 1 bis 12.')).toBeInTheDocument();
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.api.updateNode).not.toHaveBeenCalled();
      await retype(labelled(dialog, 'Monat'), '12');
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.api.updateNode).toHaveBeenCalledWith('qsm', {
        key: 'qsm',
        name: 'QS-Mittel',
        color: '#112233',
        active: false,
        viewGremiumId: 'g1',
        decisionGremiumId: null,
        fiscalStartDay: 15,
        fiscalStartMonth: 12,
      });
    });

    it('§F/finance/budget/000795: a Kostenstelle without a side shows what is missing in the form, and the save sends its side first', async () => {
      const view = await setup({ tree: of([TOP]) });
      const dialog = await openEdit('VS-Mittel');
      expect(within(dialog).getByRole('combobox', { name: /Ohne Seite/ })).toHaveAttribute('aria-required', 'true');
      await userEvent.click(button(dialog, 'Speichern'));
      expect(within(dialog).getByText('Pflichtfeld')).toBeInTheDocument();
      expect(view.planApi.setSide).not.toHaveBeenCalled();
      expect(view.api.updateNode).not.toHaveBeenCalled();
      expect(view.error).not.toHaveBeenCalled();
      await pick(dialog, /Ohne Seite/, 'Ausgabe');
      expect(within(dialog).queryByText('Pflichtfeld')).toBeNull();
      await pick(dialog, /Beiträge/, 'Ausgabe');
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.planApi.setSide.mock.calls).toEqual([
        ['fees', 'expense'],
        ['noside', 'expense'],
      ]);
      expect(view.planApi.setSide.mock.invocationCallOrder[1]).toBeLessThan(view.api.updateNode.mock.invocationCallOrder[0]);
      expect(view.success).toHaveBeenCalledWith('Gespeichert.');
    });

    it('§F/finance/budget/000803: turning the plan on asks for the sides, shows the changed allocations and saves after the confirmation', async () => {
      const view = await setup();
      view.planApi.switchPreview.mockReturnValue(of({ budgetId: 'ksm', changes: [CHANGE] }));
      const dialog = await openEdit('Kultur');
      await userEvent.click(within(dialog).getByRole('switch', { name: 'Haushaltsplan führen' }));
      await waitFor(() => expect(within(dialog).getByRole('combobox', { name: /Reisen/ })).toHaveTextContent('Ausgabe'));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(within(dialog).getByText('Pflichtfeld')).toBeInTheDocument();
      expect(view.planApi.switchPreview).not.toHaveBeenCalled();
      await pick(dialog, /Feste/, 'Einnahme');
      await userEvent.click(button(dialog, 'Schritt hinzufügen'));
      await userEvent.type(labelled(dialog, 'Name von Schritt 1'), 'Beschluss');
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.planApi.setSide).not.toHaveBeenCalled();
      expect(view.planApi.switchPreview).toHaveBeenCalledWith('ksm', expect.objectContaining({ k1: 'income' }));
      const confirm = await screen.findByRole('dialog', { name: 'Zuteilungen ändern?' });
      expect(confirm).toHaveTextContent('Feste · 2026/27');
      expect(confirm).toHaveTextContent('100 € → 0 €');
      expect(screen.queryByRole('dialog', { name: 'Budget bearbeiten' })).toBeNull();
      expect(view.planApi.setPlanSwitch).not.toHaveBeenCalled();
      await userEvent.click(button(confirm, 'Abbrechen'));
      const again = await screen.findByRole('dialog', { name: 'Budget bearbeiten' });
      await waitFor(() => expect(labelled(again, 'Name von Schritt 1').value).toBe('Beschluss'));
      await userEvent.click(button(again, 'Speichern'));
      expect(view.planApi.setSide).not.toHaveBeenCalled();
      expect(view.planApi.switchPreview).toHaveBeenCalledTimes(2);
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Zuteilungen ändern?' }), 'Haushaltsplan einschalten'));
      expect(view.planApi.setSide.mock.calls).toEqual([['k1', 'income']]);
      expect(view.planApi.setPlanSwitch).toHaveBeenCalledWith('ksm', true, true);
      expect(view.planApi.setSteps).toHaveBeenCalledWith('ksm', [{ name: 'Beschluss', gremiumId: null }]);
      const order = [view.planApi.setSide, view.planApi.setPlanSwitch, view.api.updateNode, view.planApi.setSteps].map(
        (m) => m.mock.invocationCallOrder[0],
      );
      expect(order).toEqual([...order].sort((a, b) => a - b));
      expect(view.success).toHaveBeenCalledWith('Gespeichert.');
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Zuteilungen ändern?' })).toBeNull());
      expect(screen.queryByRole('dialog', { name: 'Budget bearbeiten' })).toBeNull();
    });

    it('§F/finance/budget/000803: turning the plan on without a changed allocation saves at once', async () => {
      const view = await setup();
      const dialog = await openEdit('QS-Mittel');
      await userEvent.click(within(dialog).getByRole('switch', { name: 'Haushaltsplan führen' }));
      expect(within(dialog).queryByRole('heading', { name: 'Seite der Kostenstellen' })).toBeNull();
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.planApi.switchPreview).toHaveBeenCalledWith('qsm', {});
      expect(view.planApi.setPlanSwitch).toHaveBeenCalledWith('qsm', true, true);
      expect(view.planApi.setSteps).not.toHaveBeenCalled();
      expect(screen.queryByRole('dialog', { name: 'Zuteilungen ändern?' })).toBeNull();
    });

    it('§F/finance/budget/000814: turning the plan off sends the switch and neither sides nor steps', async () => {
      const view = await setup({ tree: of([TOP]) });
      const dialog = await openEdit('VS-Mittel');
      await userEvent.click(button(dialog, 'Schritt 1 entfernen'));
      await userEvent.click(within(dialog).getByRole('switch', { name: 'Haushaltsplan führen' }));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.planApi.setPlanSwitch).toHaveBeenCalledWith('vsm', false, false);
      expect(view.planApi.setSteps).not.toHaveBeenCalled();
      expect(view.planApi.setSide).not.toHaveBeenCalled();
      expect(view.planApi.switchPreview).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000814: names why the plan cannot go off, keeps the form and reads the budget again', async () => {
      const view = await setup();
      view.planApi.setPlanSwitch.mockReturnValueOnce(refuse(409, 'plan_switch_has_plans'));
      const dialog = await openEdit('VS-Mittel');
      await userEvent.click(within(dialog).getByRole('switch', { name: 'Haushaltsplan führen' }));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.error).toHaveBeenCalledWith('Der Haushaltsplan lässt sich nicht ausschalten, weil ein Plan beschlossen oder in Arbeit ist.');
      expect(view.api.updateNode).not.toHaveBeenCalled();
      expect(view.api.tree).toHaveBeenCalledTimes(2);
      expect(screen.getByRole('dialog', { name: 'Budget bearbeiten' })).toBeInTheDocument();
    });

    it('names the cause of a refused save and of a failed preview', async () => {
      const view = await setup();
      const dialog = await openEdit('VS-Mittel');
      view.api.updateNode.mockReturnValueOnce(refuse(409, 'budget_key_exists'));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.error).toHaveBeenLastCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
      view.api.updateNode.mockReturnValueOnce(refuse(500));
      view.api.tree.mockReturnValueOnce(refuse(500));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.error).toHaveBeenLastCalledWith('Das Budget konnte nicht gespeichert werden.');
      view.planApi.setSteps.mockReturnValueOnce(refuse(422, 'plan_step_limit'));
      await userEvent.click(button(dialog, 'Schritt hinzufügen'));
      await userEvent.type(labelled(dialog, 'Name von Schritt 3'), 'X');
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.error).toHaveBeenLastCalledWith('Ein Budget hat höchstens 10 Schritte.');
      await userEvent.click(button(dialog, 'Abbrechen'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget bearbeiten' })).toBeNull());
      view.planApi.switchPreview.mockReturnValueOnce(refuse(500));
      const other = await openEdit('QS-Mittel');
      await userEvent.click(within(other).getByRole('switch', { name: 'Haushaltsplan führen' }));
      await userEvent.click(button(other, 'Speichern'));
      expect(view.error).toHaveBeenLastCalledWith('Das Budget konnte nicht gespeichert werden.');
      expect(view.planApi.setPlanSwitch).not.toHaveBeenCalled();
    });

    it('sends nothing a second time while a save runs', async () => {
      const view = await setup();
      view.api.updateNode.mockReturnValueOnce(new Subject<unknown>());
      const dialog = await openEdit('VS-Mittel');
      await userEvent.click(button(dialog, 'Speichern'));
      expect(button(dialog, 'Speichern')).toBeDisabled();
      await userEvent.type(field(dialog, 'editName'), '{Enter}');
      expect(view.api.updateNode).toHaveBeenCalledTimes(1);
    });
  });

  describe('delete', () => {
    it('deletes a budget after the confirmation', async () => {
      const view = await setup();
      await rowMenu('QS-Mittel', 'Löschen');
      const dialog = await screen.findByRole('dialog', { name: 'Budget löschen?' });
      expect(dialog).toHaveTextContent('„QS-Mittel“ (QSM) wird gelöscht. Das lässt sich nicht rückgängig machen.');
      await userEvent.click(button(dialog, 'Abbrechen'));
      expect(view.api.deleteNode).not.toHaveBeenCalled();
      await rowMenu('QS-Mittel', 'Löschen');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Budget löschen?' }), 'Löschen'));
      expect(view.api.deleteNode).toHaveBeenCalledWith('qsm');
      expect(view.success).toHaveBeenCalledWith('Budget gelöscht.');
      expect(view.api.tree).toHaveBeenCalledTimes(2);
    });

    it('names the reason of a refused delete and closes the question', async () => {
      const view = await setup();
      view.api.deleteNode.mockReturnValueOnce(refuse(409, 'budget_has_children'));
      await rowMenu('VS-Mittel', 'Löschen');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Budget löschen?' }), 'Löschen'));
      expect(view.error).toHaveBeenCalledWith('Lösche zuerst die untergeordneten Kostenstellen.');
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Budget löschen?' })).toBeNull());
      view.api.deleteNode.mockReturnValueOnce(refuse(500));
      await rowMenu('VS-Mittel', 'Löschen');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Budget löschen?' }), 'Löschen'));
      expect(view.error).toHaveBeenLastCalledWith('Löschen fehlgeschlagen (nur ohne Unter-Kostenstellen, Buchungen oder zugewiesene Anträge).');
    });
  });

  describe('fiscal years', () => {
    const closed = fy('fy-24', 2024, { closedAt: '2025-03-01T00:00:00Z' });

    it('lists the fiscal years of a budget, the newest first, and offers the next year', async () => {
      const view = await setup({ years: [closed, FY25, { ...FY26, active: false }] });
      const dialog = await openYears();
      const rows = within(dialog).getAllByRole('row').slice(1).map((r) => r.textContent?.replace(/\s+/g, ' ').trim());
      expect(rows).toEqual(['2026/27Inaktiv', '2025/26Aktiv', '2024/25Abgeschlossen']);
      await waitFor(() => expect(field(dialog, 'fyYear').value).toBe('2027'));
      await userEvent.click(button(dialog, 'Fertig'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeNull());
      expect(view.api.listFiscalYears).toHaveBeenCalledWith('vsm');
    });

    it('starts with this year for a budget without a year, and shows no year when the read fails', async () => {
      const view = await setup({ years: [] });
      const dialog = await openYears();
      expect(within(dialog).getByText('Noch keine Haushaltsjahre in diesem Budget.')).toBeInTheDocument();
      await waitFor(() => expect(field(dialog, 'fyYear').value).toBe('2026'));
      await userEvent.click(button(dialog, 'Fertig'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeNull());
      view.api.listFiscalYears.mockReturnValueOnce(refuse(500));
      const failed = await openYears('QS-Mittel');
      expect(within(failed).getByText('Noch keine Haushaltsjahre in diesem Budget.')).toBeInTheDocument();
    });

    it('a reader sees the years without a form and without actions', async () => {
      await setup({ perms: [] });
      const dialog = await openYears();
      expect(within(dialog).getAllByRole('columnheader').map((h) => h.textContent?.trim())).toEqual(['Jahr', 'Status']);
      expect(dialog.querySelector('[name="fyYear"]')).toBeNull();
      expect(within(dialog).queryByRole('button', { name: /^Aktionen/ })).toBeNull();
    });

    it('keeps the years of the budget that is open when a late answer arrives', async () => {
      const view = await setup();
      const late = new Subject<readonly FiscalYear[]>();
      view.api.listFiscalYears.mockReturnValueOnce(late);
      const first = await openYears();
      await userEvent.click(button(first, 'Fertig'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeNull());
      view.api.listFiscalYears.mockReturnValueOnce(of([]));
      const second = await openYears('QS-Mittel');
      late.next([FY25]);
      view.fixture.detectChanges();
      expect(within(second).getByText('Noch keine Haushaltsjahre in diesem Budget.')).toBeInTheDocument();
    });

    it('creates a fiscal year and names a year that is no year', async () => {
      const view = await setup();
      const dialog = await openYears();
      await userEvent.click(button(dialog, 'Anlegen'));
      expect(view.api.createFiscalYear).toHaveBeenCalledWith('vsm', { year: 2027 });
      expect(view.success).toHaveBeenCalledWith('Haushaltsjahr angelegt.');
      expect(view.api.listFiscalYears).toHaveBeenCalledTimes(2);
      await retype(field(dialog, 'fyYear'), '1800');
      expect(within(dialog).getByText('Ein Jahr von 1900 bis 2200.')).toBeInTheDocument();
      await userEvent.type(field(dialog, 'fyYear'), '{Enter}');
      await retype(field(dialog, 'fyYear'), '');
      await userEvent.click(button(dialog, 'Anlegen'));
      expect(view.api.createFiscalYear).toHaveBeenCalledTimes(1);
    });

    it('names the cause of a refused new year', async () => {
      const view = await setup();
      const dialog = await openYears();
      view.api.createFiscalYear.mockReturnValueOnce(refuse(409, 'fiscal_year_exists'));
      await userEvent.click(button(dialog, 'Anlegen'));
      expect(view.error).toHaveBeenLastCalledWith('Dieses Jahr gibt es in diesem Budget bereits.');
      view.api.createFiscalYear.mockReturnValueOnce(refuse(422));
      await userEvent.click(button(dialog, 'Anlegen'));
      expect(view.error).toHaveBeenLastCalledWith('Das Haushaltsjahr konnte nicht gespeichert werden.');
      view.api.createFiscalYear.mockReturnValueOnce(new Subject<unknown>());
      await userEvent.click(button(dialog, 'Anlegen'));
      expect(button(dialog, 'Anlegen')).toBeDisabled();
      await userEvent.type(field(dialog, 'fyYear'), '{Enter}');
      expect(view.api.createFiscalYear).toHaveBeenCalledTimes(3);
    });

    it('a press on a year edits its year and its switch "Aktiv"', async () => {
      const view = await setup();
      const list = await openYears();
      await userEvent.click(within(list).getByText('2025/26'));
      const dialog = await screen.findByRole('dialog', { name: 'Haushaltsjahr bearbeiten' });
      expect(screen.queryByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeNull();
      await waitFor(() => expect(field(dialog, 'fyEditYear').value).toBe('2025'));
      await retype(field(dialog, 'fyEditYear'), '99');
      expect(within(dialog).getByText('Ein Jahr von 1900 bis 2200.')).toBeInTheDocument();
      expect(button(dialog, 'Speichern')).toBeDisabled();
      await userEvent.type(field(dialog, 'fyEditYear'), '{Enter}');
      expect(view.api.updateFiscalYear).not.toHaveBeenCalled();
      await retype(field(dialog, 'fyEditYear'), '2030');
      await userEvent.click(within(dialog).getByRole('switch', { name: 'Aktiv' }));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.api.updateFiscalYear).toHaveBeenCalledWith('vsm', 'fy-25', { year: 2030, active: false });
      expect(view.success).toHaveBeenCalledWith('Haushaltsjahr gespeichert.');
      expect(await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeInTheDocument();
      expect(view.api.listFiscalYears).toHaveBeenCalledTimes(2);
    });

    it('a closed year keeps its year, and a refused edit names its cause', async () => {
      const view = await setup({ years: [closed, FY25] });
      const list = await openYears();
      await userEvent.click(within(list).getByText('2024/25'));
      const dialog = await screen.findByRole('dialog', { name: 'Haushaltsjahr bearbeiten' });
      await waitFor(() => expect(field(dialog, 'fyEditYear')).toBeDisabled());
      view.api.updateFiscalYear.mockReturnValueOnce(refuse(409, 'fiscal_year_closed'));
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.error).toHaveBeenLastCalledWith('Das Haushaltsjahr ist abgeschlossen.');
      const kept = await screen.findByRole('dialog', { name: 'Haushaltsjahr bearbeiten' });
      await userEvent.click(button(kept, 'Abbrechen'));
      const back = await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' });
      await userEvent.click(within(back).getByText('2025/26'));
      const second = await screen.findByRole('dialog', { name: 'Haushaltsjahr bearbeiten' });
      view.api.updateFiscalYear.mockReturnValueOnce(refuse(500));
      await userEvent.click(button(second, 'Speichern'));
      expect(view.error).toHaveBeenLastCalledWith('Das Haushaltsjahr konnte nicht gespeichert werden.');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Haushaltsjahr bearbeiten' }), 'Abbrechen'));
      expect(await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeInTheDocument();
    });

    it('closes an open year and reopens a closed one after the confirmation', async () => {
      const view = await setup({ years: [closed, FY25] });
      await openYears();
      await rowMenu('2025/26', 'Abschließen');
      const close = await screen.findByRole('dialog', { name: 'Haushaltsjahr 2025/26 abschließen?' });
      await userEvent.click(button(close, 'Abbrechen'));
      expect(view.api.setFiscalYearClosed).not.toHaveBeenCalled();
      await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' });
      await rowMenu('2025/26', 'Abschließen');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Haushaltsjahr 2025/26 abschließen?' }), 'Abschließen'));
      expect(view.api.setFiscalYearClosed).toHaveBeenLastCalledWith('vsm', 'fy-25', true);
      expect(view.success).toHaveBeenLastCalledWith('Haushaltsjahr 2025/26 abgeschlossen.');
      await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' });
      await rowMenu('2024/25', 'Wieder öffnen');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Haushaltsjahr 2024/25 wieder öffnen?' }), 'Wieder öffnen'));
      expect(view.api.setFiscalYearClosed).toHaveBeenLastCalledWith('vsm', 'fy-24', false);
      expect(view.success).toHaveBeenLastCalledWith('Haushaltsjahr 2024/25 wieder geöffnet.');
    });

    it('§F/finance/budget/000801: names why a year cannot be closed', async () => {
      const view = await setup();
      await openYears();
      view.api.setFiscalYearClosed.mockReturnValueOnce(refuse(409, 'plan_in_progress'));
      await rowMenu('2025/26', 'Abschließen');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Haushaltsjahr 2025/26 abschließen?' }), 'Abschließen'));
      expect(view.error).toHaveBeenLastCalledWith('Der Haushaltsplan ist noch in Arbeit.');
      await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' });
      view.api.setFiscalYearClosed.mockReturnValueOnce(refuse(500));
      await rowMenu('2025/26', 'Abschließen');
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Haushaltsjahr 2025/26 abschließen?' }), 'Abschließen'));
      expect(view.error).toHaveBeenLastCalledWith('Aktion fehlgeschlagen.');
    });

    it('§F/finance/budget/000823: a step name above 120 characters shows its limit and is not saved', async () => {
      const view = await setup();
      const dialog = await openEdit('VS-Mittel');
      const name = labelled(dialog, 'Name von Schritt 1');
      await userEvent.clear(name);
      await userEvent.click(name);
      await userEvent.paste('x'.repeat(121));
      expect(within(dialog).getByText('Höchstens 120 Zeichen.')).toBeInTheDocument();
      await userEvent.click(button(dialog, 'Speichern'));
      expect(view.api.updateNode).not.toHaveBeenCalled();
      expect(view.planApi.setSteps).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000836: deletes a fiscal year after the confirmation, and says when the draft of its plan goes with it', async () => {
      const view = await setup({ tree: of([VSM, QSM]) });
      view.planApi.plan.mockImplementation((_budget: unknown, year: unknown) => (year === 'fy-26' ? of(plan()) : refuse(404, 'plan_not_found')));
      await openYears();
      expect(view.planApi.plan).toHaveBeenCalledWith('vsm', 'fy-25');
      await rowMenu('2025/26', 'Haushaltsjahr löschen');
      const plain = await screen.findByRole('dialog', { name: 'Haushaltsjahr löschen?' });
      expect(plain).toHaveTextContent('Das Haushaltsjahr 2025/26 wird gelöscht. Das lässt sich nicht rückgängig machen.');
      await userEvent.click(button(plain, 'Abbrechen'));
      expect(view.api.deleteFiscalYear).not.toHaveBeenCalled();
      await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' });
      await rowMenu('2026/27', 'Haushaltsjahr löschen');
      const withDraft = await screen.findByRole('dialog', { name: 'Haushaltsjahr löschen?' });
      expect(withDraft).toHaveTextContent('Das Haushaltsjahr 2026/27 wird mit dem Entwurf seines Haushaltsplans gelöscht.');
      await userEvent.click(button(withDraft, 'Löschen'));
      expect(view.api.deleteFiscalYear).toHaveBeenCalledWith('vsm', 'fy-26');
      expect(view.success).toHaveBeenLastCalledWith('Haushaltsjahr gelöscht.');
      expect(await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeInTheDocument();
    });

    it('§F/finance/budget/000836: a year with a decided plan offers no delete and names the cause', async () => {
      const view = await setup({ tree: of([VSM, QSM]) });
      view.planApi.plan.mockImplementation(() => of(plan([version({ state: 'in_force' })])));
      await openYears();
      await userEvent.click(screen.getByRole('button', { name: 'Aktionen: 2025/26' }));
      const item = await screen.findByRole('menuitem', { name: /Haushaltsjahr löschen/ });
      expect(item).toHaveAttribute('aria-disabled', 'true');
      expect(item).toHaveTextContent('beschlossen');
      await userEvent.click(item);
      expect(screen.queryByRole('dialog', { name: 'Haushaltsjahr löschen?' })).toBeNull();
    });

    it('§F/finance/budget/000836: a budget without a plan asks no plan, and a late answer for another budget changes nothing', async () => {
      const view = await setup();
      const late = new Subject<unknown>();
      view.planApi.plan.mockReturnValue(late);
      await openYears();
      expect(view.planApi.plan).toHaveBeenCalledTimes(2);
      await userEvent.click(button(await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' }), 'Fertig'));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' })).toBeNull());
      await openYears('QS-Mittel');
      expect(view.planApi.plan).toHaveBeenCalledTimes(2);
      late.next(plan());
      late.complete();
      view.fixture.detectChanges();
      await rowMenu('2026/27', 'Haushaltsjahr löschen');
      expect(await screen.findByRole('dialog', { name: 'Haushaltsjahr löschen?' })).toHaveTextContent('Das Haushaltsjahr 2026/27 wird gelöscht.');
    });

    it('§F/finance/budget/000836: names why a year cannot be deleted, and a closed year offers no delete', async () => {
      const view = await setup({ years: [closed, FY25] });
      await openYears();
      const del = async (code: string, status = 409) => {
        view.api.deleteFiscalYear.mockReturnValueOnce(refuse(status, code));
        await rowMenu('2025/26', 'Haushaltsjahr löschen');
        await userEvent.click(button(await screen.findByRole('dialog', { name: 'Haushaltsjahr löschen?' }), 'Löschen'));
        await screen.findByRole('dialog', { name: 'Haushaltsjahre: VS-Mittel' });
      };
      await del('fiscal_year_has_plan');
      expect(view.error).toHaveBeenLastCalledWith('Das Haushaltsjahr hat einen Haushaltsplan, der beschlossen oder in Arbeit ist. Es lässt sich deshalb weder ändern noch löschen.');
      await del('fiscal_year_has_bookings');
      expect(view.error).toHaveBeenLastCalledWith('Das Haushaltsjahr hat Buchungen. Lösche sie zuerst oder buche sie in ein anderes Jahr um.');
      await del('zzz');
      expect(view.error).toHaveBeenLastCalledWith('Das Haushaltsjahr hat Buchungen, Zuteilungen oder Anträge. Entferne sie zuerst.');
      await del('', 500);
      expect(view.error).toHaveBeenLastCalledWith('Haushaltsjahr konnte nicht gelöscht werden.');
      await userEvent.click(screen.getByRole('button', { name: 'Aktionen: 2024/25' }));
      const item = await screen.findByRole('menuitem', { name: 'Haushaltsjahr löschen' });
      expect(item).toHaveAttribute('aria-disabled', 'true');
      expect(item).toHaveAttribute('title', 'Das Haushaltsjahr ist abgeschlossen.');
    });

    it('runs no second write on a year while one runs', async () => {
      const view = await setup();
      await openYears();
      view.api.deleteFiscalYear.mockReturnValueOnce(new Subject<unknown>());
      await rowMenu('2025/26', 'Haushaltsjahr löschen');
      const dialog = await screen.findByRole('dialog', { name: 'Haushaltsjahr löschen?' });
      await userEvent.click(button(dialog, 'Löschen'));
      const busy = within(dialog).getAllByRole('button').at(-1) as HTMLButtonElement;
      expect(busy).toBeDisabled();
      await userEvent.click(busy);
      expect(view.api.deleteFiscalYear).toHaveBeenCalledTimes(1);
    });
  });
});
