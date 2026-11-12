import { of, throwError } from 'rxjs';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { render, screen } from '@testing-library/angular';
import { axe } from 'jest-axe';
import { ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { AdminApiService } from '../../admin/admin-api.service';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../budget-tree.api';
import { BudgetPlanApi, type BudgetPlan } from './budget-plan.api';
import { BudgetPlanComponent } from './budget-plan.component';
import { FY25, FY26, QSM, TOP, fy, line, node, plan, version } from './budget-plan.fixtures';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Inst = any;

function setViewport(wide: boolean, phone = false): void {
  window.matchMedia = ((query: string) => ({
    matches: (wide && query.includes('min-width: 1200px')) || (phone && query === '(max-width: 767.98px)'),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

const problem = (status: number, code = '') => ({ status, error: { code } });

interface Opts {
  tree?: readonly BudgetTreeNode[];
  years?: readonly FiscalYear[];
  /** The plan of each fiscal year; a year without an entry answers 404. */
  plans?: Readonly<Record<string, BudgetPlan>>;
  perms?: readonly string[];
  wide?: boolean;
  phone?: boolean;
  query?: Record<string, string>;
  /** The feature Abstimmungen is off. */
  votingOff?: boolean;
  /** The read of the Gremien fails. */
  gremienFail?: boolean;
}

async function setup(opts: Opts = {}) {
  TestBed.resetTestingModule();
  setViewport(opts.wide ?? true, opts.phone);
  const plans = opts.plans ?? { 'fy-26': plan() };
  const perms = opts.perms ?? ['budget.view', 'budget.structure'];
  const answer = (p: BudgetPlan = plan()) => of(p);
  const api = {
    plan: jest.fn((_top: string, fyId: string) => (plans[fyId] ? of(plans[fyId]) : throwError(() => problem(404, 'plan_not_found')))),
    createPlan: jest.fn(() => answer()),
    createNachtrag: jest.fn(() => answer()),
    setLine: jest.fn(() => answer()),
    deleteLine: jest.fn(() => answer()),
    setState: jest.fn(() => answer()),
    passNextStep: jest.fn(() => answer()),
    createStepVote: jest.fn(() => answer()),
  };
  const treeApi = {
    tree: jest.fn(() => of(opts.tree ?? [TOP, QSM])),
    listFiscalYears: jest.fn(() => of(opts.years ?? [FY25, FY26])),
    deleteNode: jest.fn(() => of(undefined)),
  };
  const gremien = jest.fn(() => (opts.gremienFail ? throwError(() => problem(500)) : of([{ id: 'g1', name: 'StuPa' }])));
  const view = await render(BudgetPlanComponent, {
    providers: [
      provideRouter([]),
      { provide: BudgetPlanApi, useValue: api },
      { provide: BudgetTreeApi, useValue: treeApi },
      { provide: AuthService, useValue: { can: (p: string) => perms.includes(p) } },
      { provide: FeatureService, useValue: { isOn: () => !opts.votingOff } },
      { provide: AdminApiService, useValue: { listGremienOptions: gremien } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(opts.query ?? {}) } } },
    ],
  });
  const router = TestBed.inject(Router);
  const toast = TestBed.inject(ToastService);
  const c = view.fixture.componentInstance as unknown as Inst;
  return { ...view, api, treeApi, gremien, router, toast, c };
}

/** The steps of a version: the Beschluss of the StuPa, then the Genehmigung without a Gremium. */
const STEPS = [
  { name: 'Beschluss', gremiumId: 'g1', gremiumName: 'StuPa', passedAt: null },
  { name: 'Genehmigung', gremiumId: null, passedAt: null },
];
const passed = (count: number) => STEPS.map((s, i) => (i < count ? { ...s, passedAt: `2026-01-${14 + i}T00:00:00Z` } : s));

const rowOf = (c: Inst, id: string) => c.rows().find((r: { id: string }) => r.id === id);

describe('BudgetPlanComponent', () => {
  const realMatchMedia = window.matchMedia;
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => {
    window.matchMedia = realMatchMedia;
  });

  describe('list and detail', () => {
    it('§000805: lists the Kostenstellen of the plan in two groups with their sums', async () => {
      const view = await setup();
      const groups = [...view.container.querySelectorAll('.bp__group')].map((g) => g.textContent?.replace(/\s+/g, ' ').trim());
      expect(groups).toEqual(['Einnahmen100 €', 'Ausgaben100 €']);
      const names = [...view.container.querySelectorAll('.bd__tree .tn__name')].map((n) => n.textContent);
      expect(names).toEqual(['VS-Mittel', 'Beiträge', 'Personal', 'Löhne', 'Zuschüsse']);
      expect(view.c.yearOptions().map((o: { label: string }) => o.label)).toEqual(['HHJ 2025/26', 'HHJ 2026/27']);
      expect(view.c.versionOptions()).toEqual([{ value: 'v0', label: 'Stammplan' }]);
      expect(view.c.fyId()).toBe('fy-26');
      expect(await axe(view.container)).toHaveNoViolations();
    });

    it('filters the list by the search text', async () => {
      const view = await setup();
      view.c.query.set('löh');
      expect(view.c.listRows().map((r: { id: string }) => r.id)).toEqual(['wages']);
      view.c.query.set('STAFF-W');
      expect(view.c.listRows().map((r: { id: string }) => r.id)).toEqual(['wages']);
      view.c.query.set('zzz');
      view.fixture.detectChanges();
      expect(screen.getByText('Keine Kostenstelle gefunden.')).toBeInTheDocument();
    });

    it('§000806 §000807: shows the steps, the sums and the balance', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      expect(view.c.steps().map((s: { label: string }) => s.label)).toEqual(['Entwurf', 'Beschluss', 'Genehmigung', 'In Kraft']);
      expect(view.c.stepAt()).toBe(0);
      expect(screen.getByText('Ausgeglichen')).toBeInTheDocument();
      expect(view.container.querySelector('app-note')).toBeNull();
    });

    it('§000811: warns for an unbalanced draft and disables the decision', async () => {
      const draft = version({ lines: [line('fees', '100'), line('grants', '130.50')] });
      const view = await setup({ plans: { 'fy-26': plan([draft]) } });
      expect(screen.getByText('Nicht ausgeglichen')).toBeInTheDocument();
      expect(screen.getByRole('status')).toHaveTextContent('Die Ausgaben liegen 30,50 € über den Einnahmen.');
      expect(view.c.primary()).toMatchObject({ id: 'in_force', disabled: true });
      const more = version({ lines: [line('fees', '200'), line('grants', '130')] });
      view.c.load.set({ kind: 'plan', plan: plan([more]) });
      view.fixture.detectChanges();
      expect(screen.getByRole('status')).toHaveTextContent('Die Einnahmen liegen 70 € über den Ausgaben.');
    });

    it('§000808: shows the columns of the year before and the change', async () => {
      const before = plan([version({ id: 'p', state: 'in_force', lines: [line('fees', '80'), line('grants', '30')] })], 'fy-25');
      const view = await setup({ plans: { 'fy-26': plan(), 'fy-25': before } });
      expect(view.c.columns().map((col: { label: string }) => col.label)).toEqual([
        'Kostenstelle',
        'Ansatz 2026/27',
        'Ansatz 2025/26',
        'Ist 2025/26',
        'Änderung',
      ]);
      expect(view.c.changeText(rowOf(view.c, 'fees'))).toBe('+20\u00a0€');
      expect(view.c.changeText(rowOf(view.c, 'grants'))).toBe('–');
      expect(view.c.changeText(rowOf(view.c, 'staff'))).toBe('–');
      expect(view.c.canCopy()).toBe(true);
      expect(view.c.money(null)).toBe('–');
      expect(view.c.money(1.5)).toBe('1,50\u00a0€');
    });

    it('has no columns of the year before in the first year', async () => {
      const view = await setup({ years: [FY26] });
      expect(view.c.columns().map((col: { key: string }) => col.key)).toEqual(['node', 'amount', 'change']);
    });

    it('§000809: shows a Nachtrag beside the version in force', async () => {
      const stamm = version({ state: 'in_force', inForceAt: '2026-03-01T00:00:00Z', steps: passed(2) });
      const nachtrag = version({ id: 'v1', number: 1, lines: [line('fees', '100'), line('grants', '45'), line('other', '15')] });
      const view = await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) } });
      expect(view.c.version().id).toBe('v1');
      expect(view.c.nachtrag()).toBe(true);
      expect(view.c.columns().map((col: { label: string }) => col.label)).toEqual(['Kostenstelle', '1. Nachtrag', 'In Kraft', 'Änderung']);
      expect(view.c.changeText(rowOf(view.c, 'grants'))).toBe('+15\u00a0€');
      expect(view.c.changeText(rowOf(view.c, 'other'))).toBe('+15\u00a0€');
      expect(view.c.versionOptions().map((o: { label: string }) => o.label)).toEqual(['1. Nachtrag', 'Stammplan']);
      view.c.pickVersion('v0');
      view.fixture.detectChanges();
      expect(view.c.nachtrag()).toBe(false);
      expect(view.c.stepAt()).toBe(4);
      expect(view.c.steps()[1].hint).toBe('14.01.2026');
      expect(view.c.primary()).toBeNull();
      expect(view.c.editable()).toBe(false);
    });

    it('§000815: shows one line with its child Kostenstellen', async () => {
      const view = await setup({ query: { costCentre: 'staff' } });
      expect(view.c.sel().id).toBe('staff');
      expect(screen.getByRole('heading', { level: 2, name: 'Personal' })).toBeInTheDocument();
      expect(view.c.childRows().map((r: { id: string }) => r.id)).toEqual(['wages']);
      expect(screen.getByText('Untergeordnete Kostenstellen')).toBeInTheDocument();
      expect(screen.getByText('Vermerke')).toBeInTheDocument();
      view.c.selectId('fees');
      view.fixture.detectChanges();
      expect(screen.queryByText('Vermerke')).toBeNull();
      expect(view.c.sideLabel(view.c.sel())).toBe('Einnahme');
      expect(view.c.sideLabel(rowOf(view.c, 'staff'))).toBe('Ausgabe');
    });

    it('shows a replaced version with a note', async () => {
      const old = version({ state: 'replaced' });
      const now = version({ id: 'v1', number: 1, state: 'in_force' });
      const view = await setup({ plans: { 'fy-26': plan([old, now]) } });
      view.c.pickVersion('v0');
      view.fixture.detectChanges();
      expect(screen.getByText('Diese Version ist durch einen Nachtrag ersetzt.')).toBeInTheDocument();
      expect(view.c.primary()).toBeNull();
      view.c.pickVersion('v1');
      expect(view.c.primary()).toMatchObject({ id: 'nachtrag', icon: 'fileplus' });
    });
  });

  describe('loading', () => {
    it('goes back to the budget when no Kostenstelle has the plan switch', async () => {
      setViewport(true);
      const navigate = jest.spyOn(Router.prototype, 'navigate').mockResolvedValue(true);
      await setup({ tree: [QSM] });
      expect(navigate).toHaveBeenCalledWith(['/budget'], { replaceUrl: true });
      navigate.mockRestore();
    });

    it('shows an error when the tree or the years fail', async () => {
      const view = await setup();
      view.treeApi.listFiscalYears.mockReturnValueOnce(throwError(() => problem(500)));
      view.c.pickTop('vsm');
      view.fixture.detectChanges();
      expect(view.c.error()).toBe(true);
      expect(view.container.querySelector('app-load-error')).not.toBeNull();
    });

    it('shows an error when the tree read fails', async () => {
      setViewport(true);
      const view = await render(BudgetPlanComponent, {
        providers: [
          provideRouter([]),
          { provide: BudgetPlanApi, useValue: {} },
          { provide: BudgetTreeApi, useValue: { tree: () => throwError(() => problem(500)) } },
          { provide: AuthService, useValue: { can: () => true } },
          { provide: AdminApiService, useValue: { listGremienOptions: () => of([]) } },
        ],
      });
      expect((view.fixture.componentInstance as unknown as Inst).error()).toBe(true);
    });

    it('takes the top level and the year of the URL', async () => {
      const second = node({ id: 'two', name: 'Zweiter', planEnabled: true });
      const view = await setup({ tree: [TOP, second], query: { budget: 'two', fy: 'fy-25' } });
      expect(view.c.topId()).toBe('two');
      expect(view.c.fyId()).toBe('fy-25');
      expect(view.c.topOptions().map((o: { label: string }) => o.label)).toEqual(['VS-Mittel', 'Zweiter']);
      expect(view.container.querySelectorAll('app-filter-select')).toHaveLength(2);
    });

    it('shows the plan read error with a retry', async () => {
      const view = await setup();
      view.api.plan.mockReturnValueOnce(throwError(() => problem(500)));
      view.c.pickYear('fy-26');
      view.fixture.detectChanges();
      expect(view.c.load().kind).toBe('error');
      expect(view.container.querySelector('.bd__sheetBody app-load-error')).not.toBeNull();
      view.c.reloadPlan();
      expect(view.c.load().kind).toBe('plan');
    });

    it('has nothing to load without a fiscal year', async () => {
      const view = await setup({ years: [] });
      expect(view.c.load().kind).toBe('none');
      expect(view.c.year()).toBeNull();
      expect(view.c.prevYear()).toBeNull();
      expect(view.c.rows()).toEqual([]);
      expect(view.c.addOptions()).toEqual([]);
    });

    it('offers to create the plan, also as a copy of the year before', async () => {
      const before = plan([version({ state: 'in_force' })], 'fy-25');
      const view = await setup({ plans: { 'fy-25': before } });
      expect(screen.getByText('Kein Haushaltsplan')).toBeInTheDocument();
      (await screen.findByRole('button', { name: 'Aus Vorjahr übernehmen' })).click();
      expect(view.api.createPlan).toHaveBeenCalledWith('vsm', 'fy-26', 'fy-25');
      expect(view.c.load().kind).toBe('plan');
      view.c.createPlan(false);
      expect(view.api.createPlan).toHaveBeenLastCalledWith('vsm', 'fy-26', null);
    });

    it('offers no create to a reader and in a closed year', async () => {
      const reader = await setup({ plans: {}, perms: ['budget.view'] });
      expect(reader.container.querySelector('.bp__none')).toBeNull();
      const closed = await setup({ plans: {}, years: [fy('fy-26', 2026, { closedAt: '2027-03-02T00:00:00Z' })] });
      expect(closed.container.querySelector('.bp__none')).toBeNull();
      expect(closed.c.yearOptions()[0].label).toContain('2026/27');
    });
  });

  describe('views', () => {
    it('§000804: goes to Bewirtschaftung with the year and the Kostenstelle', async () => {
      const view = await setup({ query: { costCentre: 'staff' } });
      const navigate = jest.spyOn(view.router, 'navigate').mockResolvedValue(true);
      view.c.setMode('plan');
      view.c.setMode(null);
      expect(navigate).not.toHaveBeenCalled();
      view.c.setMode('run');
      expect(navigate).toHaveBeenCalledWith(['/budget'], { queryParams: { budget: 'vsm', fy: 'fy-26', costCentre: 'staff' } });
    });

    it('§000810: a press on a row selects it beside the list and opens the sheet on a phone', async () => {
      const wide = await setup();
      wide.c.select(rowOf(wide.c, 'grants'));
      expect(wide.c.selId()).toBe('grants');
      expect(wide.c.tableFields()).toBe(true);
      const phone = await setup({ wide: false, phone: true });
      expect(phone.c.tableFields()).toBe(false);
      expect(phone.container.querySelector('.bp__field')).toBeNull();
      phone.c.select(rowOf(phone.c, 'grants'));
      phone.fixture.detectChanges();
      expect(phone.c.sheetRow().id).toBe('grants');
      expect(phone.c.selId()).toBe('');
      expect(phone.c.menu()[0].items[0]).toMatchObject({ id: 'in_force', disabledReason: null });
    });

    it('§000794 a Kostenstelle with children has no Ansatz field', async () => {
      const view = await setup();
      view.c.select(rowOf(view.c, 'grants'));
      view.fixture.detectChanges();
      expect(view.container.querySelector('.bp__ansatz')).not.toBeNull();
      view.c.select(rowOf(view.c, 'staff'));
      view.fixture.detectChanges();
      expect(rowOf(view.c, 'staff').hasChildren).toBe(true);
      expect(view.container.querySelector('.bp__ansatz')).toBeNull();
      expect(view.container.querySelector('[name=line-note-staff]')).not.toBeNull();
    });

    it('names the cause of a disabled decision in the phone menu', async () => {
      const draft = version({ lines: [line('fees', '1')] });
      const view = await setup({ wide: false, phone: true, plans: { 'fy-26': plan([draft]) } });
      expect(view.c.menu()[0].items[0].disabledReason).toBe('Der Plan ist nicht ausgeglichen.');
    });
  });

  describe('writes', () => {
    it('§000812: saves an amount when the person leaves the field', async () => {
      const view = await setup();
      const row = rowOf(view.c, 'grants');
      view.c.saveAmount(row);
      expect(view.api.setLine).not.toHaveBeenCalled();
      view.c.edit(row, 'amount', '');
      view.c.saveAmount(row);
      view.c.edit(row, 'amount', '30');
      view.c.saveAmount(row);
      expect(view.api.setLine).not.toHaveBeenCalled();
      view.c.edit(row, 'amount', '45.5');
      view.c.saveAmount(row);
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'grants', {
        amount: '45.5',
        note: null,
        transferable: false,
        coverable: false,
        blocked: '0.00',
      });
      view.c.saveAmount(row);
      expect(view.api.setLine).toHaveBeenCalledTimes(1);
    });

    it('§000816: saves the note and the marks of a line', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const row = rowOf(view.c, 'grants');
      view.c.saveNote(row, { target: { value: ' Text ' } });
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', expect.objectContaining({ note: 'Text' }));
      view.c.saveNote(row, { target: { value: ' ' } });
      view.c.saveLine(row, { transferable: true });
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', expect.objectContaining({ transferable: true }));
      view.c.saveLine(row, { coverable: true });
      view.c.edit(row, 'blocked', '5');
      view.c.saveAmount(row, 'blocked');
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', expect.objectContaining({ blocked: '5' }));
      expect(view.api.setLine).toHaveBeenCalledTimes(4);
    });

    it('§000793: writes nothing for a version that is not a draft or without the permission', async () => {
      const decided = await setup({ plans: { 'fy-26': plan([version({ state: 'in_progress' })]) } });
      decided.c.saveLine(rowOf(decided.c, 'grants'), { amount: '1' });
      expect(decided.api.setLine).not.toHaveBeenCalled();
      expect(decided.c.menu()[0].items.map((i: { id: string }) => i.id)).toEqual(['draft']);
      const reader = await setup({ perms: ['budget.view'] });
      expect(reader.c.primary()).toBeNull();
      expect(reader.c.menu()).toEqual([]);
      expect(reader.c.editable()).toBe(false);
    });

    it('§000792: passes the steps of the version one by one, then sets it in force', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      const success = jest.spyOn(view.toast, 'success');
      view.fixture.detectChanges();
      expect(view.c.primary()).toMatchObject({ id: 'step', label: 'Schritt abschließen: Beschluss', disabled: false });
      (view.container.querySelector('[data-testid=bp-primary] button, [data-testid=bp-primary]') as HTMLElement).click();
      expect(view.api.passNextStep).toHaveBeenLastCalledWith('v0');
      expect(success).toHaveBeenCalledWith('Schritt abgeschlossen.');
      view.c.load.set({ kind: 'plan', plan: plan([version({ state: 'in_progress', steps: passed(1) })]) });
      expect(view.c.primary()).toMatchObject({ id: 'step', label: 'Schritt abschließen: Genehmigung' });
      expect(view.c.stepAt()).toBe(2);
      expect(view.c.steps()[1].hint).toBe('14.01.2026');
      view.c.onAction('draft');
      expect(view.api.setState).toHaveBeenLastCalledWith('v0', 'draft');
      view.c.load.set({ kind: 'plan', plan: plan([version({ state: 'in_progress', steps: passed(2) })]) });
      expect(view.c.primary()).toMatchObject({ id: 'in_force' });
      view.c.onAction('in_force');
      expect(view.c.confirmInForce()).toBe(true);
      expect(view.api.setState).toHaveBeenCalledTimes(1);
      view.c.setInForce();
      expect(view.api.setState).toHaveBeenLastCalledWith('v0', 'in_force');
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
      expect(view.c.confirmInForce()).toBe(false);
    });

    it('§000811: an unbalanced draft cannot pass its first step', async () => {
      const draft = version({ steps: STEPS, lines: [line('fees', '100'), line('grants', '130')] });
      const view = await setup({ plans: { 'fy-26': plan([draft]) } });
      expect(view.c.primary()).toMatchObject({ id: 'step', disabled: true });
      view.c.load.set({ kind: 'plan', plan: plan([{ ...draft, state: 'in_progress' }]) });
      expect(view.c.primary()).toMatchObject({ id: 'step', disabled: false });
    });

    it('§000826: offers the vote of the Gremium of the next step', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      const success = jest.spyOn(view.toast, 'success');
      const ids = () => view.c.menu()[0].items.map((i: { id: string }) => i.id);
      expect(ids()).toEqual(['vote', 'new', 'add']);
      view.c.onAction('vote');
      expect(view.api.createStepVote).toHaveBeenCalledWith('v0');
      expect(success).toHaveBeenCalledWith('Abstimmung angelegt.');
      const withVote = (voteStatus: string) =>
        plan([version({ state: 'in_progress', steps: [{ ...STEPS[0], voteId: 'vote-1', voteStatus: voteStatus as 'open' }, STEPS[1]] })]);
      view.c.load.set({ kind: 'plan', plan: withVote('draft') });
      expect(ids()).toEqual(['openVote', 'draft']);
      expect(view.c.steps()[1].hint).toBe('Abstimmung vorbereitet');
      view.c.load.set({ kind: 'plan', plan: withVote('open') });
      expect(view.c.steps()[1].hint).toBe('Abstimmung läuft');
      view.c.load.set({ kind: 'plan', plan: withVote('closed') });
      expect(view.c.steps()[1].hint).toBe('Abgelehnt');
      expect(ids()).toEqual(['vote', 'openVote', 'draft']);
      view.c.load.set({ kind: 'plan', plan: withVote('cancelled') });
      expect(view.c.steps()[1].hint).toBeNull();
      const navigate = jest.spyOn(view.router, 'navigate').mockResolvedValue(true);
      view.c.onAction('openVote');
      expect(navigate).toHaveBeenCalledWith(['/voting', 'vote-1']);
    });

    it('§000826: offers no vote for a step without a Gremium or with Abstimmungen off', async () => {
      const second = await setup({ plans: { 'fy-26': plan([version({ state: 'in_progress', steps: passed(1) })]) } });
      expect(second.c.menu()[0].items.map((i: { id: string }) => i.id)).toEqual(['draft']);
      const off = await setup({ votingOff: true, plans: { 'fy-26': plan([version({ steps: [{ ...STEPS[0], voteId: 'v', voteStatus: 'open' }] })]) } });
      expect(off.c.menu()[0].items.map((i: { id: string }) => i.id)).toEqual(['new', 'add']);
    });

    it('§000799: creates a Nachtrag from the version in force', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ state: 'in_force' })]) } });
      expect(view.c.primary()).toMatchObject({ id: 'nachtrag' });
      view.c.onAction('nachtrag');
      expect(view.api.createNachtrag).toHaveBeenCalledWith('vsm', 'fy-26');
    });

    it('does nothing without a version', async () => {
      const view = await setup({ plans: {} });
      view.c.onAction('resolved');
      view.c.setInForce();
      view.c.addLine(new Event('submit'));
      view.c.saveLine({ id: 'x', amount: 1, note: '', transferable: false, coverable: false, blocked: 0 }, { amount: '2' });
      expect(view.api.setState).not.toHaveBeenCalled();
      expect(view.api.setLine).not.toHaveBeenCalled();
      expect(view.c.versionOptions()).toEqual([]);
    });

    it('§000819: takes a Kostenstelle into the draft and removes a line', async () => {
      const view = await setup({ query: { costCentre: 'wages' } });
      expect(view.c.addOptions().map((o: { value: string }) => o.value)).toEqual(['other', 'fees2']);
      expect(view.c.menu()[0].items.map((i: { id: string }) => i.id)).toEqual(['new', 'add', 'remove']);
      expect(view.c.menu()[1].items.map((i: { id: string }) => i.id)).toEqual(['delete']);
      view.c.onAction('add');
      expect(view.c.addOpen()).toBe(true);
      view.c.addLine(new Event('submit'));
      expect(view.api.setLine).not.toHaveBeenCalled();
      view.c.addId.set('other');
      view.c.addLine(new Event('submit'));
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'other', { amount: '0', note: null, transferable: false, coverable: false, blocked: '0' });
      expect(view.c.addOpen()).toBe(false);
      view.c.onAction('remove');
      expect(view.api.deleteLine).toHaveBeenCalledWith('v0', 'wages');
      expect(view.c.selId()).toBe('staff');
      view.c.selId.set('');
      view.c.onAction('remove');
      expect(view.api.deleteLine).toHaveBeenCalledTimes(1);
    });

    it('names the cause of a refused write and shows the saved plan again', async () => {
      const view = await setup();
      const error = jest.spyOn(view.toast, 'error');
      view.api.setLine.mockReturnValueOnce(throwError(() => problem(422, 'plan_blocked_above_amount')));
      view.c.saveLine(rowOf(view.c, 'staff'), { amount: '1' });
      expect(error).toHaveBeenCalledWith('Der gesperrte Betrag liegt über dem Ansatz.');
      expect(view.api.plan).toHaveBeenCalledTimes(4);
      expect(view.c.busy()).toBe(false);
    });

    it('§000829: creates a Kostenstelle in the draft and shows the plan with its line', async () => {
      const view = await setup();
      expect(view.c.parents().map((o: { value: string }) => o.value)).toEqual(['vsm', 'fees', 'staff', 'wages', 'grants']);
      view.c.onAction('new');
      expect(view.c.createOpen()).toBe(true);
      const withLine = plan([version({ lines: [line('fees', '100'), line('grants', '100')] })]);
      view.c.onCreated({ id: null, plan: withLine });
      expect(view.c.createOpen()).toBe(false);
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
      expect(view.c.plan()).toBe(withLine);
    });

    it('§000831: reads the tree again after a setting of a Kostenstelle changed', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      expect(view.gremien).toHaveBeenCalledTimes(1);
      expect(view.c.gremiumOptions()).toEqual([{ value: 'g1', label: 'StuPa' }]);
      expect(view.c.nodeOf('fees').name).toBe('Beiträge');
      expect(view.c.nodeOf('nope')).toBeNull();
      expect(view.c.sided(view.c.nodeOf('fees'))).toBe(true);
      expect(view.c.sided(view.c.nodeOf('wages'))).toBe(false);
      const before = view.c.plan();
      view.c.reloadTree();
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
      expect(view.c.plan()).toBe(before);
      view.treeApi.tree.mockReturnValueOnce(throwError(() => problem(500)));
      view.c.reloadTree();
      expect(view.api.plan).toHaveBeenCalledTimes(4);
    });

    it('has no Gremien to choose when their read fails, and reads none without the permission', async () => {
      const failed = await setup({ gremienFail: true });
      expect(failed.c.gremiumOptions()).toEqual([]);
      const reader = await setup({ perms: ['budget.view'] });
      expect(reader.gremien).not.toHaveBeenCalled();
      expect(reader.c.parents()).toHaveLength(5);
    });

    it('§000832: deletes a Kostenstelle after the confirmation', async () => {
      const view = await setup({ query: { costCentre: 'wages' } });
      const success = jest.spyOn(view.toast, 'success');
      view.c.deleteNode();
      expect(view.treeApi.deleteNode).not.toHaveBeenCalled();
      view.c.onAction('delete');
      expect(view.c.deleteRow().id).toBe('wages');
      view.c.deleteNode();
      expect(view.treeApi.deleteNode).toHaveBeenCalledWith('wages');
      expect(success).toHaveBeenCalledWith('Kostenstelle gelöscht.');
      expect(view.c.selId()).toBe('staff');
      expect(view.c.deleteRow()).toBeNull();
      view.c.onAction('delete');
      view.c.deleteNode();
      expect(view.c.selId()).toBe('');
    });

    it('§000832: names the cause of a refused delete', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const error = jest.spyOn(view.toast, 'error');
      view.treeApi.deleteNode.mockReturnValueOnce(throwError(() => problem(409, 'budget_has_bookings')));
      view.c.onAction('delete');
      view.c.deleteNode();
      expect(error).toHaveBeenCalledWith(view.c.i18n.translate('budget.cc.error.hasBookings'));
      expect(view.c.selId()).toBe('grants');
      expect(view.c.busy()).toBe(false);
    });

    it('does nothing for an action without a version', async () => {
      const view = await setup({ plans: {} });
      view.c.onAction('step');
      expect(view.api.passNextStep).not.toHaveBeenCalled();
      expect(view.c.stepAt()).toBe(0);
      expect(view.c.next()).toBeNull();
    });
  });
});
