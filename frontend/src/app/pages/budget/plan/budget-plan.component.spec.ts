import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { Location } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { downloadBlob, ToastService } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import { AdminApiService } from '../../admin/admin-api.service';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from '../budget-tree.api';
import { CostCentreCreateComponent } from '../cost-centre/cost-centre-create.component';
import { CostCentreSettingsComponent } from '../cost-centre/cost-centre-settings.component';
import { BudgetPlanApi, type BudgetPlan, type PlanMeeting, type PlanStep } from './budget-plan.api';
import { BudgetPlanComponent } from './budget-plan.component';
import { FY25, FY26, QSM, TOP, fy, line, node, plan, version } from './budget-plan.fixtures';

function setViewport(wide: boolean, phone = false, roomy = wide): void {
  window.matchMedia = ((query: string) => ({
    matches:
      (wide && query.includes('min-width: 1200px')) ||
      (roomy && query.includes('min-width: 1340px')) ||
      (phone && query === '(max-width: 767.98px)'),
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

jest.mock('@stupa-makers/ui-kit', () => ({
  ...jest.requireActual('@stupa-makers/ui-kit'),
  downloadBlob: jest.fn(),
}));

interface Opts {
  tree?: readonly BudgetTreeNode[];
  years?: readonly FiscalYear[];
  /** The plan of each fiscal year; a year without an entry answers 404. */
  plans?: Readonly<Record<string, BudgetPlan>>;
  perms?: readonly string[];
  wide?: boolean;
  phone?: boolean;
  /** The window is wide and has no room for the column "Änderung" beside the year before. */
  tight?: boolean;
  query?: Record<string, string>;
  /** The export of a version fails. */
  exportFail?: boolean;
  /** The feature Abstimmungen is off. */
  votingOff?: boolean;
  /** The read of the Gremien fails. */
  gremienFail?: boolean;
  /** The read of the plan of a version fails. */
  versionFail?: boolean;
}

async function setup(opts: Opts = {}) {
  (downloadBlob as jest.Mock).mockClear();
  TestBed.resetTestingModule();
  setViewport(opts.wide ?? true, opts.phone, (opts.wide ?? true) && !opts.tight);
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
    requestStep: jest.fn((..._args: unknown[]) => answer()),
    setStateByHand: jest.fn((..._args: unknown[]) => answer()),
    exportVersion: jest.fn((_id: string, format: string) =>
      opts.exportFail ? throwError(() => problem(503)) : of({ blob: new Blob(['x']), filename: `Haushaltsplan_VS.${format}` }),
    ),
  };
  const treeApi = {
    tree: jest.fn(() => of(opts.tree ?? [TOP, QSM])),
    changed: new Subject<void>(),
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
const ASKED = { ...STEPS[0], requestedAt: '2026-01-10T00:00:00Z' };
const MEETING: PlanMeeting = { id: 'm1', title: '12. Sitzung', date: '2026-01-20', status: 'planned' };
/** A version whose first step waits for the StuPa, with the meetings that have it on their agenda. */
const waiting = (meetings: readonly PlanMeeting[] = []) =>
  plan([version({ state: 'in_progress', steps: [ASKED, STEPS[1]], meetings })]);
const withVote = (voteStatus: PlanStep['voteStatus']) =>
  plan([version({ state: 'in_progress', steps: [{ ...ASKED, voteId: 'vote-1', voteStatus }, STEPS[1]] })]);

const text = (el: Element | null | undefined) => el?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
const texts = (view: View, selector: string) => [...view.container.querySelectorAll(selector)].map(text);
const input = (view: View, name: string) => view.container.querySelector<HTMLInputElement>(`[name="${name}"]`) as HTMLInputElement;
const primary = () => within(screen.getByTestId('bp-primary')).getByRole('button');
const treeRow = (view: View, name: string) =>
  within(view.container.querySelector('.bd__tree') as HTMLElement).getByRole('button', { name: new RegExp(`^${name}`) });
const tableRow = (name: string) => screen.getAllByText(name).find((el) => el.classList.contains('bp__name')) as HTMLElement;

/** The two file entries of the head menu: each reader of the plan has them. */
const FILES = ['Als PDF exportieren', 'Als XLSX exportieren'];

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
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
      expect(screen.queryByRole('button', { name: /^Haushalt:/ })).toBeNull();
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

    it('§F/finance/budget/000811: an empty draft passes no step and takes no request', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS, lines: [] })]) } });
      expect(primary()).toHaveAccessibleName('Beschluss anfragen');
      expect(primary()).toBeDisabled();
      expect(primary()).toHaveAttribute('title', 'Der Plan hat keine Zeile.');
      expect(view.api.requestStep).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000808: shows the columns of the year before and the change', async () => {
      const before = plan([version({ id: 'p', state: 'in_force', lines: [line('fees', '80'), line('grants', '30')] })], 'fy-25');
      const view = await setup({ plans: { 'fy-26': plan(), 'fy-25': before } });
      const income = view.container.querySelectorAll('app-data-table')[0] as HTMLElement;
      expect(within(income).getAllByRole('columnheader').map(text)).toEqual([
        'Titel',
        'Ansatz 2026/27',
        'Ansatz 2025/26',
        'Ist 2025/26',
        'Änderung',
      ]);
      const cells = within(income).getAllByRole('row').at(-1) as HTMLElement;
      expect(text(cells)).toContain('80 €');
      expect(text(cells)).toContain('+20 €');
    });

    it('§F/finance/budget/000808: a wide window below 1340 px has no column "Änderung" beside the year before', async () => {
      const before = plan([version({ id: 'p', state: 'in_force', lines: [line('fees', '80'), line('grants', '30')] })], 'fy-25');
      const view = await setup({ plans: { 'fy-26': plan(), 'fy-25': before }, tight: true });
      const income = view.container.querySelectorAll('app-data-table')[0] as HTMLElement;
      expect(within(income).getAllByRole('columnheader').map(text)).toEqual([
        'Titel',
        'Ansatz 2026/27',
        'Ansatz 2025/26',
        'Ist 2025/26',
      ]);
      const first = await setup({ years: [FY26], tight: true });
      const alone = first.container.querySelectorAll('app-data-table')[0] as HTMLElement;
      expect(within(alone).getAllByRole('columnheader').map(text)).toEqual(['Titel', 'Ansatz 2026/27', 'Änderung']);
    });

    it('has no columns of the year before in the first year', async () => {
      const view = await setup({ years: [FY26] });
      const income = view.container.querySelectorAll('app-data-table')[0] as HTMLElement;
      expect(within(income).getAllByRole('columnheader').map(text)).toEqual(['Titel', 'Ansatz 2026/27', 'Änderung']);
    });

    it('§F/finance/budget/000809: shows a Nachtrag beside the version before it', async () => {
      const stamm = version({ state: 'in_force', inForceAt: '2026-03-01T00:00:00Z', steps: passed(2) });
      const nachtrag = version({ id: 'v1', number: 1, lines: [line('fees', '100'), line('grants', '45'), line('other', '15')] });
      const view = await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) } });
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: 1. Nachtrag');
      const expense = view.container.querySelectorAll('app-data-table')[1] as HTMLElement;
      expect(within(expense).getAllByRole('columnheader').map(text)).toEqual([
        'Titel',
        'Ansatz 1. Nachtrag',
        'Ansatz Haushaltsplan',
        'Änderung',
      ]);
      expect(text(expense)).toContain('+15 €');
      await pickChip(/^Version/, 'Haushaltsplan');
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
      expect(figures).toContain('Ansatz Haushaltsplan30 €');
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
      await pickChip(/^Version/, 'Haushaltsplan');
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
      await pickChip(/^Haushalt:/, 'Zweiter');
      expect(view.container.querySelector('app-load-error')).not.toBeNull();
    });

    it('shows an error when the tree read fails', async () => {
      setViewport(true);
      const view = await render(BudgetPlanComponent, {
        providers: [
          provideRouter([]),
          { provide: BudgetPlanApi, useValue: {} },
          { provide: BudgetTreeApi, useValue: { tree: () => throwError(() => problem(500)), changed: new Subject<void>() } },
          { provide: AuthService, useValue: { can: () => true } },
          { provide: AdminApiService, useValue: { listGremienOptions: () => of([]) } },
        ],
      });
      expect(view.container.querySelector('app-load-error')).not.toBeNull();
    });

    it('the retry of a failed read of the fiscal years reads them again', async () => {
      const view = await setup();
      expect(view.container.querySelector('app-load-error')).toBeNull();
      view.treeApi.listFiscalYears.mockReturnValueOnce(throwError(() => problem(500)));
      view.fixture.componentInstance.retry();
      view.fixture.detectChanges();
      const failed = view.debugElement.query(By.directive(LoadErrorComponent));
      expect(failed).not.toBeNull();
      const reads = view.treeApi.listFiscalYears.mock.calls.length;
      failed.triggerEventHandler('retry');
      view.fixture.detectChanges();
      expect(view.treeApi.listFiscalYears).toHaveBeenCalledTimes(reads + 1);
      expect(view.container.querySelector('app-load-error')).toBeNull();
      expect(texts(view, '.bp__name').length).toBeGreaterThan(0);
    });

    it('the retry after a failed read of the years of a newly chosen budget reads that budget', async () => {
      const view = await setup({ tree: [TOP, { ...QSM, planEnabled: true }] });
      view.treeApi.listFiscalYears.mockReturnValueOnce(throwError(() => problem(500)));
      view.fixture.componentInstance.pickTop(QSM.id);
      view.fixture.detectChanges();
      expect(view.container.querySelector('app-load-error')).not.toBeNull();
      view.fixture.componentInstance.retry();
      expect(view.treeApi.listFiscalYears).toHaveBeenLastCalledWith(QSM.id);
    });

    it('drops a Kostenstelle of the URL that is not in the tree of the budget', async () => {
      const view = await setup({ query: { costCentre: 'qsm-child' } });
      view.fixture.componentInstance.pickYear('fy-26');
      expect(view.navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: expect.objectContaining({ costCentre: null }) }),
      );
      const inTree = await setup({ query: { costCentre: 'fees' } });
      inTree.fixture.componentInstance.pickYear('fy-26');
      expect(inTree.navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: expect.objectContaining({ costCentre: 'fees' }) }),
      );
    });

    it('takes the budget and the year of the URL and names the budget on its chip', async () => {
      const second = node({ id: 'two', name: 'Zweiter', planEnabled: true });
      const view = await setup({ tree: [TOP, second], query: { budget: 'two', fy: 'fy-25' } });
      expect(screen.getByRole('button', { name: /^Haushalt:/ })).toHaveTextContent('Haushalt: Zweiter');
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2025/26');
      expect(view.api.plan).toHaveBeenCalledWith('two', 'fy-25');
      await pickChip(/^Haushalt:/, 'VS-Mittel');
      expect(view.treeApi.listFiscalYears).toHaveBeenLastCalledWith('vsm');
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      expect(view.api.plan).toHaveBeenLastCalledWith('vsm', 'fy-25');
    });

    it('§F/finance/budget/000809: opens the version that the URL names', async () => {
      const stamm = version({ state: 'in_force' });
      const nachtrag = version({ id: 'v1', number: 1 });
      await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) }, query: { version: '0' } });
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
      await setup({ plans: { 'fy-26': plan([stamm, nachtrag]) }, query: { version: 'x' } });
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: 1. Nachtrag');
    });

    it('§F/finance/budget/000826: opens the plan of the version that a vote names', async () => {
      const old = plan([version({ id: 'old', state: 'replaced' }), version({ id: 'now', number: 1, state: 'in_force' })], 'fy-25');
      const view = await setup({ plans: { 'fy-25': old, 'fy-26': plan() }, query: { planVersion: 'old' } });
      expect(view.api.planOfVersion).toHaveBeenCalledWith('old');
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2025/26');
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
      const gone = await setup({ plans: { 'fy-25': old, 'fy-26': plan() }, query: { planVersion: 'zzz' } });
      expect(gone.api.planOfVersion).toHaveBeenCalledWith('zzz');
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: 1. Nachtrag');
      const failed = await setup({ versionFail: true, query: { planVersion: 'old' } });
      expect(failed.api.plan).toHaveBeenCalledWith('vsm', 'fy-26');
    });

    it('§F/finance/budget/000816: a quiet read of the plan keeps the line open', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const settings = () =>
        view.fixture.debugElement.query(By.directive(CostCentreSettingsComponent))?.componentInstance as CostCentreSettingsComponent;
      const first = settings();
      const late = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(late);
      view.fixture.componentInstance.refreshPlan();
      view.fixture.detectChanges();
      expect(settings()).toBe(first);
      expect(view.container.querySelector('app-skeleton')).toBeNull();
      late.next(plan([version({ lines: [line('fees', '77')] })]));
      view.fixture.detectChanges();
      expect(settings()).toBe(first);
      expect(text(view.container.querySelector('.bp__lineFigs'))).toContain('77 €');
      const failed = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(failed).mockReturnValueOnce(throwError(() => problem(500)));
      view.fixture.componentInstance.refreshPlan();
      failed.error(problem(500));
      view.fixture.detectChanges();
      expect(view.container.querySelector('.bd__sheetBody app-load-error')).not.toBeNull();
      await pickChip(/Haushaltsjahr/, 'HHJ 2026/27');
      const other = new Subject<BudgetPlan>();
      const gone = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(other).mockReturnValueOnce(gone);
      view.fixture.componentInstance.refreshPlan();
      view.fixture.componentInstance.refreshPlan();
      const reads = view.api.plan.mock.calls.length;
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      other.next(plan([version({ lines: [line('fees', '55')] })]));
      gone.error(problem(500));
      view.fixture.detectChanges();
      expect(view.container.textContent).not.toContain('55 €');
      expect(view.api.plan.mock.calls.length).toBeGreaterThan(reads);
      expect(view.container.querySelector('.bd__sheetBody app-load-error')).toBeNull();
      view.api.plan.mockReturnValueOnce(throwError(() => problem(404, 'plan_not_found')));
      view.fixture.componentInstance.refreshPlan();
      view.fixture.detectChanges();
      expect(screen.getByText('Kein Haushaltsplan')).toBeInTheDocument();
    });

    it('§F/finance/budget/000812: an answer for another year does not come onto the page', async () => {
      const view = await setup({ plans: { 'fy-25': plan([version({ state: 'in_force' })], 'fy-25'), 'fy-26': plan() } });
      const read = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(read);
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      await pickChip(/Haushaltsjahr/, 'HHJ 2026/27');
      read.next(plan([version({ id: 'late', number: 3 })], 'fy-25'));
      read.complete();
      view.fixture.detectChanges();
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
      const old = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(old);
      view.fixture.componentInstance.reloadPlan();
      view.fixture.componentInstance.refreshPlan();
      old.next(plan([version({ id: 'old', number: 4 })]));
      old.complete();
      view.fixture.detectChanges();
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
      const failed = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(failed);
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      await pickChip(/Haushaltsjahr/, 'HHJ 2026/27');
      failed.error(problem(500));
      view.fixture.detectChanges();
      expect(view.container.querySelector('.bd__sheetBody app-load-error')).toBeNull();
      const saved = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(saved);
      await typeAmount(input(view, 'amount-fees'), '12');
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      saved.next(plan([version({ id: 'late', number: 3 })]));
      view.fixture.detectChanges();
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2025/26');
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
    });

    it('§F/finance/budget/000812: a late answer keeps the version that the person chose, and a new read keeps it in the URL', async () => {
      const both = plan([version({ state: 'in_force' }), version({ id: 'v1', number: 1 })]);
      const view = await setup({ plans: { 'fy-26': both } });
      const saved = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(saved);
      await typeAmount(input(view, 'amount-fees'), '12');
      await pickChip(/^Version/, 'Haushaltsplan');
      saved.next(both);
      view.fixture.detectChanges();
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
      view.fixture.componentInstance.reloadPlan();
      expect(view.navigate).toHaveBeenLastCalledWith(
        [],
        expect.objectContaining({ queryParams: expect.objectContaining({ fy: 'fy-26', version: 0 }) }),
      );
    });

    it('§F/finance/budget/000812 §F/finance/budget/000848: the answer of a new Kostenstelle and the years of a budget that the person left stay off the page', async () => {
      const second = node({ id: 'two', name: 'Zweiter', planEnabled: true });
      const view = await setup({
        tree: [TOP, second],
        plans: { 'fy-25': plan([version({ state: 'in_force' })], 'fy-25'), 'fy-26': plan() },
      });
      const page = view.fixture.componentInstance;
      const tree = new Subject<BudgetTreeNode[]>();
      view.treeApi.tree.mockReturnValueOnce(tree);
      page.onCreated({ id: null, plan: plan([version({ id: 'late', number: 3 })]) });
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      tree.next([TOP, second]);
      view.fixture.detectChanges();
      expect(screen.getByRole('button', { name: /^Version/ })).toHaveTextContent('Version: Haushaltsplan');
      const years = new Subject<FiscalYear[]>();
      const failed = new Subject<FiscalYear[]>();
      view.treeApi.listFiscalYears.mockReturnValueOnce(years).mockReturnValueOnce(failed);
      page.pickTop('two');
      page.pickTop('two');
      view.fixture.detectChanges();
      expect(screen.queryByRole('button', { name: /^Version/ })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).toBeNull();
      expect(screen.queryByTestId('bp-primary')).toBeNull();
      page.pickTop('vsm');
      years.next([fy('other', 2040)]);
      failed.error(problem(500));
      view.fixture.detectChanges();
      expect(screen.getByRole('button', { name: /Haushaltsjahr/ })).toHaveTextContent('HHJ 2026/27');
      expect(view.container.querySelector('app-load-error')).toBeNull();
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
      expect(screen.queryByRole('button', { name: /^(Titel|Kostenstelle) anlegen$/ })).toBeNull();
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
      expect(screen.getByRole('button', { name: /^Haushalt:/ })).toHaveTextContent('Haushalt: VS-Mittel');
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
      expect(view.success).not.toHaveBeenCalled();
      expect(screen.queryByRole('heading', { level: 2, name: 'Zuschüsse' })).toBeNull();
    });

    it('§F/finance/budget/000812: an amount field shows the last amount while the answer of the save before holds another', async () => {
      const view = await setup();
      const first = new Subject<BudgetPlan>();
      const second = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(second);
      const field = input(view, 'amount-grants');
      const lines = (grants: string) => [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', grants)];
      await typeAmount(field, '80');
      await typeAmount(field, '90');
      expect(view.api.setLine.mock.calls.map((call) => call[2])).toEqual([{ amount: '80' }, { amount: '90' }]);
      expect(field.value).toBe('90,00');
      first.next(plan([version({ lines: lines('80') })]));
      first.complete();
      view.fixture.detectChanges();
      expect(field.value).toBe('90,00');
      second.next(plan([version({ lines: lines('90') })]));
      second.complete();
      view.fixture.detectChanges();
      expect(field.value).toBe('90,00');
    });

    it('§F/finance/budget/000812: a refused amount gives the field the amount of the save that still runs', async () => {
      const view = await setup();
      const first = new Subject<BudgetPlan>();
      const second = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(second);
      const field = input(view, 'amount-grants');
      await typeAmount(field, '80');
      await typeAmount(field, '75');
      second.error(problem(409, 'plan_blocked_above_amount'));
      await waitFor(() => expect(input(view, 'amount-grants').value).toBe('80,00'));
      first.next(plan([version({ lines: [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '80')] })]));
      first.complete();
    });

    it('§F/finance/budget/000812: a refused amount leaves the amount of the later save in the field', async () => {
      const view = await setup();
      const first = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(new Subject<BudgetPlan>());
      await typeAmount(input(view, 'amount-grants'), '80');
      await typeAmount(input(view, 'amount-grants'), '75');
      first.error(problem(409, 'plan_blocked_above_amount'));
      view.fixture.detectChanges();
      await new Promise((done) => setTimeout(done, 50));
      const page = view.fixture.componentInstance;
      expect(page.fieldValue(page.rows().find((row) => row.id === 'grants')!, 'amount')).toBe('75');
      expect(input(view, 'amount-grants').value).toBe('75,00');
    });

    it('§F/finance/budget/000812: a typed Sperrvermerk is saved when the person selects another line', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      await userEvent.type(input(view, 'line-blocked-grants'), '5');
      view.fixture.componentInstance.selectId('wages');
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', { blocked: '5' });
    });

    it('§F/finance/budget/000809: the change of a line shows its sign, and no change shows a dash', async () => {
      const view = await setup();
      const page = view.fixture.componentInstance;
      const row = page.rows()[0];
      expect(page.changeText({ ...row, amount: 30, prev: 10 })).toMatch(/^\+20\s€$/);
      expect(page.changeText({ ...row, amount: 10, prev: 30 })).toMatch(/^−20\s€$/);
      expect(page.changeText({ ...row, amount: 10, prev: 10 })).toBe('–');
      expect(page.changeText({ ...row, amount: 10, prev: null })).toBe('–');
    });

    it('§F/finance/budget/000812: a save that answers after the person left writes no URL of the plan page', async () => {
      const view = await setup();
      const answers: Subject<BudgetPlan>[] = [new Subject(), new Subject(), new Subject()];
      answers.forEach((answer) => view.api.setLine.mockReturnValueOnce(answer));
      const save = async (value: string, answer: Subject<BudgetPlan>) => {
        await typeAmount(input(view, 'amount-grants'), value);
        view.navigate.mockClear();
        answer.next(plan());
        answer.complete();
      };
      const leaving = jest.spyOn(view.router, 'getCurrentNavigation');
      leaving.mockReturnValue({ extractedUrl: view.router.parseUrl('/voting') } as ReturnType<Router['getCurrentNavigation']>);
      await save('41', answers[0]);
      expect(view.navigate).not.toHaveBeenCalled();
      leaving.mockReturnValue({ extractedUrl: view.router.parseUrl(`${view.router.url}?fy=fy-26`) } as ReturnType<Router['getCurrentNavigation']>);
      await save('42', answers[1]);
      expect(view.navigate).toHaveBeenCalled();
      leaving.mockReturnValue(null);
      await typeAmount(input(view, 'amount-grants'), '43');
      view.navigate.mockClear();
      view.fixture.destroy();
      answers[2].next(plan());
      expect(view.navigate).not.toHaveBeenCalled();
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
      expect(screen.queryByRole('button', { name: /^(Titel|Kostenstelle) anlegen$/ })).toBeNull();
      const reader = await setup({ perms: ['budget.view'] });
      expect(screen.queryByTestId('bp-primary')).toBeNull();
      expect(await openMenu()).toEqual(FILES);
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

    it('§F/finance/budget/000812: a refused field keeps the line open and shows the saved text again', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const sheet = () => view.container.querySelector('.bp__lineFigs');
      const open = sheet();
      const pending = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(pending);
      view.api.setLine.mockReturnValueOnce(throwError(() => problem(422, 'plan_blocked_above_amount')));
      const note = view.container.querySelector<HTMLTextAreaElement>('[name="line-note-grants"]') as HTMLTextAreaElement;
      await userEvent.type(note, 'Neu');
      await userEvent.tab();
      view.fixture.detectChanges();
      expect(view.error).toHaveBeenCalledWith('Der gesperrte Betrag liegt über dem Ansatz.');
      expect(sheet()).toBe(open);
      expect(view.container.querySelector('app-skeleton')).toBeNull();
      expect(note.value).toBe('');
      pending.next(plan());
      view.fixture.detectChanges();
      expect(sheet()).toBe(open);
    });

    it('§F/finance/budget/000812: a refused Vermerk shows the saved state again, a saved one stays', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const refused = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(refused);
      const mark = screen.getByRole('switch', { name: 'Übertragbar' });
      await userEvent.click(mark);
      view.fixture.detectChanges();
      expect(mark).toHaveAttribute('aria-checked', 'true');
      refused.error(problem(409, 'plan_not_draft'));
      view.fixture.detectChanges();
      expect(mark).toHaveAttribute('aria-checked', 'false');
      const marked = plan([version({ lines: [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '30', { transferable: true })] })]);
      view.api.setLine.mockReturnValueOnce(of(marked));
      await userEvent.click(screen.getByRole('switch', { name: 'Übertragbar' }));
      view.fixture.detectChanges();
      expect(screen.getByRole('switch', { name: 'Übertragbar' })).toHaveAttribute('aria-checked', 'true');
      expect(view.fixture.componentInstance.mark({ id: 'grants', transferable: false } as never, 'transferable')).toBe(false);
    });

    it('§F/finance/budget/000812: a typed Erläuterung stays with its line and survives the answer of its own save', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const page = view.fixture.componentInstance;
      const note = (id: string) => view.container.querySelector<HTMLTextAreaElement>(`[name="line-note-${id}"]`) as HTMLTextAreaElement;
      const saving = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(saving);
      await userEvent.type(note('grants'), 'Erster');
      await userEvent.tab();
      await userEvent.type(note('grants'), ' und mehr');
      saving.next(plan([version({ lines: [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '30', { note: 'Erster' })] })]));
      saving.complete();
      view.fixture.detectChanges();
      expect(note('grants').value).toBe('Erster und mehr');
      view.api.setLine.mockReturnValueOnce(new Subject<BudgetPlan>());
      page.selectId('wages');
      view.fixture.detectChanges();
      expect(view.api.setLine).toHaveBeenLastCalledWith('v0', 'grants', { note: 'Erster und mehr' });
      expect(view.api.setLine).toHaveBeenCalledTimes(2);
      page.selectId('grants');
      page.selectId('wages');
      expect(view.api.setLine).toHaveBeenCalledTimes(2);
      expect(note('wages').value).toBe('');
      expect(page.noteValue({ id: 'wages', note: 'x' } as never)).toBe('x');
    });

    it('§F/finance/budget/000812: a press and a text of one year do not show in the line of another year', async () => {
      const marked = [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '30')];
      const view = await setup({
        plans: { 'fy-25': plan([version({ id: 'v25', lines: marked })], 'fy-25'), 'fy-26': plan() },
        query: { costCentre: 'grants' },
      });
      const note = () => view.container.querySelector<HTMLTextAreaElement>('[name="line-note-grants"]') as HTMLTextAreaElement;
      const mark = new Subject<BudgetPlan>();
      const text = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(mark).mockReturnValueOnce(text);
      await userEvent.click(screen.getByRole('switch', { name: 'Übertragbar' }));
      await userEvent.type(note(), 'Text von 26');
      await pickChip(/Haushaltsjahr/, 'HHJ 2025/26');
      view.fixture.detectChanges();
      expect(view.api.setLine).toHaveBeenCalledTimes(2);
      expect(screen.getByRole('switch', { name: 'Übertragbar' })).toHaveAttribute('aria-checked', 'false');
      expect(note().value).toBe('');
      mark.next(plan());
      mark.complete();
      text.next(plan());
      text.complete();
      await pickChip(/Haushaltsjahr/, 'HHJ 2026/27');
      view.fixture.detectChanges();
      expect(screen.getByRole('switch', { name: 'Übertragbar' })).toHaveAttribute('aria-checked', 'false');
      expect(note().value).toBe('');
    });

    it('§F/finance/budget/000812: a field that is set back while its save runs is saved again', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const first = new Subject<BudgetPlan>();
      const second = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(second);
      const mark = screen.getByRole('switch', { name: 'Übertragbar' });
      await userEvent.click(mark);
      await userEvent.click(mark);
      expect(view.api.setLine.mock.calls.map((call) => call[2])).toEqual([{ transferable: true }, { transferable: false }]);
      first.next(plan([version({ lines: [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '30', { transferable: true })] })]));
      first.complete();
      view.fixture.detectChanges();
      expect(mark).toHaveAttribute('aria-checked', 'false');
      second.next(plan());
      second.complete();
      view.fixture.detectChanges();
      expect(mark).toHaveAttribute('aria-checked', 'false');
      await userEvent.click(mark);
      expect(view.api.setLine).toHaveBeenCalledTimes(3);
    });

    it('§F/finance/budget/000810: the amount fields of a table are wide from a typed Ansatz of 10 million euro on, also while its save runs', async () => {
      const view = await setup();
      const field = () => view.container.querySelector('app-currency-input.bp__field') as HTMLElement;
      expect(field()).not.toHaveClass('bp__field--wide');
      const saved = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(saved);
      await typeAmount(input(view, 'amount-fees'), '10000000');
      view.fixture.detectChanges();
      expect(field()).toHaveClass('bp__field--wide');
    });

    it('§F/finance/budget/000810: the amount fields of a table are wide for a plan that holds an Ansatz from 10 million euro', async () => {
      const large = plan([version({ lines: [line('fees', '10000000'), line('staff', '70'), line('wages', '60'), line('grants', '30')] })]);
      const view = await setup({ plans: { 'fy-26': large } });
      expect(view.container.querySelector('app-currency-input.bp__field')).toHaveClass('bp__field--wide');
    });

    it('§F/finance/budget/000812: a Vermerk keeps the last press until its last save ended', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const on = plan([version({ lines: [line('fees', '100'), line('staff', '70'), line('wages', '60'), line('grants', '30', { transferable: true })] })]);
      const first = new Subject<BudgetPlan>();
      const second = new Subject<BudgetPlan>();
      const third = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(second).mockReturnValueOnce(third);
      const mark = screen.getByRole('switch', { name: 'Übertragbar' });
      await userEvent.click(mark);
      await userEvent.click(mark);
      await userEvent.click(mark);
      first.next(on);
      first.complete();
      second.next(plan());
      second.complete();
      view.fixture.detectChanges();
      expect(mark).toHaveAttribute('aria-checked', 'true');
      third.error(problem(409, 'plan_state_invalid'));
      view.fixture.detectChanges();
      expect(mark).toHaveAttribute('aria-checked', 'false');
    });

    it('§F/finance/budget/000812: a field set back is saved again after a save of another field of its line ended', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const held = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(held);
      const mark = screen.getByRole('switch', { name: 'Übertragbar' });
      await userEvent.click(mark);
      await userEvent.click(screen.getByRole('switch', { name: 'Deckungsfähig' }));
      await userEvent.click(mark);
      expect(view.api.setLine.mock.calls.map((call) => call[2])).toEqual([{ transferable: true }, { coverable: true }, { transferable: false }]);
    });

    it('§F/finance/budget/000812: an Erläuterung keeps the last text until its last save ended', async () => {
      const view = await setup({ query: { costCentre: 'grants' } });
      const note = () => view.container.querySelector<HTMLTextAreaElement>('[name="line-note-grants"]') as HTMLTextAreaElement;
      const first = new Subject<BudgetPlan>();
      const second = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(second).mockReturnValueOnce(new Subject<BudgetPlan>());
      await userEvent.type(note(), 'a');
      await userEvent.tab();
      await userEvent.clear(note());
      await userEvent.tab();
      await userEvent.type(note(), 'a');
      await userEvent.tab();
      expect(view.api.setLine).toHaveBeenCalledTimes(3);
      first.next(plan());
      first.complete();
      second.next(plan());
      second.complete();
      view.fixture.detectChanges();
      expect(note().value).toBe('a');
    });

    it('§F/finance/budget/000812: the read after mixed answers waits for a page that loads another budget', async () => {
      const view = await setup({ tree: [TOP, node({ id: 'two', name: 'Zweiter', planEnabled: true })], query: { costCentre: 'fees' } });
      const first = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(of(plan([version({ lines: [line('fees', '9')] })])));
      await typeAmount(input(view, 'line-amount-fees'), '8');
      await typeAmount(input(view, 'line-amount-fees'), '9');
      view.treeApi.listFiscalYears.mockReturnValueOnce(new Subject<FiscalYear[]>());
      view.fixture.componentInstance.pickTop('two');
      const reads = view.api.plan.mock.calls.length;
      first.next(plan([version({ lines: [line('fees', '8')] })]));
      first.complete();
      expect(view.api.plan.mock.calls.length).toBe(reads);
    });

    it('§F/finance/budget/000812: after answers in another order than their requests the page reads the plan once more', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const first = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(of(plan([version({ lines: [line('fees', '9')] })])));
      await typeAmount(input(view, 'line-amount-fees'), '8');
      await typeAmount(input(view, 'line-amount-fees'), '9');
      const reads = view.api.plan.mock.calls.length;
      view.api.plan.mockReturnValueOnce(of(plan([version({ lines: [line('fees', '80')] })])));
      first.next(plan([version({ lines: [line('fees', '8')] })]));
      first.complete();
      view.fixture.detectChanges();
      expect(view.api.plan.mock.calls.length).toBe(reads + 1);
      expect(text(view.container.querySelector('.bp__lineFigs'))).toContain('80 €');
    });

    it('§F/finance/budget/000848: another budget takes the selected Kostenstelle of the budget before off the page', async () => {
      const view = await setup({ tree: [TOP, node({ id: 'two', name: 'Zweiter', planEnabled: true })], query: { costCentre: 'grants' } });
      const page = view.fixture.componentInstance;
      expect(page.selId()).toBe('grants');
      page.pickTop('vsm');
      expect(page.selId()).toBe('grants');
      page.pickTop('two');
      expect(page.selId()).toBe('');
    });

    it('§F/finance/budget/000812: an answer that is older than the plan on the page does not replace it', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const read = new Subject<BudgetPlan>();
      view.api.plan.mockReturnValueOnce(read);
      view.fixture.componentInstance.refreshPlan();
      view.api.setLine.mockReturnValueOnce(of(plan([version({ lines: [line('fees', '777')] })])));
      await typeAmount(input(view, 'line-amount-fees'), '777');
      read.next(plan([version({ lines: [line('fees', '1')] })]));
      view.fixture.detectChanges();
      expect(text(view.container.querySelector('.bp__lineFigs'))).toContain('777 €');
      const first = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(first).mockReturnValueOnce(of(plan([version({ lines: [line('fees', '9')] })])));
      await typeAmount(input(view, 'line-amount-fees'), '8');
      await typeAmount(input(view, 'line-amount-fees'), '9');
      first.next(plan([version({ lines: [line('fees', '8')] })]));
      view.fixture.detectChanges();
      expect(text(view.container.querySelector('.bp__lineFigs'))).toContain('9 €');
      const tree = new Subject<BudgetTreeNode[]>();
      view.treeApi.tree.mockReturnValueOnce(tree);
      view.fixture.componentInstance.onCreated({ id: null, plan: plan([version({ lines: [line('fees', '5')] })]) });
      view.api.setLine.mockReturnValueOnce(of(plan([version({ lines: [line('fees', '6')] })])));
      await typeAmount(input(view, 'line-amount-fees'), '6');
      tree.next([TOP, QSM]);
      view.fixture.detectChanges();
      expect(text(view.container.querySelector('.bp__lineFigs'))).toContain('6 €');
    });
  });

  describe('steps', () => {
    it('§F/finance/budget/000792 §F/finance/budget/000825 §F/finance/budget/000840 §F/finance/budget/000841: passes a step without a Gremium by hand after the confirmation', async () => {
      const steps = STEPS.map((step) => ({ ...step, gremiumId: null }));
      const view = await setup({ plans: { 'fy-26': plan([version({ steps })]) } });
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
      expect(await openMenu()).toEqual(['Zurück in den Entwurf', ...FILES]);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Zurück in den Entwurf' }));
      expect(await screen.findByText(/Eine laufende Abstimmung wird abgebrochen/)).toBeInTheDocument();
      await answerDialog('Zurück in den Entwurf?', 'Zurück in den Entwurf');
      expect(view.api.setState).toHaveBeenCalledWith('v0', 'draft');
      expect(view.success).toHaveBeenCalledWith('Die Version ist wieder ein Entwurf.');
    });

    it('§F/finance/budget/000875: a reader loads the shown version as PDF and as XLSX', async () => {
      const view = await setup({ perms: ['budget.view'] });
      await choose('Als PDF exportieren');
      expect(view.api.exportVersion).toHaveBeenLastCalledWith('v0', 'pdf');
      await choose('Als XLSX exportieren');
      expect(view.api.exportVersion).toHaveBeenLastCalledWith('v0', 'xlsx');
      expect((downloadBlob as jest.Mock).mock.calls.map((call) => call[1])).toEqual([
        'Haushaltsplan_VS.pdf',
        'Haushaltsplan_VS.xlsx',
      ]);
    });

    it('§F/finance/budget/000875: a failed export shows a toast and frees the menu', async () => {
      const view = await setup({ exportFail: true });
      await choose('Als PDF exportieren');
      expect(view.error).toHaveBeenCalledWith('Der Export ist fehlgeschlagen.');
      expect(downloadBlob).not.toHaveBeenCalled();
      expect(await openMenu()).toContain('Als XLSX exportieren');
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

    it('§F/finance/budget/000838: asks the Gremium of the next step for its decision', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      expect(primary()).toHaveAccessibleName('Beschluss anfragen');
      expect(await openMenu()).toEqual(['Zeile hinzufügen', ...FILES, 'Entwurf löschen']);
      await userEvent.keyboard('{Escape}');
      await userEvent.click(primary());
      expect(view.api.requestStep).toHaveBeenCalledWith('v0');
      expect(view.success).toHaveBeenCalledWith('Beschluss angefragt.');
    });

    it('§F/finance/budget/000838: an unbalanced draft names the cause on the request', async () => {
      const draft = version({ steps: STEPS, lines: [line('fees', '100'), line('grants', '130')] });
      const view = await setup({ plans: { 'fy-26': plan([draft]) } });
      expect(primary()).toBeDisabled();
      expect(primary()).toHaveAttribute('title', 'Der Plan ist nicht ausgeglichen.');
      expect(view.api.requestStep).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000838: a request that the server refuses names its cause', async () => {
      const view = await setup({ plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      view.api.requestStep.mockReturnValueOnce(throwError(() => problem(409, 'plan_step_waits')));
      await userEvent.click(primary());
      expect(view.error).toHaveBeenCalledWith('Der Beschluss ist schon angefragt.');
    });

    it('§F/finance/budget/000838: a step that waits shows that it waits for a meeting of its Gremium', async () => {
      const view = await setup({ plans: { 'fy-26': waiting() } });
      expect(text(view.container.querySelector('.bp__stepper'))).toContain('Wartet auf eine Sitzung: StuPa');
      expect(screen.queryByTestId('bp-primary')).toBeNull();
      expect(await openMenu()).toEqual(['Zurück in den Entwurf', ...FILES]);
    });

    it('§F/finance/budget/000838: a step that waits names each meeting with the plan on its agenda and links to it', async () => {
      const view = await setup({ plans: { 'fy-26': waiting([MEETING, { ...MEETING, id: 'm2', title: 'Sondersitzung', date: null }]) } });
      expect(text(view.container.querySelector('.bp__stepper'))).toContain(
        'Auf der Tagesordnung: 12. Sitzung, 20.01.2026 · Sondersitzung',
      );
      expect(primary()).toHaveAccessibleName('Zur Sitzung');
      expect(await openMenu()).toEqual(['Zur Sitzung „Sondersitzung“', 'Zurück in den Entwurf', ...FILES]);
      await userEvent.click(screen.getByRole('menuitem', { name: 'Zur Sitzung „Sondersitzung“' }));
      expect(view.navigate).toHaveBeenCalledWith(['/meetings', 'm2']);
      await userEvent.click(primary());
      expect(view.navigate).toHaveBeenCalledWith(['/meetings', 'm1']);
    });

    it('§F/finance/budget/000838: the open vote of a step is the next action and opens the vote', async () => {
      const open = await setup({ plans: { 'fy-26': withVote('open') } });
      expect(text(open.container.querySelector('.bp__stepper'))).toContain('Abstimmung läuft');
      await userEvent.click(primary());
      expect(open.navigate).toHaveBeenCalledWith(['/voting', 'vote-1']);
    });

    it('§F/finance/budget/000838: a reader finds the vote of the step in the head, not alone in the menu', async () => {
      const view = await setup({ plans: { 'fy-26': withVote('open') }, perms: ['budget.view'] });
      expect(primary()).toHaveAccessibleName('Zur Abstimmung');
      await userEvent.click(primary());
      expect(view.navigate).toHaveBeenCalledWith(['/voting', 'vote-1']);
    });

    it('§F/finance/budget/000838: a reader gets no action that moves the version', async () => {
      await setup({ plans: { 'fy-26': withVote('open') }, perms: ['budget.view'] });
      expect(await openMenu()).toEqual(FILES);
      await setup({ plans: { 'fy-26': waiting() }, perms: ['budget.view'] });
      expect(await openMenu()).toEqual(FILES);
      await setup({ plans: { 'fy-26': withVote('open') }, perms: ['budget.view'], wide: false, phone: true });
      expect(await openMenu()).toEqual(['Zur Abstimmung', ...FILES]);
    });

    it('§F/finance/budget/000826: a cancelled vote leaves the step waiting for a meeting', async () => {
      const view = await setup({ plans: { 'fy-26': withVote('cancelled') } });
      expect(text(view.container.querySelector('.bp__stepper'))).toContain('Wartet auf eine Sitzung: StuPa');
      expect(await openMenu()).toEqual(['Zur Abstimmung', 'Zurück in den Entwurf', ...FILES]);
    });

    it('§F/finance/budget/000838: offers no request for a step without a Gremium or with Abstimmungen off', async () => {
      await setup({ plans: { 'fy-26': plan([version({ state: 'in_progress', steps: passed(1) })]) } });
      expect(primary()).toHaveAccessibleName('Schritt abschließen: Genehmigung');
      expect(await openMenu()).toEqual(['Zurück in den Entwurf', ...FILES]);
      await userEvent.keyboard('{Escape}');
      await setup({ votingOff: true, plans: { 'fy-26': plan([version({ steps: STEPS })]) } });
      expect(primary()).toHaveAccessibleName('Schritt abschließen: Beschluss');
      expect(await openMenu()).toEqual(['Zeile hinzufügen', ...FILES, 'Entwurf löschen']);
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

    it('§F/finance/budget/000852: a node below the Haushalt is a Titel, a node below it a Kostenstelle', async () => {
      const view = await setup();
      expect(screen.getByRole('button', { name: 'Titel anlegen' })).toBeInTheDocument();
      view.fixture.componentInstance.selectId('grants');
      view.fixture.detectChanges();
      expect(await screen.findByRole('heading', { name: 'Titel' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Kostenstelle anlegen' })).toBeInTheDocument();
      view.fixture.componentInstance.selectId('wages');
      view.fixture.detectChanges();
      expect(await screen.findByRole('heading', { name: 'Kostenstelle' })).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Titel' })).toBeNull();
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
      expect(settings.gremiumOptions()).toEqual([{ value: 'g1', label: 'StuPa' }]);
      const before = view.api.plan.mock.calls.length;
      settings.saved.emit(true);
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
      expect(view.api.plan.mock.calls.length).toBe(before);
      view.treeApi.tree.mockReturnValueOnce(throwError(() => problem(500)));
      const reads = view.api.plan.mock.calls.length;
      settings.saved.emit(true);
      expect(view.api.plan.mock.calls.length).toBeGreaterThan(reads);
    });

    it('§F/finance/budget/000851: drops the answer of a tree read that went out before the read on the page', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const older = new Subject<BudgetTreeNode[]>();
      const newer = new Subject<BudgetTreeNode[]>();
      view.treeApi.tree.mockReturnValueOnce(older).mockReturnValueOnce(newer);
      view.fixture.componentInstance.reloadTree();
      view.fixture.componentInstance.reloadTree();
      newer.next([{ ...TOP, name: 'Neu' }, QSM]);
      older.next([{ ...TOP, name: 'Alt' }, QSM]);
      expect((view.fixture.componentInstance as unknown as { tree(): BudgetTreeNode[] }).tree()[0].name).toBe('Neu');
    });

    it('§F/finance/budget/000850: reads the tree after a save of a section that went off a page before', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const reads = view.treeApi.tree.mock.calls.length;
      view.treeApi.changed.next();
      expect(view.treeApi.tree.mock.calls.length).toBe(reads + 1);
    });

    it('§F/finance/budget/000850: a failed tree read before the page took its budget from the URL leaves the URL', async () => {
      const view = await setup({ query: { budget: 'top', fy: 'fy-25', costCentre: 'fees' } });
      const page = view.fixture.componentInstance as unknown as { topId: { set(id: string): void } };
      page.topId.set('');
      view.navigate.mockClear();
      view.treeApi.tree.mockReturnValueOnce(throwError(() => problem(0)));
      view.treeApi.changed.next();
      expect(view.navigate).not.toHaveBeenCalled();
      page.topId.set(TOP.id);
      view.treeApi.tree.mockReturnValueOnce(throwError(() => problem(0)));
      view.treeApi.changed.next();
      expect(view.navigate).toHaveBeenCalled();
    });

    it('§F/finance/budget/000851: the first tree read does not replace the tree of a later read', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const older = new Subject<BudgetTreeNode[]>();
      const newer = new Subject<BudgetTreeNode[]>();
      view.treeApi.tree.mockReturnValueOnce(older).mockReturnValueOnce(newer);
      const page = view.fixture.componentInstance as unknown as { tree(): BudgetTreeNode[]; retry(): void };
      page.retry();
      view.treeApi.changed.next();
      newer.next([{ ...TOP, name: 'Neu' }, QSM]);
      older.next([{ ...TOP, name: 'Alt' }, QSM]);
      expect(page.tree()[0].name).toBe('Neu');
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

  describe('sides', () => {
    const select = () => screen.getByRole('combobox', { name: /Seite/ });

    it('§F/finance/budget/000853: the line of a Titel sets its side in a draft, and a Kostenstelle below it has no side field', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      await waitFor(() => expect(select()).toHaveTextContent('Einnahme'));
      expect(view.container.querySelector('app-cost-centre-settings [name^="cc-side"]')).toBeNull();
      const late = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(late);
      await userEvent.click(select());
      await userEvent.click(await screen.findByRole('option', { name: 'Ausgabe' }));
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'fees', { side: 'expense' });
      expect(select()).toHaveTextContent('Ausgabe');
      late.next(plan([version({ lines: [line('fees', '100', { side: 'expense' }), line('grants', '30')] })]));
      late.complete();
      view.fixture.detectChanges();
      expect(texts(view, '.bp__group')).toEqual(['Einnahmen0 €', 'Ausgaben130 €']);
      expect(screen.getByRole('heading', { name: 'Vermerke' })).toBeInTheDocument();
      await userEvent.click(select());
      await userEvent.click(await screen.findByRole('option', { name: 'Ausgabe' }));
      expect(view.api.setLine).toHaveBeenCalledTimes(1);
      view.fixture.componentInstance.saveSide(view.fixture.componentInstance.rows()[0], null);
      expect(view.api.setLine).toHaveBeenCalledTimes(1);
      await userEvent.click(treeRow(view, 'Zuschüsse'));
      expect(select()).toHaveTextContent('Ausgabe');
      const below = await setup({ query: { costCentre: 'wages' } });
      expect(below.container.querySelector('[name^="line-side"]')).toBeNull();
    });

    it('§F/finance/budget/000853: a version that left the draft shows the side and takes no change', async () => {
      await setup({ plans: { 'fy-26': plan([version({ state: 'in_force' })]) }, query: { costCentre: 'fees' } });
      await waitFor(() => expect(select()).toHaveTextContent('Einnahme'));
      expect(select()).toBeDisabled();
    });

    it('§F/finance/budget/000853: lists a Titel without a side in its own group and keeps the version in the draft', async () => {
      const lines = [line('noside', '5'), line('fees', '30'), line('grants', '30')];
      const view = await setup({ plans: { 'fy-26': plan([version({ lines })]) } });
      expect(texts(view, '.bp__group')).toEqual(['Ohne Seite', 'Einnahmen30 €', 'Ausgaben30 €']);
      expect(texts(view, '.bd__tree .tn__name')).toEqual(['VS-Mittel', 'Ohne Seite', 'Beiträge', 'Zuschüsse']);
      expect(screen.getByRole('heading', { level: 3, name: 'Ohne Seite' })).toBeInTheDocument();
      expect(primary()).toBeDisabled();
      expect(primary()).toHaveAttribute('title', 'Jeder Titel braucht eine Seite.');
      await userEvent.click(treeRow(view, 'Ohne Seite'));
      expect(text(view.container.querySelector('.bd__line'))).toContain('Ohne Seite');
      expect(select()).toHaveAttribute('aria-required', 'true');
      expect(screen.queryByRole('heading', { name: 'Vermerke' })).toBeNull();
      await userEvent.click(select());
      await userEvent.click(await screen.findByRole('option', { name: 'Einnahme' }));
      expect(view.api.setLine).toHaveBeenCalledWith('v0', 'noside', { side: 'income' });
    });

    it('§F/finance/budget/000853: names the cause of a refused side', async () => {
      const view = await setup({ query: { costCentre: 'fees' } });
      const refused = new Subject<BudgetPlan>();
      view.api.setLine.mockReturnValueOnce(refused);
      await userEvent.click(select());
      await userEvent.click(await screen.findByRole('option', { name: 'Ausgabe' }));
      await waitFor(() => expect(select()).toHaveTextContent('Ausgabe'));
      refused.error(problem(422, 'plan_side_missing'));
      view.fixture.detectChanges();
      expect(view.error).toHaveBeenCalledWith('Jeder Titel braucht eine Seite.');
      await waitFor(() => expect(select()).toHaveTextContent('Einnahme'));
    });
  });

  describe('state by hand', () => {
    const PERMS = ['budget.view', 'budget.structure', 'budget.plan.set_state'];
    const stepped = (over: Parameters<typeof version>[0] = {}) => plan([version({ steps: STEPS, ...over })]);
    const dialog = () => screen.findByRole('dialog', { name: 'Zustand setzen' });
    async function pickState(scope: HTMLElement, option: string): Promise<void> {
      await userEvent.click(within(scope).getByRole('combobox', { name: /Zustand/ }));
      await userEvent.click(await screen.findByRole('option', { name: option }));
    }
    const options = async (scope: HTMLElement) => {
      await userEvent.click(within(scope).getByRole('combobox', { name: /Zustand/ }));
      const names = (await screen.findAllByRole('option')).map(text);
      await userEvent.keyboard('{Escape}');
      return names;
    };

    it('§F/finance/budget/000855 §F/finance/budget/000840: sets a step by hand with a reason and reads the allocations again', async () => {
      const view = await setup({ perms: PERMS, plans: { 'fy-26': stepped() } });
      await choose('Zustand setzen');
      const open = await dialog();
      const save = within(screen.getByTestId('bp-state-save')).getByRole('button');
      expect(save).toBeDisabled();
      await pickState(open, 'Genehmigung');
      expect(save).toBeDisabled();
      expect(within(open).queryByText(/Danach ändert nur ein Nachtrag/)).toBeNull();
      await userEvent.type(within(open).getByRole('textbox', { name: /Begründung/ }), ' Beschluss vom 3. März ');
      await userEvent.click(save);
      expect(view.api.setStateByHand).toHaveBeenCalledWith('v0', { state: 'in_progress', step: 1, reason: 'Beschluss vom 3. März' });
      expect(view.success).toHaveBeenCalledWith('Der Zustand ist gesetzt.');
      expect(view.treeApi.tree).toHaveBeenCalledTimes(2);
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Zustand setzen' })).toBeNull());
    });

    it('§F/finance/budget/000855: offers each state but the own one and names what a version in force does', async () => {
      const view = await setup({ perms: PERMS, plans: { 'fy-26': stepped() } });
      await choose('Zustand setzen');
      const open = await dialog();
      expect(await options(open)).toEqual(['Beschluss', 'Genehmigung', 'In Kraft']);
      await pickState(open, 'In Kraft');
      expect(within(open).getByText(/Danach ändert nur ein Nachtrag/)).toBeInTheDocument();
      await userEvent.type(within(open).getByRole('textbox', { name: /Begründung/ }), 'Altbestand{Enter}');
      fireEvent.submit(open.querySelector('form') as HTMLFormElement);
      expect(view.api.setStateByHand).toHaveBeenCalledWith('v0', { state: 'in_force', step: null, reason: 'Altbestand' });
      expect(view.api.setStateByHand).toHaveBeenCalledTimes(1);

      await setup({ perms: PERMS, plans: { 'fy-26': stepped({ state: 'in_progress', steps: passed(1) }) } });
      await choose('Zustand setzen');
      expect(await options(await dialog())).toEqual(['Entwurf', 'Beschluss', 'In Kraft']);
      await setup({ perms: PERMS, plans: { 'fy-26': stepped({ state: 'in_progress', steps: passed(2) }) } });
      await choose('Zustand setzen');
      expect(await options(await dialog())).toEqual(['Entwurf', 'Beschluss', 'Genehmigung', 'In Kraft']);
      await setup({ perms: PERMS, plans: { 'fy-26': stepped({ state: 'in_force', steps: passed(2) }) } });
      await choose('Zustand setzen');
      const last = await dialog();
      expect(await options(last)).toEqual(['Entwurf', 'Beschluss', 'Genehmigung']);
      await userEvent.click(within(last).getByRole('button', { name: 'Abbrechen' }));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Zustand setzen' })).toBeNull());
    });

    it('§F/finance/budget/000855: only the own permission, an open year and the newest version offer the action', async () => {
      await setup({ plans: { 'fy-26': stepped() } });
      expect(await openMenu()).not.toContain('Zustand setzen');
      await setup({ perms: PERMS, years: [FY25, fy('fy-26', 2026, { closedAt: '2026-05-01T00:00:00Z' })], plans: { 'fy-26': stepped() } });
      expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).toBeNull();
      const two = plan([version({ id: 'old', state: 'in_force' }), version({ id: 'new', number: 1 })]);
      const view = await setup({ perms: PERMS, plans: { 'fy-26': two }, query: { version: '0' } });
      expect(view.fixture.componentInstance.canSetState()).toBe(false);
      await pickChip(/^Version/, '1. Nachtrag');
      expect(view.fixture.componentInstance.canSetState()).toBe(true);
      const none = await setup({ perms: PERMS, plans: {} });
      expect(none.fixture.componentInstance.canSetState()).toBe(false);
      expect(none.fixture.componentInstance.stateOptions()).toEqual([]);
      none.fixture.componentInstance.setStateByHand(new Event('submit'));
      expect(none.api.setStateByHand).not.toHaveBeenCalled();
    });

    it('§F/finance/budget/000855: a step that was passed by hand says so under its date', async () => {
      const steps = [{ ...STEPS[0], passedAt: '2026-01-14T00:00:00Z', byHand: true }, STEPS[1]];
      const view = await setup({ plans: { 'fy-26': stepped({ state: 'in_progress', steps }) } });
      expect(text(view.container.querySelector('.bp__stepper'))).toContain('14.01.2026 · von Hand');
    });
  });
});
