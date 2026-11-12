import { type Observable, of, throwError } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { axe } from 'jest-axe';
import { ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { BudgetTreeApi, type BudgetTreeNode } from '../../budget/budget-tree.api';
import { BudgetPlanApi } from '../../budget/plan/budget-plan.api';
import { FY25, FY26, QSM, TOP, fy } from '../../budget/plan/budget-plan.fixtures';
import { AdminApiService } from '../admin-api.service';
import { AdminBudgetsComponent } from './admin-budgets.component';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Inst = any;

const problem = (status: number, code = '', detail = '') => ({ status, error: { code, detail } });
const refuse = (status: number, code = '', detail = ''): Observable<never> => throwError(() => problem(status, code, detail));
const submit = () => ({ preventDefault: jest.fn() }) as unknown as Event;
const STEPS = [
  { name: 'Beschluss', gremiumId: 'g1' },
  { name: 'Genehmigung', gremiumId: null },
];

interface Opts {
  tree?: Observable<readonly BudgetTreeNode[]>;
  perms?: readonly string[];
  gremienFail?: boolean;
}

async function setup(opts: Opts = {}) {
  TestBed.resetTestingModule();
  const perms = opts.perms ?? ['budget.structure'];
  const ok = () => of({});
  const api = {
    tree: jest.fn(() => opts.tree ?? of([TOP, QSM])),
    createNode: jest.fn(ok),
    updateNode: jest.fn(ok),
    deleteNode: jest.fn(ok),
    listFiscalYears: jest.fn(() => of([FY25, FY26])),
    createFiscalYear: jest.fn(ok),
    updateFiscalYear: jest.fn(ok),
    setFiscalYearClosed: jest.fn(ok),
    deleteFiscalYear: jest.fn(ok),
  };
  const planApi = {
    steps: jest.fn(() => of({ budgetId: 'vsm', steps: STEPS })),
    setSteps: jest.fn(ok),
    setPlanSwitch: jest.fn(ok),
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
  return {
    ...view,
    api,
    planApi,
    toast,
    success: jest.spyOn(toast, 'success'),
    error: jest.spyOn(toast, 'error'),
    c: view.fixture.componentInstance as unknown as Inst,
  };
}

describe('AdminBudgetsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  describe('list', () => {
    it('§000828: lists only the top-level budgets, each with its start and its plan switch', async () => {
      const view = await setup();
      expect(view.c.budgets().map((b: BudgetTreeNode) => b.id)).toEqual(['vsm', 'qsm']);
      expect(screen.getByText('VS-Mittel')).toBeInTheDocument();
      expect(screen.queryByText('Beiträge')).toBeNull();
      expect(screen.getAllByText('01.03.')).toHaveLength(2);
      expect(screen.getByText('Mit Haushaltsplan')).toBeInTheDocument();
      expect(screen.getByText('Ohne Haushaltsplan')).toBeInTheDocument();
      expect(view.c.columns().map((col: { key: string }) => col.key)).toEqual(['node', 'start', 'plan', 'actions']);
      expect(view.c.rowId(TOP)).toBe('vsm');
      expect(view.c.asBudget(TOP)).toBe(TOP);
      expect(view.c.gremiumOptions()).toEqual([{ value: 'g1', label: 'StuPa' }]);
      expect(await axe(view.container)).toHaveNoViolations();
    });

    it('shows the load error, and no Gremien when their read fails', async () => {
      const view = await setup({ tree: refuse(500), gremienFail: true });
      expect(view.c.loadError()).toBe(true);
      expect(view.c.loading()).toBe(false);
      expect(view.c.gremiumOptions()).toEqual([]);
    });

    it('shows the empty state without a budget', async () => {
      const view = await setup({ tree: of([]) });
      expect(view.container.querySelector('app-empty-state')).not.toBeNull();
    });

    it('opens the fiscal years or the delete dialog from the menu of a row', async () => {
      const view = await setup();
      expect(view.c.rowMenu().map((s: { items: { id: string }[] }) => s.items[0].id)).toEqual(['years', 'delete']);
      view.c.onRowMenu(TOP, { id: 'years', label: '' });
      expect(view.c.fyOpen()).toBe(true);
      view.c.deleteBlocked.set('x');
      view.c.onRowMenu(TOP, { id: 'delete', label: '' });
      expect(view.c.deleteTarget()).toBe(TOP);
      expect(view.c.deleteBlocked()).toBeNull();
    });
  });

  describe('create', () => {
    it('creates a budget with the start of its fiscal year', async () => {
      const view = await setup();
      view.c.openTop();
      expect(view.c.topOpen()).toBe(true);
      view.c.createTop(submit());
      expect(view.api.createNode).not.toHaveBeenCalled();
      view.c.patchTop('key', ' QS ');
      view.c.patchTop('name', ' QS-Mittel ');
      view.c.patchTopCutoff('day', '40');
      view.c.patchTopCutoff('month', '10');
      view.c.createTop(submit());
      expect(view.api.createNode).toHaveBeenCalledWith({ key: 'QS', name: 'QS-Mittel', fiscalStartDay: 28, fiscalStartMonth: 10 });
      expect(view.success).toHaveBeenCalledWith('Budget angelegt.');
      expect(view.c.topOpen()).toBe(false);
      expect(view.api.tree).toHaveBeenCalledTimes(2);
    });

    it('names the cause of a refused create', async () => {
      const view = await setup();
      view.api.createNode.mockReturnValueOnce(refuse(409, 'budget_key_exists'));
      view.c.patchTop('key', 'VS');
      view.c.patchTop('name', 'X');
      view.c.createTop(submit());
      expect(view.error).toHaveBeenCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
    });
  });

  describe('edit', () => {
    it('§000827: opens the form of a budget with its steps', async () => {
      const view = await setup();
      view.c.openEdit({ ...TOP, color: ' #112233 ', viewGremiumId: 'g1', decisionGremiumId: 'g1' });
      view.fixture.detectChanges();
      expect(view.c.form()).toMatchObject({
        key: 'vsm',
        name: 'VS-Mittel',
        colour: '#112233',
        active: true,
        viewGremium: 'g1',
        decisionGremium: 'g1',
        day: 1,
        month: 3,
        plan: true,
        steps: [
          { name: 'Beschluss', gremiumId: 'g1' },
          { name: 'Genehmigung', gremiumId: '' },
        ],
      });
      expect(view.c.formValid()).toBe(true);
      expect(view.c.canAddStep()).toBe(true);
      view.c.closeEdit();
      expect(view.c.form()).toBeNull();
      expect(view.c.formValid()).toBe(false);
      expect(view.c.canAddStep()).toBe(true);
      view.c.patch({ name: 'x' });
      view.c.addStep();
      expect(view.c.form()).toBeNull();
    });

    it('opens the form without steps when their read fails or answers for another budget', async () => {
      const view = await setup();
      view.planApi.steps.mockReturnValueOnce(refuse(500));
      view.c.openEdit(QSM);
      expect(view.c.form()).toMatchObject({ plan: false, colour: '', viewGremium: '', decisionGremium: '', steps: [] });
      const late: { next: (v: unknown) => void } = { next: () => undefined };
      view.planApi.steps.mockReturnValueOnce({ subscribe: (o: { next: (v: unknown) => void }) => (late.next = o.next) } as never);
      view.c.openEdit(TOP);
      view.c.openEdit(QSM);
      late.next({ budgetId: 'vsm', steps: [{ name: 'Alt', gremiumId: null }] });
      expect(view.c.form().steps.map((s: { name: string }) => s.name)).toEqual(['Beschluss', 'Genehmigung']);
    });

    it('§000827: adds, changes, moves and removes the steps', async () => {
      const view = await setup();
      view.c.openEdit(TOP);
      const names = () => view.c.form().steps.map((s: { name: string }) => s.name);
      view.c.addStep();
      expect(view.c.formValid()).toBe(false);
      view.c.patchStep(2, { name: 'Anzeige' });
      view.c.moveStep(2, -1);
      expect(names()).toEqual(['Beschluss', 'Anzeige', 'Genehmigung']);
      view.c.removeStep(0);
      expect(names()).toEqual(['Anzeige', 'Genehmigung']);
      view.c.patch({ steps: Array.from({ length: 10 }, () => ({ name: 'S', gremiumId: '' })) });
      expect(view.c.canAddStep()).toBe(false);
      view.c.patch({ plan: false, steps: [{ name: '', gremiumId: '' }] });
      expect(view.c.formValid()).toBe(true);
    });

    it('checks the key, the name and the colour of the form', async () => {
      const view = await setup();
      view.c.openEdit(TOP);
      view.c.patch({ key: ' ' });
      expect(view.c.formValid()).toBe(false);
      view.c.patch({ key: 'VS', name: '' });
      expect(view.c.formValid()).toBe(false);
      view.c.patch({ name: 'VS', colour: '#12' });
      expect(view.c.formValid()).toBe(false);
      view.c.saveEdit();
      expect(view.api.updateNode).not.toHaveBeenCalled();
    });

    it('saves only the settings when the plan switch and the steps did not change', async () => {
      const view = await setup();
      view.c.saveEdit();
      view.c.openEdit(TOP);
      view.c.patch({ name: ' VS ' });
      view.c.saveEdit();
      expect(view.api.updateNode).toHaveBeenCalledWith('vsm', { key: 'vsm', name: 'VS', color: '', active: true, viewGremiumId: null });
      expect(view.planApi.setPlanSwitch).not.toHaveBeenCalled();
      expect(view.planApi.setSteps).not.toHaveBeenCalled();
      expect(view.success).toHaveBeenCalledWith('Gespeichert.');
      expect(view.c.editNode()).toBeNull();
      expect(view.api.tree).toHaveBeenCalledTimes(2);
    });

    it('§000827: saves the changed Gremium, the start, the plan switch and the steps in this order', async () => {
      const view = await setup();
      view.planApi.steps.mockReturnValueOnce(of({ budgetId: 'qsm', steps: [] }));
      view.c.openEdit(QSM);
      view.c.patch({ plan: true, decisionGremium: 'g1', viewGremium: 'g1' });
      view.c.patchCutoff('day', '15');
      view.c.patchCutoff('month', '10');
      view.c.addStep();
      view.c.patchStep(0, { name: ' Beschluss ', gremiumId: 'g1' });
      view.c.saveEdit();
      expect(view.api.updateNode).toHaveBeenCalledWith('qsm', expect.objectContaining({ viewGremiumId: 'g1', decisionGremiumId: 'g1', fiscalStartDay: 15, fiscalStartMonth: 10 }));
      expect(view.planApi.setPlanSwitch).toHaveBeenCalledWith('qsm', true);
      expect(view.planApi.setSteps).toHaveBeenCalledWith('qsm', [{ name: 'Beschluss', gremiumId: 'g1' }]);
      expect(view.planApi.setPlanSwitch.mock.invocationCallOrder[0]).toBeLessThan(view.planApi.setSteps.mock.invocationCallOrder[0]);
    });

    it('removes the deciding Gremium and sends no steps for a budget without a plan', async () => {
      const view = await setup();
      view.c.openEdit({ ...TOP, decisionGremiumId: 'g1' });
      view.c.patch({ plan: false, decisionGremium: '' });
      view.c.removeStep(0);
      view.c.saveEdit();
      expect(view.api.updateNode).toHaveBeenCalledWith('vsm', expect.objectContaining({ decisionGremiumId: null }));
      expect(view.planApi.setPlanSwitch).toHaveBeenCalledWith('vsm', false);
      expect(view.planApi.setSteps).not.toHaveBeenCalled();
    });

    it('names the cause of a refused save, reads the list again and sends nothing while a save runs', async () => {
      const view = await setup();
      view.c.openEdit(TOP);
      view.api.updateNode.mockReturnValueOnce(refuse(409, 'budget_key_exists'));
      view.c.saveEdit();
      expect(view.error).toHaveBeenCalledWith('Diesen Schlüssel gibt es an dieser Stelle schon.');
      expect(view.c.editNode()).not.toBeNull();
      expect(view.c.busy()).toBe(false);
      view.api.updateNode.mockReturnValueOnce(refuse(500));
      view.c.saveEdit();
      expect(view.error).toHaveBeenLastCalledWith(view.c.i18n.translate('admin.budgets.error.save'));
      view.c.busy.set(true);
      view.c.saveEdit();
      expect(view.api.updateNode).toHaveBeenCalledTimes(2);
    });
  });

  describe('delete', () => {
    it('deletes a budget after the confirmation', async () => {
      const view = await setup();
      view.c.deleteBudget();
      expect(view.api.deleteNode).not.toHaveBeenCalled();
      view.c.deleteTarget.set(QSM);
      view.c.deleteBudget();
      expect(view.api.deleteNode).toHaveBeenCalledWith('qsm');
      expect(view.success).toHaveBeenCalledWith('Budget gelöscht.');
      expect(view.c.deleteTarget()).toBeNull();
    });

    it('names the reason of a refused delete in the dialog', async () => {
      const view = await setup();
      view.api.deleteNode.mockReturnValueOnce(refuse(409, 'budget_has_children'));
      view.c.deleteTarget.set(TOP);
      view.c.deleteBudget();
      expect(view.c.deleteBlocked()).toBe(view.c.i18n.translate('budget.cc.error.hasChildren'));
      expect(view.c.deleteTarget()).toBe(TOP);
      view.c.closeDelete();
      expect(view.c.deleteBlocked()).toBeNull();
    });
  });

  describe('fiscal years', () => {
    const closed = fy('fy-24', 2024, { closedAt: '2025-03-01T00:00:00Z' });

    it('lists the fiscal years of a budget, the newest first', async () => {
      const view = await setup();
      view.c.openFy(TOP);
      expect(view.c.fiscalYears().map((y: { id: string }) => y.id)).toEqual(['fy-26', 'fy-25']);
      expect(view.c.fyBudgetLabel()).toBe('vsm – VS-Mittel');
      expect(view.c.fyColumns().map((col: { key: string }) => col.key)).toEqual(['display', 'active', 'actions']);
      expect(view.c.fyRowId(FY25)).toBe('fy-25');
      expect(view.c.asYear(FY25)).toBe(FY25);
      view.api.listFiscalYears.mockReturnValueOnce(refuse(500));
      view.c.openFy(TOP);
      expect(view.c.fiscalYears()).toEqual([]);
    });

    it('has no label and no actions column without a budget or the permission', async () => {
      const view = await setup({ perms: [] });
      expect(view.c.fyBudgetLabel()).toBe('');
      expect(view.c.fyColumns().map((col: { key: string }) => col.key)).toEqual(['display', 'active']);
      view.c.createFiscalYear(submit());
      view.c.saveFyEdit();
      view.c.doFyClose();
      view.c.doFyDelete();
      expect(view.api.createFiscalYear).not.toHaveBeenCalled();
      expect(view.api.listFiscalYears).not.toHaveBeenCalled();
    });

    it('keeps the years of the budget that is open when a late answer arrives', async () => {
      const view = await setup();
      const late: { next: (v: unknown) => void } = { next: () => undefined };
      view.api.listFiscalYears.mockReturnValueOnce({ subscribe: (o: { next: (v: unknown) => void }) => (late.next = o.next) } as never);
      view.c.openFy(TOP);
      view.c.fyBudget.set(QSM);
      late.next([FY25]);
      expect(view.c.fiscalYears()).toEqual([]);
    });

    it('creates a fiscal year', async () => {
      const view = await setup();
      view.c.openFy(TOP);
      view.c.patchFyYear('2027');
      view.c.createFiscalYear(submit());
      expect(view.api.createFiscalYear).toHaveBeenCalledWith('vsm', { year: 2027 });
      expect(view.api.listFiscalYears).toHaveBeenCalledTimes(2);
      view.c.patchFyYear('x');
      expect(view.c.newFyYear()).toBe(new Date().getFullYear());
      view.api.createFiscalYear.mockReturnValueOnce(refuse(422));
      view.c.createFiscalYear(submit());
      expect(view.error).toHaveBeenCalledWith(view.c.i18n.translate('budget.tree.toast.fyFailed'));
    });

    it('edits the year and the active flag of a fiscal year', async () => {
      const view = await setup();
      view.c.openFy(TOP);
      view.c.openFyEdit(FY25);
      expect(view.c.fyOpen()).toBe(false);
      view.c.patchFyEditYear('2030');
      view.c.fyEditActive.set(false);
      view.c.saveFyEdit();
      expect(view.api.updateFiscalYear).toHaveBeenCalledWith('vsm', 'fy-25', { year: 2030, active: false });
      expect(view.c.fyEdit()).toBeNull();
      expect(view.c.fyOpen()).toBe(true);
      view.c.patchFyEditYear('');
      expect(view.c.fyEditYear()).toBe(new Date().getFullYear());
      view.c.openFyEdit(FY25);
      view.api.updateFiscalYear.mockReturnValueOnce(refuse(422));
      view.c.saveFyEdit();
      expect(view.error).toHaveBeenLastCalledWith(view.c.i18n.translate('budget.tree.toast.fyDuplicate'));
      view.api.updateFiscalYear.mockReturnValueOnce(refuse(500));
      view.c.saveFyEdit();
      expect(view.error).toHaveBeenLastCalledWith(view.c.i18n.translate('budget.tree.toast.fyFailed'));
    });

    it('closes an open year and reopens a closed one', async () => {
      const view = await setup();
      view.c.openFy(TOP);
      expect(view.c.fyMenu(FY25).map((s: { items: { id: string }[] }) => s.items[0].id)).toEqual(['close', 'delete']);
      expect(view.c.fyMenu(closed)[0].items[0].id).toBe('reopen');
      expect(view.c.fyMenu(closed)[1].items[0].disabledReason).toBeTruthy();
      expect(view.c.fyMenu(FY25)[1].items[0].disabledReason).toBeNull();
      view.c.onFyMenu(FY25, { id: 'close', label: '' });
      expect(view.c.fyOpen()).toBe(false);
      view.c.doFyClose();
      expect(view.api.setFiscalYearClosed).toHaveBeenLastCalledWith('vsm', 'fy-25', true);
      view.c.onFyMenu(closed, { id: 'reopen', label: '' });
      view.c.doFyClose();
      expect(view.api.setFiscalYearClosed).toHaveBeenLastCalledWith('vsm', 'fy-24', false);
      view.c.onFyMenu(FY25, { id: 'close', label: '' });
      view.api.setFiscalYearClosed.mockReturnValueOnce(refuse(500));
      view.c.doFyClose();
      expect(view.error).toHaveBeenCalledWith(view.c.i18n.translate('budget.tree.toast.failed'));
    });

    it('deletes a fiscal year, and names why a year cannot be deleted', async () => {
      const view = await setup();
      view.c.openFy(TOP);
      view.c.onFyMenu(FY25, { id: 'delete', label: '' });
      expect(view.c.fyDelete()).toBe(FY25);
      view.api.deleteFiscalYear.mockReturnValueOnce(refuse(409, '', 'has bookings'));
      view.c.doFyDelete();
      expect(view.c.fyDeleteBlocked()).toBe(view.c.i18n.translate('budget.tree.fyBlocked.bookings'));
      view.api.deleteFiscalYear.mockReturnValueOnce(refuse(500));
      view.c.doFyDelete();
      expect(view.error).toHaveBeenCalledWith(view.c.i18n.translate('budget.tree.toast.fyDeleteFailed'));
      view.c.doFyDelete();
      expect(view.api.deleteFiscalYear).toHaveBeenLastCalledWith('vsm', 'fy-25');
      expect(view.c.fyDelete()).toBeNull();
      expect(view.c.fyDeleteBlocked()).toBeNull();
      expect(view.c.fyOpen()).toBe(true);
    });
  });
});
