import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { Location } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { AdminApiService } from '../../admin/admin-api.service';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../budget-tree.api';
import { CostCentreCreateComponent } from '../cost-centre/cost-centre-create.component';
import { CostCentreSettingsComponent } from '../cost-centre/cost-centre-settings.component';
import { BudgetPlanApi, type BudgetPlan, type PlanStep } from './budget-plan.api';
import { BudgetPlanComponent } from './budget-plan.component';
import { FY25, FY26, QSM, TOP, fy, line, node, plan, version } from './budget-plan.fixtures';

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
  /** The read of the plan of a version fails. */
  versionFail?: boolean;
}

async function setup(opts: Opts = {}) {
  TestBed.resetTestingModule();
  setViewport(opts.wide ?? true, opts.phone);
  const plans = opts.plans ?? { 'fy-26': plan() };
  const perms = opts.perms ?? ['budget.view', 'budget.structure'];
  const answer = (p: BudgetPlan = plans['fy-26'] ?? plan()) => of(p);
  const api = {
    plan: jest.fn((_top: string, fyId: string) => (plans[fyId] ? of(plans[fyId]) : throwError(() => problem(404, 'plan_not_found')))),
    planOfVersion: jest.fn((_id: string) => (opts.versionFail ? throwError(() => problem(404)) : of(plans['fy-25'] ?? plan()))),
    createPlan: jest.fn((..._args: unknown[]) => of(plan())),
    createNachtrag: jest.fn((..._args: unknown[]) => answer()),
    setLine: jest.fn((..._args: unknown[]) => answer()),
    deleteLine: jest.fn((..._args: unknown[]) => answer()),
    setState: jest.fn((..._args: unknown[]) => answer()),
    deleteVersion: jest.fn((..._args: unknown[]) => of(undefined)),
    passNextStep: jest.fn((..._args: unknown[]) => answer()),
    createStepVote: jest.fn((..._args: unknown[]) => answer()),
  };
  const treeApi = {
    tree: jest.fn(() => of(opts.tree ?? [TOP, QSM])),
    listFiscalYears: jest.fn((_id: string) => of(opts.years ?? [FY25, FY26])),
    deleteNode: jest.fn((_id: string) => of(undefined)),
  };
  const gremien = jest.fn(() => (opts.gremienFail ? throwError(() => problem(500)) : of([{ id: 'g1', name: 'StuPa' }])));
  const params = new BehaviorSubject(convertToParamMap(opts.query ?? {}));
  const view = await render(BudgetPlanComponent, {
    providers: [
      provideRouter([]),
      { provide: BudgetPlanApi, useValue: api },
      { provide: BudgetTreeApi, useValue: treeApi },
      { provide: AuthService, useValue: { can: (p: string) => perms.includes(p) } },
      { provide: FeatureService, useValue: { isOn: () => !opts.votingOff } },
      { provide: AdminApiService, useValue: { listGremienOptions: gremien } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: params.value }, queryParamMap: params } },
    ],
  });
  const router = TestBed.inject(Router);
  const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
  const back = jest.spyOn(TestBed.inject(Location), 'back').mockImplementation(() => params.next(convertToParamMap({})));
  const toast = TestBed.inject(ToastService);
  const success = jest.spyOn(toast, 'success');
  const error = jest.spyOn(toast, 'error');
  return { ...view, api, treeApi, gremien, router, navigate, success, error, params, back };
}

type View = Awaited<ReturnType<typeof setup>>;

/** The steps of a version: the Beschluss of the StuPa, then the Genehmigung without a Gremium. */
const STEPS: readonly PlanStep[] = [
  { name: 'Beschluss', gremiumId: 'g1', gremiumName: 'StuPa', passedAt: null },
  { name: 'Genehmigung', gremiumId: null, passedAt: null },
];
const passed = (count: number) => STEPS.map((s, i) => (i < count ? { ...s, passedAt: `2026-01-${14 + i}T00:00:00Z` } : s));
const withVote = (voteStatus: PlanStep['voteStatus'], state: 'draft' | 'in_progress' = 'in_progress') =>
  plan([version({ state, steps: [{ ...STEPS[0], voteId: 'vote-1', voteStatus }, STEPS[1]] })]);

const text = (el: Element | null | undefined) => el?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
const texts = (view: View, selector: string) => [...view.container.querySelectorAll(selector)].map(text);
const input = (view: View, name: string) => view.container.querySelector<HTMLInputElement>(`[name="${name}"]`) as HTMLInputElement;
const primary = () => within(screen.getByTestId('bp-primary')).getByRole('button');
const treeRow = (view: View, name: string) =>
  within(view.container.querySelector('.bd__tree') as HTMLElement).getByRole('button', { name: new RegExp(`^${name}`) });
const tableRow = (name: string) => screen.getAllByText(name).find((el) => el.classList.contains('bp__name')) as HTMLElement;

/** Open the ⋮ menu of the head, or of `scope`, and return the names of its items. */
async function openMenu(scope: HTMLElement = document.body): Promise<string[]> {
  await userEvent.click(within(scope).getByRole('button', { name: 'Weitere Aktionen' }));
  return (await screen.findAllByRole('menuitem')).map((i) => text(i.querySelector('.rm__label')));
}
/** Open the ⋮ menu and press one of its items. */
async function choose(name: string, scope?: HTMLElement): Promise<void> {
  await openMenu(scope);
  await userEvent.click(screen.getByRole('menuitem', { name }));
}
/** Press a button of the confirmation that is open. */
async function answerDialog(title: string, button: string): Promise<void> {
  const dialog = await screen.findByRole('dialog', { name: title });
  await userEvent.click(within(dialog).getByRole('button', { name: button }));
}
/** Type an amount into a field and leave the field. */
async function typeAmount(field: HTMLInputElement, value: string, leave = '{Tab}'): Promise<void> {
  await userEvent.clear(field);
  if (value) await userEvent.type(field, value);
  if (leave === '{Tab}') await userEvent.tab();
  else await userEvent.keyboard(leave);
}
/** Choose an option of a chip of the page. */
async function pickChip(chip: string | RegExp, option: string): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: chip }));
  await userEvent.click(await screen.findByRole('option', { name: option }));
}

describe('BudgetPlanComponent', () => {
  const realMatchMedia = window.matchMedia;
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
  afterEach(() => {
    jest.useRealTimers();
    window.matchMedia = realMatchMedia;
  });

  describe('list and detail', () => {
    it('§F/finance/budget/000805: lists the Kostenstellen of the plan in two groups with their sums', async () => {
      const view = await setup();
      expect(texts(view, '.bp__group')).toEqual(['Einnahmen100 €', 'Ausgaben100 €']);
      expect(texts(view, '.bd__tree .tn__name')).toEqual(['VS-Mittel', 'Beiträge', 'Personal', 'Löhne', 'Zuschüsse']);
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2026/27');
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Stammplan');
      expect(screen.queryByRole('button', { name: /^Budget/ })).toBeNull();
      expect(view.container.querySelector('.bd__tree [title]')).toBeNull();
      expect(await axe(view.container)).toHaveNoViolations();
    });

    it('§F/finance/budget/000140: opens the fiscal year that holds today', async () => {
      const view = await setup({ years: [FY25, FY26, fy('fy-27', 2027)], plans: { 'fy-26': plan() } });
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2026/27');
      expect(view.api.plan).toHaveBeenCalledWith('vsm', 'fy-26');
    });

    it('filters the list by the search text', async () => {
      const view = await setup();
      const search = screen.getByPlaceholderText('Kostenstellen durchsuchen');
      await userEvent.type(search, 'löh');
      expect(texts(view, '.bd__tree .tn__name')).toEqual(['VS-Mittel', 'Löhne']);
      await userEvent.clear(search);
      await userEvent.type(search, 'STAFF-W');
      expect(texts(view, '.bd__tree .tn__name')).toEqual(['VS-Mittel', 'Löhne']);
      await userEvent.clear(search);
      await userEvent.type(search, 'zzz');
      expect(screen.getByText('Keine Kostenstelle gefunden.')).toBeInTheDocument();
    });

    it('marks an inactive Kostenstelle in the list and in the table', async () => {
      const top = { ...TOP, children: TOP.children.map((c) => (c.id === 'grants' ? { ...c, active: false } : c)) };
      await setup({ tree: [top] });
      expect(screen.getAllByText('inaktiv')).toHaveLength(2);
    });

    it('§F/finance/budget/000806 §F/finance/budget/000807: shows the steps under each other, the sums and the balance', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      const stepper = view.container.querySelector('.bp__stepper') as HTMLElement;
      for (const label of ['Entwurf', 'Beschluss', 'Genehmigung', 'In Kraft']) expect(within(stepper).getByText(label)).toBeInTheDocument();
      expect(screen.getByText('Ausgeglichen')).toBeInTheDocument();
      expect(view.container.querySelector('app-note')).toBeNull();
    });

    it('§F/finance/budget/000806: shows the date of a passed step and of the decision', async () => {
      const done = version({ state: 'in_force', inForceAt: '2026-03-01T00:00:00Z', steps: passed(2) });
      const view = await setup({ plans: { 'fy-26': plan([done]) } });
      const stepper = text(view.container.querySelector('.bp__stepper'));
      expect(stepper).toContain('14.01.2026');
      expect(stepper).toContain('15.01.2026');
      expect(stepper).toContain('01.03.2026');
    });

    it('§F/finance/budget/000811: warns for an unbalanced draft and names the cause on the disabled action', async () => {
      const more = version({ lines: [line('fees', '100'), line('grants', '130.50')] });
      await setup({ plans: { 'fy-26': plan([more]) } });
      expect(screen.getByText('Nicht ausgeglichen')).toBeInTheDocument();
      expect(screen.getByRole('status')).toHaveTextContent('Die Ausgaben liegen 30,50 € über den Einnahmen.');
      expect(primary()).toBeDisabled();
      expect(primary()).toHaveAttribute('title', 'Der Plan ist nicht ausgeglichen.');
      const less = version({ lines: [line('fees', '200'), line('grants', '130')] });
      await setup({ plans: { 'fy-26': plan([less]) } });
      expect(screen.getByRole('status')).toHaveTextContent('Die Einnahmen liegen 70 € über den Ausgaben.');
    });

    it('§F/finance/budget/000811: an empty draft cannot come into force', async () => {
      await setup({ plans: { 'fy-26': plan([version({ lines: [] })]) } });
      expect(primary()).toBeDisabled();
      expect(primary()).toHaveAttribute('title', 'Der Plan hat keine Zeile.');
    });

    it('§F/finance/budget/000811: an empty draft passes no step and takes no vote', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS, lines: [] })]) } });
      expect(primary()).toBeDisabled();
      expect(primary()).toHaveAttribute('title', 'Der Plan hat keine Zeile.');
      await openMenu();
      const item = screen.getByRole('menuitem', { name: 'Abstimmung anlegen' });
      expect(item).toHaveAttribute('aria-disabled', 'true');
      expect(item).toHaveAttribute('title', 'Der Plan hat keine Zeile.');
      expect(view.api.createStepVote).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000808: shows the columns of the year before and the change', async () => {
      const before = plan([version({ id: 'p', state: 'in_force', lines: [line('fees', '80'), line('grants', '30')] })], 'fy-25');
      const view = await setup({ plans: { 'fy-26': plan(), 'fy-25': before } });
      const income = view.container.querySelectorAll('app-data-table')[0] as HTMLElement;
      expect(within(income).getAllByRole('columnheader').map(text)).toEqual([
        'Kostenstelle',
        'Ansatz 2026/27',
        'Ansatz 2025/26',
        'Ist 2025/26',
        'Änderung',
      ]);
      const cells = within(income).getAllByRole('row').at(-1) as HTMLElement;
      expect(text(cells)).toContain('80 €');
      expect(text(cells)).toContain('+20 €');
    });

    it('has no columns of the year before in the first year', async () => {
      const view = await setup({ years: [FY26] });
      const income = view.container.querySelectorAll('app-data-table')[0] as HTMLElement;
      expect(within(income).getAllByRole('columnheader').map(text)).toEqual(['Kostenstelle', 'Ansatz 2026/27', 'Änderung']);
    });

    it('§F/finance/budget/000809: shows a Nachtrag beside the version before it', async () => {
      const stamm = version({ state: 'in_force', inForceAt: '2026-03-01T00:00:00Z', steps: passed(2) });
      const nachtrag = version({ id: 'v1', number: 1, lines: [line('fees', '100'), line('grants', '45'), line('other', '15')] });
      const view = await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) } });
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: 1. Nachtrag');
      const expense = view.container.querySelectorAll('app-data-table')[1] as HTMLElement;
      expect(within(expense).getAllByRole('columnheader').map(text)).toEqual([
        'Kostenstelle',
        'Ansatz 1. Nachtrag',
        'Ansatz Stammplan',
        'Änderung',
      ]);
      expect(text(expense)).toContain('+15 €');
      await pickChip(/^Version/, 'Stammplan');
      expect(view.navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: { budget: 'vsm', fy: 'fy-26', version: 0, costCentre: null } }),
      );
      expect(screen.queryByTestId('bp-primary')).toBeNull();
      expect(input(view, 'amount-grants')).toBeNull();
      await userEvent.click(treeRow(view, 'Zuschüsse'));
      expect(screen.getAllByText('Ansatz 2026/27').length).toBeGreaterThan(0);
    });

    it('§F/finance/budget/000809: the detail of a line of a Nachtrag shows the Ansatz of the version before', async () => {
      const stamm = version({ state: 'in_force' });
      const nachtrag = version({ id: 'v1', number: 1, lines: [line('fees', '100'), line('grants', '45')] });
      const view = await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) }, query: { costCentre: 'grants' } });
      const figures = text(view.container.querySelector('.bd__figs'));
      expect(figures).toContain('Ansatz 1. Nachtrag45 €');
      expect(figures).toContain('Ansatz Stammplan30 €');
      expect(figures).toContain('Änderung+15 €');
    });

    it('§F/finance/budget/000815: shows one line with its child Kostenstellen', async () => {
      const view = await setup({ query: { costCentre: 'staff' } });
      expect(screen.getByRole('heading', { level: 2, name: 'Personal' })).toBeInTheDocument();
      expect(screen.getByText('Untergeordnete Kostenstellen')).toBeInTheDocument();
      expect(screen.getByText('Vermerke')).toBeInTheDocument();
      expect(text(view.container.querySelector('.bd__line'))).toContain('Ausgabe');
      await userEvent.click(treeRow(view, 'Beiträge'));
      expect(screen.getByRole('heading', { level: 2, name: 'Beiträge' })).toBeInTheDocument();
      expect(screen.queryByText('Vermerke')).toBeNull();
      expect(text(view.container.querySelector('.bd__line'))).toContain('Einnahme');
      await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { level: 2 })));
      await userEvent.click(treeRow(view, 'VS-Mittel'));
      expect(screen.getByRole('heading', { level: 2, name: 'VS-Mittel' })).toBeInTheDocument();
    });

    it('§F/finance/budget/000808: the detail of a line shows the year before', async () => {
      const before = plan([version({ id: 'p', state: 'in_force', lines: [line('fees', '80'), line('grants', '30')] })], 'fy-25');
      const view = await setup({ plans: { 'fy-26': plan(), 'fy-25': before }, query: { costCentre: 'fees' } });
      const figures = text(view.container.querySelector('.bd__figs'));
      expect(figures).toContain('Ansatz 2025/2680 €');
      expect(figures).toContain('Ist 2025/2690 €');
    });

    it('shows a replaced version with a note and offers a Nachtrag only for the version in force', async () => {
      const old = version({ state: 'replaced' });
      const now = version({ id: 'v1', number: 1, state: 'in_force' });
      await setup({ plans: { 'fy-26': plan([old, now]) } });
      expect(primary()).toHaveAccessibleName('Nachtrag anlegen');
      await pickChip(/^Version/, 'Stammplan');
      expect(screen.getByText('Diese Version ist durch einen Nachtrag ersetzt.')).toBeInTheDocument();
      expect(screen.queryByTestId('bp-primary')).toBeNull();
    });
  });

  describe('loading', () => {
    it('goes back to the budget when no Kostenstelle has the plan switch', async () => {
      const navigate = jest.spyOn(Router.prototype, 'navigate').mockResolvedValue(true);
      await setup({ tree: [QSM] });
      expect(navigate).toHaveBeenCalledWith(['/budget'], { replaceUrl: true });
      navigate.mockRestore();
    });

    it('shows an error when the read of the years fails', async () => {
      const second = node({ id: 'two', name: 'Zweiter', planEnabled: true });
      const view = await setup({ tree: [TOP, second] });
      view.treeApi.listFiscalYears.mockReturnValueOnce(throwError(() => problem(500)));
      await pickChip(/^Budget/, 'Zweiter');
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
      expect(view.container.querySelector('app-load-error')).not.toBeNull();
    });

    it('takes the budget and the year of the URL and names the budget on its chip', async () => {
      const second = node({ id: 'two', name: 'Zweiter', planEnabled: true });
      const view = await setup({ tree: [TOP, second], query: { budget: 'two', fy: 'fy-25' } });
      expect(screen.getByRole('button', { name: /^Budget/ })).toHaveTextContent('Budget: Zweiter');
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2025/26');
      expect(view.api.plan).toHaveBeenCalledWith('two', 'fy-25');
      await pickChip(/^Budget/, 'VS-Mittel');
      expect(view.treeApi.listFiscalYears).toHaveBeenLastCalledWith('vsm');
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      expect(view.api.plan).toHaveBeenLastCalledWith('vsm', 'fy-25');
    });

    it('§F/finance/budget/000809: opens the version that the URL names', async () => {
      const stamm = version({ state: 'in_force' });
      const nachtrag = version({ id: 'v1', number: 1 });
      await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) }, query: { version: '0' } });
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Stammplan');
      await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) }, query: { version: 'x' } });
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: 1. Nachtrag');
    });

    it('§F/finance/budget/000826: opens the plan of the version that a vote names', async () => {
      const old = plan([version({ id: 'old', state: 'replaced' }), version({ id: 'now', number: 1, state: 'in_force' })], 'fy-25');
      const view = await setup({ plans: { 'fy-25': old, 'fy-26': plan() }, query: { planVersion: 'old' } });
      expect(view.api.planOfVersion).toHaveBeenCalledWith('old');
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2025/26');
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Stammplan');
      const gone = await setup({ plans: { 'fy-25': old, 'fy-26': plan() }, query: { planVersion: 'zzz' } });
      expect(gone.api.planOfVersion).toHaveBeenCalledWith('zzz');
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: 1. Nachtrag');
      const failed = await setup({ versionFail: true, query: { planVersion: 'old' } });
      expect(failed.api.plan).toHaveBeenCalledWith('vsm', 'fy-26');
    });

    it('shows the plan read error with a retry', async () => {
      const view = await setup({ tree: [TOP, node({ id: 'two', name: 'Zweiter', planEnabled: true })] });
      view.api.plan.mockReturnValueOnce(throwError(() => problem(500)));
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      expect(view.container.querySelector('.bd__sheetBody app-load-error')).not.toBeNull();
      (view.fixture.debugElement.query(By.directive(LoadErrorComponent)).componentInstance as LoadErrorComponent).retry.emit();
      view.fixture.detectChanges();
      expect(view.container.querySelector('.bd__sheetBody app-load-error')).toBeNull();
      expect(screen.getByText('Kein Haushaltsplan')).toBeInTheDocument();
    });

    it('has nothing to plan without a fiscal year', async () => {
      const view = await setup({ years: [] });
      expect(screen.getByText('Kein Haushaltsjahr')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Haushaltsplan anlegen' })).toBeNull();
      expect(view.api.plan).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000796: creates the plan of a year, empty with the floating button', async () => {
      const view = await setup({ plans: {} });
      expect(screen.getByText('Kein Haushaltsplan')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Aus Vorjahr übernehmen' })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Haushaltsplan anlegen' }));
      expect(view.api.createPlan).toHaveBeenCalledWith('vsm', 'fy-26', null);
      expect(view.success).toHaveBeenCalledWith('Haushaltsplan angelegt.');
      expect(screen.getByText('Ausgeglichen')).toBeInTheDocument();
    });

    it('§F/finance/budget/000837: creates the plan as a copy of the year before', async () => {
      const before = plan([version({ state: 'in_force' })], 'fy-25');
      const view = await setup({ plans: { 'fy-25': before } });
      await userEvent.click(screen.getByRole('button', { name: 'Aus Vorjahr übernehmen' }));
      expect(view.api.createPlan).toHaveBeenCalledWith('vsm', 'fy-26', 'fy-25');
    });

    it('offers no create to a reader and in a closed year', async () => {
      const before = plan([version({ state: 'in_force' })], 'fy-25');
      await setup({ plans: { 'fy-25': before }, perms: ['budget.view'] });
      expect(screen.getByText('Kein Haushaltsplan')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Haushaltsplan anlegen' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Aus Vorjahr übernehmen' })).toBeNull();
      await setup({ plans: { 'fy-25': before }, years: [FY25, fy('fy-26', 2026, { closedAt: '2027-03-02T00:00:00Z' })], query: { fy: 'fy-26' } });
      expect(screen.queryByRole('button', { name: 'Haushaltsplan anlegen' })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Aus Vorjahr übernehmen' })).toBeNull();
    });

    it('§F/finance/budget/000801: a plan of a closed year is read only', async () => {
      const view = await setup({ years: [fy('fy-26', 2026, { closedAt: '2027-03-02T00:00:00Z' })] });
      expect(screen.queryByTestId('bp-primary')).toBeNull();
      expect(input(view, 'amount-grants')).toBeNull();
      expect(screen.queryByRole('button', { name: 'Kostenstelle anlegen' })).toBeNull();
    });
  });

  describe('views', () => {
    it('§F/finance/budget/000804: goes to Bewirtschaftung with the year and the Kostenstelle', async () => {
      const view = await setup({ query: { costCentre: 'staff' } });
      view.navigate.mockClear();
      await userEvent.click(screen.getByRole('radio', { name: 'Planung' }));
      expect(view.navigate).not.toHaveBeenCalled();
      await userEvent.click(screen.getByRole('radio', { name: 'Bewirtschaftung' }));
      expect(view.navigate).toHaveBeenCalledWith(['/budget'], { queryParams: { budget: 'vsm', fy: 'fy-26', costCentre: 'staff' } });
    });

    it('§F/finance/budget/000810: a press on a table row shows the line beside the list', async () => {
      const view = await setup();
      await userEvent.click(tableRow('Zuschüsse'));
      expect(screen.getByRole('heading', { level: 2, name: 'Zuschüsse' })).toBeInTheDocument();
      expect(view.navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: { budget: 'vsm', fy: 'fy-26', version: null, costCentre: 'grants' } }),
      );
      expect(screen.queryByRole('dialog', { name: 'Zuschüsse' })).toBeNull();
    });

    it('§F/finance/budget/000810: a phone edits a line in the bottom sheet, with the actions of its Kostenstelle', async () => {
      const view = await setup({ wide: false, phone: true });
      expect(view.container.querySelector('.bp__field')).toBeNull();
      expect(screen.getByRole('button', { name: /^Budget/ })).toHaveTextContent('Budget: VS-Mittel');
      await userEvent.click(tableRow('Zuschüsse'));
      const sheet = await screen.findByRole('dialog', { name: 'Zuschüsse' });
      expect(text(sheet)).toContain('GRANTS · Ausgabe');
      await typeAmount(input(view, 'line-amount-grants'), '45,5');
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'grants', { amount: '45.5' });
      expect(await openMenu(sheet)).toEqual(['Zeile entfernen', 'Kostenstelle löschen']);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Zeile entfernen' }));
      await answerDialog('Zeile entfernen?', 'Entfernen');
      expect(view.api.deleteLine).toHaveBeenCalledWith('v0', 'grants');
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Zuschüsse' })).toBeNull());
    });

    it('§F/finance/budget/000810: closing the bottom sheet deselects the Kostenstelle', async () => {
      const view = await setup({ wide: false, phone: true, query: { costCentre: 'grants' } });
      const sheet = await screen.findByRole('dialog', { name: 'Zuschüsse' });
      await userEvent.click(within(sheet).getAllByRole('button', { name: /schließen/i })[0]);
      expect(view.navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: expect.objectContaining({ costCentre: null }) }),
      );
    });

    it('a phone filters the tables by the search and has the next step first in the menu', async () => {
      const draft = version({ lines: [line('fees', '1'), line('grants', '2')] });
      const view = await setup({ wide: false, phone: true, plans: { 'fy-26': plan([draft]) } });
      expect(screen.queryByTestId('bp-primary')).toBeNull();
      const items = await openMenu();
      expect(items[0]).toBe('In Kraft setzen');
      const first = screen.getByRole('menuitem', { name: 'In Kraft setzen' });
      expect(first).toHaveAttribute('aria-disabled', 'true');
      expect(first).toHaveAttribute('title', 'Der Plan ist nicht ausgeglichen.');
      await userEvent.keyboard('{Escape}');
      await userEvent.type(screen.getByPlaceholderText('Kostenstellen durchsuchen'), 'zusch');
      expect(texts(view, '.bp__name')).toEqual(['Zuschüsse']);
    });

    it('§F/finance/budget/000794: a Kostenstelle with children has no Ansatz field', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      expect(input(view, 'line-amount-grants')).not.toBeNull();
      expect(input(view, 'amount-staff')).toBeNull();
      await userEvent.click(treeRow(view, 'Personal'));
      expect(input(view, 'line-amount-staff')).toBeNull();
      expect(input(view, 'line-note-staff')).not.toBeNull();
    });
  });

  describe('fields', () => {
    it('§F/finance/budget/000812: saves only the amount when the person leaves the field', async () => {
      const view = await setup();
      const field = input(view, 'amount-grants');
      await userEvent.click(field);
      await userEvent.tab();
      expect(view.api.setLine).not.toHaveBeenCalled();
      await typeAmount(field, '30');
      expect(view.api.setLine).not.toHaveBeenCalled();
      await typeAmount(field, '45,5');
      expect(view.api.setLine).toHaveBeenCalledTimes(1);
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'grants', { amount: '45.5' });
      expect(view.success).toHaveBeenCalledWith('Gespeichert.');
      expect(screen.queryByRole('heading', { level: 2, name: 'Zuschüsse' })).toBeNull();
    });

    it('§F/finance/budget/000812: Enter saves the amount and keeps the plan open', async () => {
      const view = await setup();
      await typeAmount(input(view, 'amount-grants'), '12', '{Enter}');
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'grants', { amount: '12' });
      expect(screen.getByRole('heading', { level: 2, name: 'VS-Mittel' })).toBeInTheDocument();
    });

    it('§F/finance/budget/000812: an empty field saves nothing and shows the saved amount again', async () => {
      const view = await setup();
      const field = input(view, 'amount-grants');
      await typeAmount(field, '');
      expect(view.api.setLine).not.toHaveBeenCalled();
      await waitFor(() => expect(input(view, 'amount-grants').value).toBe('30,00'));
    });

    it('§F/finance/budget/000812: refuses a negative amount and an amount that is too large', async () => {
      const view = await setup();
      await typeAmount(input(view, 'amount-grants'), '-5');
      expect(view.error).toHaveBeenLastCalledWith('Der Betrag darf nicht negativ sein.');
      await typeAmount(input(view, 'amount-grants'), '99999999999');
      expect(view.error).toHaveBeenLastCalledWith('Der Betrag ist zu groß.');
      expect(view.api.setLine).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000812: a second field saves while the first save runs', async () => {
      const view = await setup();
      const pending = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(pending);
      await typeAmount(input(view, 'amount-grants'), '31');
      await typeAmount(input(view, 'amount-fees'), '31');
      expect(view.api.setLine).toHaveBeenCalledTimes(2);
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'fees', { amount: '31' });
    });

    it('§F/finance/budget/000816: saves the note and each mark of a line on its own', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const noted = plan([version({ lines: [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '30', { note: 'Text' })] })]);
      view.api.setLine.mockReturnValueOnce(of(noted));
      const note = input(view, 'line-note-grants');
      await userEvent.type(note, ' Text ');
      await userEvent.tab();
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', { note: 'Text' });
      await userEvent.click(input(view, 'line-note-grants'));
      await userEvent.tab();
      expect(view.api.setLine).toHaveBeenCalledTimes(1);
      await userEvent.click(screen.getByRole('switch', { name: 'Übertragbar' }));
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', { transferable: true });
      await userEvent.click(screen.getByRole('switch', { name: 'Deckungsfähig' }));
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', { coverable: true });
      await typeAmount(input(view, 'line-blocked-grants'), '5');
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', { blocked: '5' });
      expect(view.api.setLine).toHaveBeenCalledTimes(4);
    });

    it('§F/finance/budget/000816: an emptied note saves as no note', async () => {
      const draft = version({ lines: [line('fees', '30'), line('grants', '30', { note: 'Alt' })] });
      const view = await setup({ plans: { 'fy-26': plan([draft]) }, query: { costCentre: 'grants' } });
      await userEvent.clear(input(view, 'line-note-grants'));
      await userEvent.tab();
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', { note: null });
    });

    it('§F/finance/budget/000816: shows the marks of a line in the table', async () => {
      const draft = version({
        lines: [line('fees', '30'), line('grants', '30', { transferable: true, coverable: true, blocked: '5' })],
      });
      const view = await setup({ plans: { 'fy-26': plan([draft]) } });
      expect(text(view.container.querySelectorAll('app-data-table')[1])).toContain('ÜbertragbarDeckungsfähigGesperrt: 5 €');
    });

    it('§F/finance/budget/000793: a version in progress and a reader have no field to write', async () => {
      const decided = await setup({ plans: { 'fy-26': plan([version({ state: 'in_progress' })]) }, query: { costCentre: 'grants' } });
      await waitFor(() => expect(input(decided, 'line-amount-grants')).toBeDisabled());
      expect(input(decided, 'line-note-grants')).toBeDisabled();
      expect(screen.getByRole('switch', { name: 'Übertragbar' })).toBeDisabled();
      expect(screen.queryByRole('button', { name: 'Kostenstelle anlegen' })).toBeNull();
      const reader = await setup({ perms: ['budget.view'] });
      expect(screen.queryByTestId('bp-primary')).toBeNull();
      expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).toBeNull();
      expect(input(reader, 'amount-grants')).toBeNull();
      expect(reader.gremien).not.toHaveBeenCalled();
    });

    it('names the cause of a refused write and shows the saved plan again', async () => {
      const view = await setup();
      view.api.setLine.mockReturnValueOnce(throwError(() => problem(422, 'plan_blocked_above_amount')));
      const reads = view.api.plan.mock.calls.length;
      await typeAmount(input(view, 'amount-grants'), '1');
      expect(view.error).toHaveBeenCalledWith('Der gesperrte Betrag liegt über dem Ansatz.');
      expect(view.api.plan.mock.calls.length).toBeGreaterThan(reads);
      view.api.setLine.mockReturnValueOnce(throwError(() => problem(500, 'zzz')));
      await typeAmount(input(view, 'amount-grants'), '2');
      expect(view.error).toHaveBeenLastCalledWith('Die Änderung konnte nicht gespeichert werden.');
    });
  });

  describe('steps', () => {
    it('§F/finance/budget/000792 §F/finance/budget/000825 §F/finance/budget/000840 §F/finance/budget/000841: passes a step by hand after the confirmation', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      expect(primary()).toHaveAccessibleName('Schritt abschließen: Beschluss');
      await userEvent.click(primary());
      await answerDialog('Schritt abschließen?', 'Abbrechen');
      expect(view.api.passNextStep).not.toHaveBeenCalled();
      await userEvent.click(primary());
      expect(await screen.findByText('Der Schritt „Beschluss“ gilt danach als abgeschlossen.')).toBeInTheDocument();
      await answerDialog('Schritt abschließen?', 'Abschließen');
      expect(view.api.passNextStep).toHaveBeenCalledWith('v0', 0);
      expect(view.success).toHaveBeenCalledWith('Schritt abgeschlossen.');
    });

    it('§F/finance/budget/000811: an unbalanced draft cannot pass its first step, a version in progress can pass its next', async () => {
      const draft = version({ steps: STEPS, lines: [line('fees', '100'), line('grants', '130')] });
      await setup({ plans: { 'fy-26': plan([draft]) } });
      expect(primary()).toBeDisabled();
      await setup({ plans: { 'fy-26': plan([{ ...draft, state: 'in_progress', steps: passed(1) }]) } });
      expect(primary()).toHaveAccessibleName('Schritt abschließen: Genehmigung');
      expect(primary()).toBeEnabled();
    });

    it('§F/finance/budget/000792 §F/finance/budget/000840: sets the version in force after its last step and reads the allocations again', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ state: 'in_progress', steps: passed(2) })]) } });
      expect(primary()).toHaveAccessibleName('In Kraft setzen');
      await userEvent.click(primary());
      await answerDialog('Version in Kraft setzen?', 'In Kraft setzen');
      expect(view.api.setState).toHaveBeenCalledWith('v0', 'in_force');
      expect(view.success).toHaveBeenCalledWith('Die Version ist in Kraft.');
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
    });

    it('§F/finance/budget/000792 §F/finance/budget/000840: moves a version in progress back to the draft after the confirmation', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ state: 'in_progress', steps: passed(1) })]) } });
      expect(await openMenu()).toEqual(['Zurück in den Entwurf']);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Zurück in den Entwurf' }));
      expect(await screen.findByText(/Eine laufende Abstimmung wird abgebrochen/)).toBeInTheDocument();
      await answerDialog('Zurück in den Entwurf?', 'Zurück in den Entwurf');
      expect(view.api.setState).toHaveBeenCalledWith('v0', 'draft');
      expect(view.success).toHaveBeenCalledWith('Die Version ist wieder ein Entwurf.');
    });

    it('§F/finance/budget/000835 §F/finance/budget/000840: deletes the draft after the confirmation and reads the year again', async () => {
      const view = await setup();
      const reads = view.api.plan.mock.calls.length;
      await choose('Entwurf löschen');
      await answerDialog('Entwurf löschen?', 'Löschen');
      expect(view.api.deleteVersion).toHaveBeenCalledWith('v0');
      expect(view.success).toHaveBeenCalledWith('Entwurf gelöscht.');
      expect(view.api.plan.mock.calls.length).toBeGreaterThan(reads);
    });

    it('§F/finance/budget/000835: names the cause when the draft cannot be deleted', async () => {
      const view = await setup();
      view.api.deleteVersion.mockReturnValueOnce(throwError(() => problem(409, 'plan_version_locked')));
      await choose('Entwurf löschen');
      await answerDialog('Entwurf löschen?', 'Löschen');
      expect(view.error).toHaveBeenCalledWith('Nur ein Entwurf kann geändert werden.');
    });

    it('§F/finance/budget/000826 §F/finance/budget/000838: creates the vote of the Gremium of the next step from the menu', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      expect(await openMenu()).toEqual(['Abstimmung anlegen', 'Zeile hinzufügen', 'Entwurf löschen']);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Abstimmung anlegen' }));
      expect(view.api.createStepVote).toHaveBeenCalledWith('v0');
      expect(view.success).toHaveBeenCalledWith('Abstimmung angelegt.');
    });

    it('§F/finance/budget/000826: an unbalanced draft names the cause on the vote', async () => {
      const draft = version({ steps: STEPS, lines: [line('fees', '100'), line('grants', '130')] });
      const view = await setup({ plans: { 'fy-26': plan([draft]) } });
      await openMenu();
      const item = screen.getByRole('menuitem', { name: 'Abstimmung anlegen' });
      expect(item).toHaveAttribute('aria-disabled', 'true');
      await userEvent.click(item);
      expect(view.api.createStepVote).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000826 §F/finance/budget/000838: a vote that waits for its result is the next action and opens the vote', async () => {
      const prepared = await setup({ plans: { 'fy-26': withVote('draft') } });
      expect(text(prepared.container.querySelector('.bp__stepper'))).toContain('Abstimmung geplant');
      expect(primary()).toHaveAccessibleName('Zur Abstimmung');
      expect(await openMenu()).toEqual(['Zurück in den Entwurf']);
      const open = await setup({ plans: { 'fy-26': withVote('open') } });
      expect(text(open.container.querySelector('.bp__stepper'))).toContain('Abstimmung läuft');
      await userEvent.click(primary());
      expect(open.navigate).toHaveBeenCalledWith(['/voting', 'vote-1']);
    });

    it('§F/finance/budget/000826: after a refused vote the next action is a new vote, and the menu opens the old one', async () => {
      const view = await setup({ plans: { 'fy-26': withVote('closed') } });
      expect(text(view.container.querySelector('.bp__stepper'))).toContain('Abgelehnt');
      expect(primary()).toHaveAccessibleName('Abstimmung anlegen');
      expect(await openMenu()).toEqual(['Zur Abstimmung', 'Zurück in den Entwurf']);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Zur Abstimmung' }));
      expect(view.navigate).toHaveBeenCalledWith(['/voting', 'vote-1']);
      await userEvent.click(primary());
      expect(view.api.createStepVote).toHaveBeenCalledWith('v0');
    });

    it('§F/finance/budget/000826: a cancelled vote leaves the step to pass by hand or by a new vote', async () => {
      const view = await setup({ plans: { 'fy-26': withVote('cancelled') } });
      expect(text(view.container.querySelector('.bp__stepper'))).not.toContain('Abstimmung');
      expect(primary()).toHaveAccessibleName('Schritt abschließen: Beschluss');
      expect(await openMenu()).toEqual(['Abstimmung anlegen', 'Zur Abstimmung', 'Zurück in den Entwurf']);
    });

    it('§F/finance/budget/000826: offers no vote for a step without a Gremium or with Abstimmungen off', async () => {
      await setup({ plans: { 'fy-26': plan([version({ state: 'in_progress', steps: passed(1) })]) } });
      expect(await openMenu()).toEqual(['Zurück in den Entwurf']);
      await userEvent.keyboard('{Escape}');
      await setup({ votingOff: true, plans: { 'fy-26': withVote('open', 'draft') } });
      expect(primary()).toHaveAccessibleName('Schritt abschließen: Beschluss');
      expect(await openMenu()).toEqual(['Zeile hinzufügen', 'Entwurf löschen']);
    });

    it('§F/finance/budget/000799: creates a Nachtrag from the version in force', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ state: 'in_force' })]) } });
      await userEvent.click(primary());
      expect(view.api.createNachtrag).toHaveBeenCalledWith('vsm', 'fy-26');
      expect(view.success).toHaveBeenCalledWith('Nachtrag angelegt.');
    });

    it('takes no second action while a write runs', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ state: 'in_force' })]) } });
      const pending = new Subject<BudgetPlan>();
      view.api.createNachtrag.mockReturnValueOnce(pending);
      await userEvent.click(primary());
      expect(primary()).toBeDisabled();
      fireEvent.click(primary());
      expect(view.api.createNachtrag).toHaveBeenCalledTimes(1);
      pending.next(plan());
      await waitFor(() => expect(primary()).toBeEnabled());
    });
  });

  describe('Kostenstellen', () => {
    it('§F/finance/budget/000819: takes a Kostenstelle into the draft with the picker', async () => {
      const view = await setup();
      await choose('Zeile hinzufügen');
      const dialog = await screen.findByRole('dialog', { name: 'Zeile hinzufügen' });
      const add = within(dialog).getByRole('button', { name: 'Zeile hinzufügen' });
      expect(add).toBeDisabled();
      await userEvent.click(dialog.querySelector('[data-cc-trigger]') as HTMLElement);
      const options = (await screen.findAllByRole('option')).map(text);
      expect(options.some((o) => o.includes('Sonstige Einnahmen'))).toBe(true);
      expect(options.some((o) => o.includes('Honorare'))).toBe(true);
      expect(options.some((o) => o.includes('Zuschüsse'))).toBe(false);
      expect(options.some((o) => o.includes('VS-Mittel'))).toBe(false);
      await userEvent.click(await screen.findByRole('option', { name: /Sonstige Einnahmen/ }));
      await userEvent.click(add);
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'other', {});
      expect(view.success).toHaveBeenCalledWith('Zeile hinzugefügt.');
    });

    it('§F/finance/budget/000819: the add dialog closes without a write', async () => {
      const view = await setup();
      await choose('Zeile hinzufügen');
      const dialog = await screen.findByRole('dialog', { name: 'Zeile hinzufügen' });
      fireEvent.submit(dialog.querySelector('form') as HTMLFormElement);
      await userEvent.click(within(dialog).getByRole('button', { name: 'Abbrechen' }));
      expect(view.api.setLine).not.toHaveBeenCalled();
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Zeile hinzufügen' })).toBeNull());
    });

    it('§F/finance/budget/000819 §F/finance/budget/000840: removes a line after the confirmation and shows its parent', async () => {
      const view = await setup({ query: { costCentre: 'wages' } });
      expect(await openMenu()).toEqual(['Zeile entfernen', 'Kostenstelle löschen']);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Zeile entfernen' }));
      expect(await screen.findByText('„Löhne“ steht danach nicht mehr im Entwurf. Die Kostenstelle bleibt bestehen.')).toBeInTheDocument();
      await answerDialog('Zeile entfernen?', 'Entfernen');
      expect(view.api.deleteLine).toHaveBeenCalledWith('v0', 'wages');
      expect(view.success).toHaveBeenCalledWith('Zeile entfernt.');
      expect(screen.getByRole('heading', { level: 2, name: 'Personal' })).toBeInTheDocument();
    });

    it('§F/finance/budget/000829: the floating button opens the dialog of a new Kostenstelle below the shown one', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const create = view.fixture.debugElement.query(By.directive(CostCentreCreateComponent)).componentInstance as CostCentreCreateComponent;
      expect(create.open()).toBe(false);
      await userEvent.click(screen.getByRole('button', { name: 'Kostenstelle anlegen' }));
      expect(create.open()).toBe(true);
      expect(create.parent()).toBe('grants');
      expect(create.versionId()).toBe('v0');
      expect(create.parentNodes()[0].children.map((c) => c.id)).toEqual(['fees', 'staff', 'grants']);
      expect([...create.firstChildAmounts().entries()]).toEqual([
        ['fees', '100.00'],
        ['wages', '60.00'],
        ['grants', '30.00'],
      ]);
      const withLine = plan([version({ lines: [line('fees', '100'), line('grants', '100')] })]);
      create.created.emit({ id: null, plan: withLine });
      view.fixture.detectChanges();
      expect(create.open()).toBe(false);
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
      expect(text(view.container.querySelector('.bd__figs'))).toContain('Ansatz 2026/27100 €');
      await userEvent.click(screen.getByRole('button', { name: 'Kostenstelle anlegen' }));
      create.closed.emit();
      view.fixture.detectChanges();
      expect(create.open()).toBe(false);
    });

    it('§F/finance/budget/000831: reads the tree again after a setting of a Kostenstelle changed', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const settings = view.fixture.debugElement.query(By.directive(CostCentreSettingsComponent)).componentInstance as CostCentreSettingsComponent;
      expect(settings.node().name).toBe('Beiträge');
      expect(settings.sided()).toBe(true);
      expect(settings.gremiumOptions()).toEqual([{ value: 'g1', label: 'StuPa' }]);
      settings.saved.emit();
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
      view.treeApi.tree.mockReturnValueOnce(throwError(() => problem(500)));
      const reads = view.api.plan.mock.calls.length;
      settings.saved.emit();
      expect(view.api.plan.mock.calls.length).toBeGreaterThan(reads);
      await userEvent.click(treeRow(view, 'Löhne'));
      const child = view.fixture.debugElement.query(By.directive(CostCentreSettingsComponent)).componentInstance as CostCentreSettingsComponent;
      expect(child.sided()).toBe(false);
    });

    it('has no Gremien to choose when their read fails', async () => {
      const view = await setup({ gremienFail: true, query: { costCentre: 'fees' } });
      const settings = view.fixture.debugElement.query(By.directive(CostCentreSettingsComponent)).componentInstance as CostCentreSettingsComponent;
      expect(settings.gremiumOptions()).toEqual([]);
    });

    it('§F/finance/budget/000832 §F/finance/budget/000840: deletes a Kostenstelle after the confirmation and shows its parent', async () => {
      const view = await setup({ query: { costCentre: 'wages' } });
      await choose('Kostenstelle löschen');
      expect(await screen.findByText(/„Löhne“ \(STAFF-WAGES\) wird gelöscht/)).toBeInTheDocument();
      await answerDialog('Kostenstelle löschen?', 'Abbrechen');
      expect(view.treeApi.deleteNode).not.toHaveBeenCalled();
      await choose('Kostenstelle löschen');
      await answerDialog('Kostenstelle löschen?', 'Löschen');
      expect(view.treeApi.deleteNode).toHaveBeenCalledWith('wages');
      expect(view.success).toHaveBeenCalledWith('Kostenstelle gelöscht.');
      expect(screen.getByRole('heading', { level: 2, name: 'Personal' })).toBeInTheDocument();
    });

    it('§F/finance/budget/000832: a version that is not a draft still deletes a Kostenstelle, and shows the plan after', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ state: 'in_force' })]) }, query: { costCentre: 'grants' } });
      expect(await openMenu()).toEqual(['Kostenstelle löschen']);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Kostenstelle löschen' }));
      await answerDialog('Kostenstelle löschen?', 'Löschen');
      expect(view.treeApi.deleteNode).toHaveBeenCalledWith('grants');
      expect(screen.getByRole('heading', { level: 2, name: 'VS-Mittel' })).toBeInTheDocument();
    });

    it('§F/finance/budget/000832: names the cause of a refused delete', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      view.treeApi.deleteNode.mockReturnValueOnce(throwError(() => problem(409, 'budget_has_bookings')));
      await choose('Kostenstelle löschen');
      await answerDialog('Kostenstelle löschen?', 'Löschen');
      expect(view.error).toHaveBeenCalledWith('Die Kostenstelle hat Buchungen und lässt sich nicht löschen.');
      expect(screen.getByRole('heading', { level: 2, name: 'Zuschüsse' })).toBeInTheDocument();
    });

    it('a phone deletes a Kostenstelle from the menu of the sheet and closes the sheet', async () => {
      const view = await setup({ wide: false, phone: true, query: { costCentre: 'grants' } });
      const sheet = await screen.findByRole('dialog', { name: 'Zuschüsse' });
      await choose('Kostenstelle löschen', sheet);
      await answerDialog('Kostenstelle löschen?', 'Löschen');
      expect(view.treeApi.deleteNode).toHaveBeenCalledWith('grants');
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Zuschüsse' })).toBeNull());
    });
  });
});
