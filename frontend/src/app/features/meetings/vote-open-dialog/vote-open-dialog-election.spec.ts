import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Attendance, Meeting } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { VoteOpenDialogComponent } from './vote-open-dialog.component';

const MEETING = {
  id: 'm-1',
  title: '34. Sitzung',
  status: 'live',
  votes: [],
  publicJoin: true,
  guestsMode: 'vote',
  admittedGuests: 4,
} as unknown as Meeting;
const APP_TOP: AgendaItem = { id: 't-3', applicationId: 'a-1', title: 'Zuschuss Party', position: 2 };
const FREE_TOP: AgendaItem = { id: 't-8', applicationId: null, title: 'Wahlen', position: 7 };

const member = (id: string, name: string): Attendance =>
  ({ principalId: id, displayName: name, email: null, status: 'present' }) as Attendance;
const MEMBERS = [member('p-1', 'Anna Berg'), member('p-2', 'Ben Ott')];

async function setup(item: AgendaItem = FREE_TOP) {
  const opened = jest.fn();
  const view = await render(VoteOpenDialogComponent, {
    inputs: { meeting: MEETING, item, topNumber: 8, members: MEMBERS },
    on: { opened },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  return { ...view, http, cmp: view.fixture.componentInstance, opened };
}

const submitButton = () =>
  screen.getAllByRole('button', { name: 'Wahl öffnen' }).find((b) => b.closest('.dialog__footer')) as HTMLElement;

describe('VoteOpenDialogComponent · election (F2)', () => {
  it('offers no election on an application item', async () => {
    const { cmp } = await setup(APP_TOP);
    expect(screen.queryByRole('radio', { name: 'Wahl' })).toBeNull();
    cmp.setKind('election');
    expect(cmp.kind()).toBe('motion');
  });

  it('builds an election: round, seats, members and free names, reorder, remove', async () => {
    const { http, cmp, opened, container, fixture } = await setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole('radio', { name: 'Wahl' }));
    expect(screen.getByRole('switch', { name: 'Geheime Wahl' })).toHaveAttribute('aria-checked', 'true');
    // Guests vote in an election only when the lead switches them on.
    expect(screen.getByRole('switch', { name: 'Gäste stimmen mit ab' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    const round = screen.getByLabelText('Wahlgang');
    await user.clear(round);
    await user.type(round, 'Wahl der Referate');
    await user.click(screen.getByRole('button', { name: 'Ein Posten mehr' }));
    expect(cmp.seats()).toBe(2);
    expect(screen.getByText('Für 2 Posten braucht es mindestens 2 Kandidierende.')).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
    expect(screen.getByText(/Jede Person hat 2 Stimmen/)).toBeInTheDocument();

    cmp.addMember('p-2');
    await user.type(screen.getByLabelText('Freier Name'), '  Cem Aydin {Enter}');
    cmp.addMember('p-1');
    cmp.addMember('p-1'); // a person is a candidate once
    cmp.addMember('p-x'); // not on the roster
    cmp.addFreeName(); // the field is empty again
    // A free name that is already on the list stays out (case and spaces ignored).
    await user.type(screen.getByLabelText('Freier Name'), 'cem  AYDIN');
    expect(screen.getByText('Dieser Name steht schon auf der Liste.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hinzufügen' })).toBeDisabled();
    cmp.addFreeName();
    cmp.freeName.set('');
    // A roster member picked after a free name of the same spelling: the server
    // refuses the pair, so the dialog blocks the submit until one entry goes.
    cmp.removeCandidate(cmp.candidates().find((c) => c.principalId === 'p-1')!.key);
    cmp.freeName.set('Anna Berg');
    cmp.addFreeName();
    cmp.addMember('p-1');
    fixture.detectChanges();
    expect(cmp.nameTwice()).toBe(true);
    expect(screen.getByText(/Ein freier Name steht doppelt/)).toBeInTheDocument();
    expect(cmp.canSubmit()).toBe(false);
    cmp.removeCandidate(cmp.candidates().find((c) => c.name === 'Anna Berg' && !c.principalId)!.key);
    fixture.detectChanges();
    expect(cmp.nameTwice()).toBe(false);
    view(cmp).toEqual(['Ben Ott', 'Cem Aydin', 'Anna Berg']);
    await user.click(screen.getByRole('button', { name: 'Anna Berg nach oben' }));
    view(cmp).toEqual(['Ben Ott', 'Anna Berg', 'Cem Aydin']);
    await user.click(screen.getByRole('button', { name: 'Ben Ott nach unten' }));
    view(cmp).toEqual(['Anna Berg', 'Ben Ott', 'Cem Aydin']);
    cmp.moveCandidate(0, -1); // the first one stays first
    await user.click(screen.getByRole('button', { name: 'Ben Ott entfernen' }));
    view(cmp).toEqual(['Anna Berg', 'Cem Aydin']);
    expect(await runAxe(container)).toHaveNoViolations();

    await user.click(submitButton());
    const req = http.expectOne('/api/meetings/m-1/votes');
    expect(req.request.body).toEqual({
      agendaItemId: 't-8',
      kind: 'election',
      question: 'Wahl der Referate',
      seats: 2,
      candidates: [{ name: 'Anna Berg', principalId: 'p-1' }, { name: 'Cem Aydin' }],
      secret: true,
      guestsVote: false,
    });
    req.flush({ ...MEETING, votes: [], createdAt: 'x' });
    expect(opened).toHaveBeenCalled();
  });

  it('names the Ja/Nein rule of a single candidate and keeps the seats in bounds', async () => {
    const { cmp } = await setup();
    cmp.setKind('election');
    cmp.changeSeats(-1);
    expect(cmp.seats()).toBe(1);
    cmp.changeSeats(100);
    expect(cmp.seats()).toBe(50);
    cmp.changeSeats(-49);
    expect(cmp.ruleSentence()).toMatch(/Jede Person hat eine Stimme/);
    cmp.addMember('p-1');
    expect(cmp.ruleSentence()).toMatch(/Eine Kandidatur/);
    // No name: no submit.
    cmp.question.set('  ');
    expect(cmp.canSubmit()).toBe(false);
    cmp.setKind('nonsense');
    expect(cmp.kind()).toBe('election');
    cmp.setKind('motion');
    expect(cmp.canSubmit()).toBe(true);
  });

  it('names a roster member without a name by the e-mail, else by the id', async () => {
    const { cmp, fixture } = await setup();
    fixture.componentRef.setInput('members', [
      { principalId: 'p-7', displayName: null, email: 'mia@x.de', status: 'present' } as Attendance,
      { principalId: 'p-8', displayName: null, email: null, status: 'present' } as Attendance,
    ]);
    expect(cmp.memberOptions()).toEqual([
      { value: 'p-7', label: 'mia@x.de' },
      { value: 'p-8', label: 'p-8' },
    ]);
    cmp.addMember('p-7');
    cmp.addMember('p-8');
    expect(cmp.candidates().map((c) => c.name)).toEqual(['mia@x.de', 'p-8']);
    expect(cmp.memberOptions()).toEqual([]);
  });
});

/** The names of the candidate list, in order. */
function view(cmp: VoteOpenDialogComponent) {
  return expect(cmp.candidates().map((c) => c.name));
}
