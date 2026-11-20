import { Subject, of, throwError } from 'rxjs';
import { render, type RenderResult, screen } from '@testing-library/angular';
import { ApiClient } from '@core/api/api-client.service';
import type { BulkItemResult, BulkTransitionOption } from '@core/api/models';
import { BulkDialogComponent, type BulkMode, type BulkTarget } from './bulk-dialog.component';

const TARGETS: readonly BulkTarget[] = [
  { id: 'a-1', title: 'Sommerfest' },
  { id: 'a-2', title: 'Flyer' },
];

const APPROVE: BulkTransitionOption = {
  toStateId: 's-ok',
  label: 'Annehmen',
  color: null,
  approves: true,
  amounts: [
    { applicationId: 'a-1', title: null, amount: '1250.00' },
    { applicationId: 'a-2', title: '  ', amount: null },
    { applicationId: 'a-9', title: null, amount: 'abc' },
  ],
  applicationIds: ['a-1', 'a-2'],
};

interface Api {
  bulkTransitions: jest.Mock;
  fireBulkTransition: jest.Mock;
  bulkComment: jest.Mock;
}

async function setup(
  mode: BulkMode,
  api: Partial<Api> = {},
): Promise<{ view: RenderResult<BulkDialogComponent>; cmp: BulkDialogComponent; api: Api }> {
  const full: Api = {
    bulkTransitions: jest.fn(() => of([APPROVE])),
    fireBulkTransition: jest.fn(() => of([])),
    bulkComment: jest.fn(() => of([])),
    ...api,
  };
  const view = await render(BulkDialogComponent, {
    providers: [{ provide: ApiClient, useValue: full }],
    componentInputs: { mode, targets: TARGETS },
  });
  const cmp = view.fixture.componentInstance;
  cmp.open.set(true);
  view.fixture.detectChanges();
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { view, cmp, api: full };
}

describe('BulkDialogComponent (001700-001704)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the amounts with title and money fallbacks', async () => {
    const { cmp, view } = await setup('transition');
    expect(cmp.canConfirm()).toBe(false);
    cmp.pick.set('s-ok');
    view.fixture.detectChanges();
    const amounts = cmp.amounts();
    expect(amounts.map((a) => a.title)).toEqual(['Sommerfest', 'Flyer', expect.any(String)]);
    expect(amounts[0].amount).toContain('1.250,00');
    expect(amounts[1].amount).toBe('');
    expect(amounts[2].amount).toBe('abc');
    expect(screen.getByTestId('bulk-amounts')).toBeTruthy();
  });

  /** § 001704: a status that only some Anträge reach says how many and names the others. */
  it('names the Anträge that the chosen status skips', async () => {
    const half: BulkTransitionOption = {
      toStateId: 's-back',
      label: 'Zurückgestellt',
      color: null,
      approves: false,
      amounts: [],
      applicationIds: ['a-1'],
    };
    const { cmp, view } = await setup('transition', {
      bulkTransitions: jest.fn(() => of([APPROVE, half])),
    });
    expect(screen.getByText('1 von 2')).toBeTruthy();
    expect(screen.queryByText('2 von 2')).toBeNull();
    expect(cmp.skipped()).toEqual([]);
    cmp.pick.set('s-back');
    view.fixture.detectChanges();
    expect(cmp.skipped().map((t) => t.title)).toEqual(['Flyer']);
    expect(screen.getByTestId('bulk-skipped').textContent).toContain('Flyer');
    expect(screen.getByRole('dialog', { name: /Status setzen/ })).toBeTruthy();
  });

  it('shows the error when the targets do not load', async () => {
    const { cmp } = await setup('transition', {
      bulkTransitions: jest.fn(() => throwError(() => new Error('x'))),
    });
    expect(cmp.failed()).toBe(true);
    expect(cmp.loading()).toBe(false);
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('shows the empty state when no target fits', async () => {
    const { cmp } = await setup('transition', { bulkTransitions: jest.fn(() => of([])) });
    expect(cmp.options()).toEqual([]);
    expect(cmp.chosen()).toBeNull();
    expect(cmp.amounts()).toEqual([]);
  });

  it('drops an answer that comes after the dialog opened again', async () => {
    const first = new Subject<BulkTransitionOption[]>();
    const failing = new Subject<BulkTransitionOption[]>();
    const answers = [first, failing, of([APPROVE])];
    const { cmp, view } = await setup('transition', {
      bulkTransitions: jest.fn(() => answers.shift()),
    });
    cmp.open.set(false);
    view.fixture.detectChanges();
    cmp.open.set(true);
    view.fixture.detectChanges();
    cmp.open.set(false);
    view.fixture.detectChanges();
    cmp.open.set(true);
    view.fixture.detectChanges();
    first.next([]);
    failing.error(new Error('late'));
    expect(cmp.options()).toEqual([APPROVE]);
    expect(cmp.failed()).toBe(false);
  });

  it('fires the transition and lists ok and error lines', async () => {
    const results: BulkItemResult[] = [
      { applicationId: 'a-1', ok: true },
      { applicationId: 'a-2', ok: false, error: 'Übergang nicht verfügbar' },
      { applicationId: 'a-9', ok: false },
      { applicationId: 'a-3', ok: false, code: 'transition_not_available', error: 'x' },
    ];
    const { cmp, api, view } = await setup('transition', {
      fireBulkTransition: jest.fn(() => of(results)),
    });
    const done = jest.fn();
    cmp.done.subscribe(done);
    cmp.submit();
    expect(api.fireBulkTransition).not.toHaveBeenCalled();
    cmp.pick.set('s-ok');
    cmp.submit();
    view.fixture.detectChanges();
    expect(api.fireBulkTransition).toHaveBeenCalledWith(['a-1', 'a-2'], 's-ok');
    expect(done).toHaveBeenCalled();
    expect(cmp.okCount()).toBe(1);
    expect(cmp.results()?.map((r) => r.text)[1]).toBe('Übergang nicht verfügbar');
    expect(cmp.results()?.[2].text).not.toBe('');
    expect(cmp.results()?.[3].text).toBe('Übersprungen: Status nicht erlaubt');
    expect(cmp.canConfirm()).toBe(false);
    cmp.close();
    expect(cmp.open()).toBe(false);
  });

  it('sends the message and shows the error of a failed send', async () => {
    const { cmp, api, view } = await setup('message', {
      bulkComment: jest.fn(() => throwError(() => new Error('x'))),
    });
    expect(api.bulkTransitions).not.toHaveBeenCalled();
    expect(cmp.canConfirm()).toBe(false);
    cmp.body.set('  Hallo  ');
    expect(cmp.canConfirm()).toBe(true);
    cmp.submit();
    view.fixture.detectChanges();
    expect(api.bulkComment).toHaveBeenCalledWith(['a-1', 'a-2'], 'Hallo');
    expect(cmp.running()).toBe(false);
    expect(cmp.failed()).toBe(true);
    expect(cmp.results()).toBeNull();
    expect(cmp.title()).not.toBe('');
  });
});
