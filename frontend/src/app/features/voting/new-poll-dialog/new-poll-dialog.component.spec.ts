import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import type { CircularCreateBody, PollCreateBody, Vote } from '@core/api/models';
import { AdminOptionsService } from '../../../pages/admin/admin-options.service';
import { NewPollDialogComponent } from './new-poll-dialog.component';

/** A fixed local "now": 22 Oct 2026, 12:00. */
const NOW = new Date(2026, 9, 22, 12, 0).getTime();

/** The user has vote.manage in g1 and g2, not in g3. */
async function setup(
  opts: { gremien?: { value: string; label: string }[]; fail?: boolean; optionsFail?: boolean; gremiumId?: string; rulesFail?: boolean } = {},
) {
  const createPoll = jest.fn((_body: PollCreateBody) =>
    opts.fail ? throwError(() => new Error('boom')) : of({ id: 'p1' } as Vote),
  );
  const createCircular = jest.fn((_body: CircularCreateBody) =>
    opts.fail ? throwError(() => new Error('boom')) : of({ id: 'c1' } as Vote),
  );
  const circularRules = jest.fn(() =>
    opts.rulesFail ? throwError(() => new Error('x')) : of({ minDays: 5 }),
  );
  const gremien = opts.gremien ?? [
    { value: 'g1', label: 'STUPA' },
    { value: 'g2', label: 'AStA' },
    { value: 'g3', label: 'Fachschaft' },
  ];
  const created = jest.fn();
  const closed = jest.fn();
  const view = await render(NewPollDialogComponent, {
    inputs: { open: true, gremiumId: opts.gremiumId ?? '' },
    on: { created, closed },
    providers: [
      { provide: ApiClient, useValue: { createPoll, createCircular, circularRules } },
      { provide: AuthService, useValue: { canInGremium: (id: string) => id !== 'g3' } },
      {
        provide: AdminOptionsService,
        useValue: {
          gremiumOptions: () => (opts.optionsFail ? throwError(() => new Error('x')) : of(gremien)),
        },
      },
    ],
  });
  return { ...view, cmp: view.fixture.componentInstance, createPoll, createCircular, created, closed };
}

/** Fill a valid single poll of g1 that ends tomorrow at 18:00. */
function fill(cmp: NewPollDialogComponent): void {
  cmp.gremium.set('g1');
  cmp.question.set(' Wohin? ');
  cmp.draft.set({
    mode: 'single',
    maxChoices: 2,
    options: [
      { key: 1, label: 'Ulm', date: '', start: '', end: '' },
      { key: 2, label: 'Tübingen', date: '', start: '', end: '' },
    ],
  });
  cmp.endDate.set('2026-10-23');
  cmp.endTime.set('18:00');
}

describe('NewPollDialogComponent', () => {
  beforeEach(() => jest.spyOn(Date, 'now').mockReturnValue(NOW));
  afterEach(() => jest.restoreAllMocks());

  it('offers the Gremien with vote.manage and the fields of the spec', async () => {
    const { cmp } = await setup();
    expect(cmp.gremiumOptions().map((o) => o.label)).toEqual(['STUPA', 'AStA']);
    expect(screen.getByRole('heading', { name: 'Abstimmung anlegen' })).toBeInTheDocument();
    expect(screen.getByLabelText('Frage')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Terminumfrage' })).toBeInTheDocument();
    expect(screen.getByLabelText(/Endet am/)).toBeInTheDocument();
    expect(screen.queryByRole('switch', { name: 'Geheime Umfrage' })).toBeNull();
    for (const name of ['Abbrechen', 'Als Entwurf speichern', 'Starten']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Starten' })).toBeDisabled();
  });

  it('preselects a single Gremium instead of one without the right', async () => {
    const { cmp } = await setup({ gremien: [{ value: 'g2', label: 'AStA' }], gremiumId: 'g3' });
    expect(cmp.gremium()).toBe('g2');
  });

  it('offers no Gremium when the list fails', async () => {
    const none = await setup({ optionsFail: true, gremiumId: 'g1' });
    expect(none.cmp.gremiumOptions()).toEqual([]);
    expect(none.cmp.gremium()).toBe('');
  });

  it('needs an end at least one hour ahead', async () => {
    const { cmp } = await setup();
    fill(cmp);
    expect(cmp.canSubmit()).toBe(true);
    cmp.endDate.set('2026-10-22');
    cmp.endTime.set('12:30');
    expect(cmp.endOk()).toBe(false);
    cmp.endTime.set('13:00');
    expect(cmp.endOk()).toBe(true);
    cmp.endTime.set('');
    expect(cmp.canSubmit()).toBe(false);
  });

  it('starts the poll, or saves it as a draft', async () => {
    const { cmp, fixture, createPoll, created } = await setup();
    const user = userEvent.setup();
    fill(cmp);
    fixture.detectChanges();
    await user.click(screen.getByRole('button', { name: 'Starten' }));
    expect(createPoll).toHaveBeenCalledWith({
      kind: 'poll',
      eligibleGroup: 'g1',
      question: 'Wohin?',
      mode: 'single',
      options: [{ label: 'Ulm' }, { label: 'Tübingen' }],
      secret: true,
      closesAt: new Date('2026-10-23T18:00').toISOString(),
      draft: false,
    });
    expect(created).toHaveBeenCalledWith({ id: 'p1' });
    cmp.submit(true);
    expect(createPoll).toHaveBeenLastCalledWith(expect.objectContaining({ draft: true }));
  });

  it('keeps the dialog on a failure and closes on "Abbrechen"', async () => {
    const { cmp, created, closed } = await setup({ fail: true });
    const user = userEvent.setup();
    fill(cmp);
    cmp.submit(false);
    expect(created).not.toHaveBeenCalled();
    expect(cmp.submitting()).toBe(false);
    cmp.question.set('');
    cmp.submit(false);
    await user.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(closed).toHaveBeenCalled();
  });

  describe('Umlaufverfahren (§000914)', () => {
    it('takes the Gremium, the question and the end only', async () => {
      const { cmp, fixture } = await setup();
      cmp.setKind('other');
      cmp.setKind(null);
      expect(cmp.circular()).toBe(false);
      cmp.setKind('circular');
      fixture.detectChanges();
      expect(screen.getByLabelText('Beschlussfrage')).toBeInTheDocument();
      expect(screen.queryByRole('radio', { name: 'Terminumfrage' })).toBeNull();
      expect(screen.getByRole('note')).toHaveTextContent('mindestens 5 Tage');
      cmp.setKind('poll');
      expect(cmp.circular()).toBe(false);
    });

    it('needs an end at least the days of the server ahead', async () => {
      const { cmp } = await setup();
      cmp.setKind('circular');
      cmp.gremium.set('g1');
      cmp.question.set(' Lastenanhänger beschaffen? ');
      cmp.endTime.set('12:00');
      cmp.endDate.set('2026-10-26');
      expect(cmp.canSubmit()).toBe(false);
      cmp.endDate.set('2026-10-27');
      expect(cmp.canSubmit()).toBe(true);
    });

    it('keeps three days when the rules do not load', async () => {
      const { cmp } = await setup({ rulesFail: true });
      expect(cmp.minDays()).toBe(3);
    });

    it('starts the Umlaufverfahren, or saves it as a draft', async () => {
      const { cmp, createCircular, createPoll, created } = await setup();
      cmp.setKind('circular');
      cmp.gremium.set('g1');
      cmp.question.set(' Lastenanhänger beschaffen? ');
      cmp.endDate.set('2026-11-02');
      cmp.endTime.set('18:00');
      cmp.submit(false);
      expect(createCircular).toHaveBeenCalledWith({
        kind: 'circular',
        eligibleGroup: 'g1',
        question: 'Lastenanhänger beschaffen?',
        closesAt: new Date('2026-11-02T18:00').toISOString(),
        draft: false,
      });
      expect(createPoll).not.toHaveBeenCalled();
      expect(created).toHaveBeenCalledWith({ id: 'c1' });
      cmp.submit(true);
      expect(createCircular).toHaveBeenLastCalledWith(expect.objectContaining({ draft: true }));
    });
  });
});
