import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Meeting } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { VoteOpenDialogComponent } from './vote-open-dialog.component';

const MEETING = {
  id: 'm-1',
  title: '34. Sitzung',
  status: 'live',
  isProtokollant: true,
  votes: [],
  publicJoin: false,
  guestsMode: 'watch',
  admittedGuests: 0,
} as unknown as Meeting;
const APP_TOP: AgendaItem = { id: 't-3', applicationId: 'a-1', title: 'Zuschuss Party', position: 2 };
const FREE_TOP: AgendaItem = { id: 't-8', applicationId: null, title: 'Sommerfest', position: 7 };

async function setup(item: AgendaItem = FREE_TOP) {
  const opened = jest.fn();
  const view = await render(VoteOpenDialogComponent, {
    inputs: { meeting: MEETING, item, topNumber: 8 },
    on: { opened },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  return { ...view, http, cmp: view.fixture.componentInstance, opened };
}

const footerButton = (name: string) =>
  screen.getAllByRole('button', { name }).find((b) => b.closest('.dialog__footer')) as HTMLElement;

describe('VoteOpenDialogComponent · poll', () => {
  it('offers no poll on an application item', async () => {
    const { cmp } = await setup(APP_TOP);
    expect(screen.queryByRole('radio', { name: 'Umfrage' })).toBeNull();
    cmp.setKind('poll');
    expect(cmp.kind()).toBe('motion');
  });

  it('builds a single poll: question, options, reorder, remove, open', async () => {
    const { http, cmp, opened, container } = await setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole('radio', { name: 'Umfrage' }));
    expect(screen.getByRole('heading', { name: 'Umfrage öffnen' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Einzelwahl' })).toHaveAttribute('aria-checked', 'true');
    // A poll is open unless the lead switches the secrecy on.
    expect(screen.getByRole('switch', { name: 'Geheime Umfrage' })).toHaveAttribute('aria-checked', 'false');
    // No majority rule and no stepper for a single poll.
    expect(screen.queryByText('Höchstens wählbar')).toBeNull();

    const question = screen.getByLabelText('Frage');
    await user.clear(question);
    await user.type(question, 'Wohin geht der Ausflug?');
    const add = screen.getByRole('button', { name: 'Hinzufügen' });
    expect(add).toBeDisabled();
    await user.type(screen.getByLabelText('Neue Option'), 'Stuttgart{Enter}');
    // One option is too few.
    expect(footerButton('Umfrage öffnen')).toBeDisabled();
    await user.type(screen.getByLabelText('Neue Option'), 'Tübingen');
    await user.click(add);
    await user.type(screen.getByLabelText('Neue Option'), 'Ulm{Enter}');
    // A label on the list already stays out (case and spaces ignored).
    await user.type(screen.getByLabelText('Neue Option'), '  ulm ');
    expect(add).toBeDisabled();
    await user.clear(screen.getByLabelText('Neue Option'));

    await user.click(screen.getByRole('button', { name: 'Ulm nach oben' }));
    await user.click(screen.getByRole('button', { name: 'Stuttgart entfernen' }));
    expect(screen.getAllByRole('listitem').map((li) => li.textContent?.trim())).toEqual([
      expect.stringContaining('Ulm'),
      expect.stringContaining('Tübingen'),
    ]);
    expect(cmp.canSubmit()).toBe(true);
    await user.click(screen.getByRole('switch', { name: 'Geheime Umfrage' }));
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(footerButton('Umfrage öffnen'));
    const req = http.expectOne('/api/meetings/m-1/votes');
    expect(req.request.body).toEqual({
      agendaItemId: 't-8',
      kind: 'poll',
      question: 'Wohin geht der Ausflug?',
      poll: { mode: 'single', options: [{ label: 'Ulm' }, { label: 'Tübingen' }] },
      secret: true,
    });
    req.flush({ ...MEETING, votes: [], createdAt: 'x' });
    expect(opened).toHaveBeenCalled();
  });

  it('a multi poll sends its limit; a poll needs its question', async () => {
    const { http, cmp } = await setup();
    const user = userEvent.setup();
    cmp.setKind('poll');
    await user.click(await screen.findByRole('radio', { name: 'Mehrfachwahl' }));
    for (const label of ['A', 'B', 'C']) {
      await user.type(screen.getByLabelText('Neue Option'), `${label}{Enter}`);
    }
    expect(screen.getByText('Höchstens wählbar')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Eine Option weniger' }));
    cmp.question.set('  ');
    expect(cmp.canSubmit()).toBe(false);
    cmp.question.set('Was essen wir?');
    expect(cmp.canSubmit()).toBe(true);
    // "Vorbereiten" saves a draft.
    cmp.submit(true);
    const req = http.expectOne('/api/meetings/m-1/votes');
    expect(req.request.body).toEqual({
      agendaItemId: 't-8',
      kind: 'poll',
      question: 'Was essen wir?',
      poll: { mode: 'multi', options: [{ label: 'A' }, { label: 'B' }, { label: 'C' }], maxChoices: 1 },
      secret: false,
      draft: true,
    });
  });

  it('a date poll lists "Termine" from Datum, Beginn and Ende', async () => {
    const { http, cmp } = await setup();
    cmp.setKind('poll');
    cmp.question.set('Wann treffen wir uns?');
    cmp.poll.set({
      mode: 'date',
      maxChoices: 2,
      options: [
        { key: 1, label: 'Text bleibt', date: '', start: '', end: '' },
        { key: 2, label: '', date: '2026-11-03', start: '18:00', end: '20:00' },
        { key: 3, label: '', date: '2026-11-04', start: '17:00', end: '' },
      ],
    });
    await screen.findByText('Termine');
    expect(screen.getByLabelText('Datum')).toBeInTheDocument();
    expect(screen.getByLabelText('Beginn')).toBeInTheDocument();
    expect(screen.getByLabelText('Ende')).toBeInTheDocument();
    cmp.submit(false);
    const body = http.expectOne('/api/meetings/m-1/votes').request.body;
    expect(body.poll.mode).toBe('date');
    expect(body.poll.options).toEqual([
      { start: new Date('2026-11-03T18:00').toISOString(), end: new Date('2026-11-03T20:00').toISOString() },
      { start: new Date('2026-11-04T17:00').toISOString() },
    ]);
    expect(body.poll.maxChoices).toBeUndefined();
  });

  it('switching back to a motion keeps the motion body', async () => {
    const { cmp } = await setup();
    cmp.setKind('poll');
    expect(cmp.isPoll()).toBe(true);
    expect(cmp.canSubmit()).toBe(false);
    cmp.setKind('motion');
    expect(cmp.isPoll()).toBe(false);
    expect(cmp.canSubmit()).toBe(true);
  });
});
