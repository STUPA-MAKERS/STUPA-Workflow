import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import type { Vote } from '@core/api/models';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../testing/meeting-fixtures';
import { VoteCastComponent } from './vote-cast.component';
import { RailStatusService } from '../../layout/rail-status.service';

function vote(overrides: Partial<Vote> = {}): Vote {
  return {
    id: 'v1',
    applicationId: 'a1',
    meetingId: 'm1',
    agendaItemId: 'ag3',
    question: 'Soll der Antrag gefördert werden?',
    eligibleGroup: 'g1',
    config: { options: ['yes', 'no', 'abstain'], majorityRule: 'two_thirds' },
    status: 'open',
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    tally: { counts: {}, eligible: 12, voted: 5, present: 12, revealed: false, quorumMet: true, leading: null },
    ...overrides,
  };
}

/** A draft standalone vote: the only shape the delete route accepts. */
function draftVote(overrides: Partial<Vote> = {}): Vote {
  return vote({ status: 'draft', meetingId: null, ...overrides });
}

const NO_DELEGATION: VoteDelegationStatus = {
  blocked: false,
  delegatedToName: null,
  exercising: false,
  delegatedByName: null,
};

async function setup(opts: {
  vote?: Vote;
  getError?: unknown;
  castError?: unknown;
  /** The server flag `canCast` of the loaded vote (default true). */
  canCast?: boolean;
  /** The server flag `canManage` of the loaded vote (default false). */
  canManage?: boolean;
  delegation?: VoteDelegationStatus;
  delegationError?: boolean;
  routeId?: string | null;
  deleteError?: unknown;
  /** Gremium rights of the caller (`session.manage` gives the beamer). */
  sessionManage?: boolean;
  meetingError?: boolean;
} = {}) {
  // The server sets the capability flags of the caller on GET /votes/{id}.
  const served: Vote = {
    canCast: opts.canCast ?? true,
    canManage: opts.canManage ?? false,
    ...(opts.vote ?? vote()),
  };
  const getVote = opts.getError
    ? jest.fn(() => throwError(() => opts.getError))
    : jest.fn(() => of(served));
  const castBallot = opts.castError
    ? jest.fn(() => throwError(() => opts.castError))
    : jest.fn(() => of({ status: 'cast' as const }));
  const deleteVote = opts.deleteError
    ? jest.fn(() => throwError(() => opts.deleteError))
    : jest.fn(() => of(void 0));
  const getMeeting = jest.fn(() =>
    opts.meetingError
      ? throwError(() => ({ status: 403 }))
      : of({ id: 'm1', title: '34. Sitzung', gremiumId: 'g1' }),
  );
  const listAgenda = jest.fn(() =>
    of([
      { id: 'ag1', position: 0 },
      { id: 'ag2', position: 1 },
      { id: 'ag3', position: 2 },
    ]),
  );
  const api = { getVote, castBallot, deleteVote, getMeeting, listAgenda };
  const voteStatus = opts.delegationError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of(opts.delegation ?? NO_DELEGATION));
  const auth = {
    canInGremium: jest.fn(() => opts.sessionManage ?? false),
    canInAnyGremium: jest.fn(() => opts.sessionManage ?? false),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const railStatus = { refresh: jest.fn() };

  const id = opts.routeId === undefined ? 'v1' : opts.routeId;
  const r = await render(VoteCastComponent, {
    providers: [
      // The delete navigates away, so both target routes must resolve.
      provideRouter([
        { path: 'voting', children: [] },
        { path: 'voting/beamer/:id', children: [] },
        { path: 'applications/:id', children: [] },
        { path: 'meetings/:id', children: [] },
      ]),
      { provide: ApiClient, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: DelegationsApiService, useValue: { voteStatus } },
      { provide: ToastService, useValue: toast },
      { provide: RailStatusService, useValue: railStatus },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap(id === null ? {} : { id }) } },
      },
    ],
  });
  return { ...r, getVote, castBallot, deleteVote, getMeeting, voteStatus, toast, railStatus, auth };
}

/** Conflict answer with its machine code. */
function conflict(code: string) {
  return { status: 409, error: { type: `app://error/${code}`, title: 'Conflict', status: 409, code } };
}

const own = () => within(screen.getByRole('group', { name: 'Deine Stimme' }));
const confirmButton = () => screen.getByRole('button', { name: /abgeben/ });

async function castOwn(choice = 'Ja'): Promise<void> {
  await userEvent.click(own().getByRole('button', { name: choice }));
  await userEvent.click(confirmButton());
}

describe('VoteCastComponent', () => {
  it('shows the vote as a card with meeting, item and rule (board Arbeit-Abstimmungen)', async () => {
    const { getMeeting } = await setup();
    expect(screen.getByRole('heading', { level: 1, name: 'Abstimmungen' })).toBeInTheDocument();
    expect(screen.getByText('Offen')).toBeInTheDocument();
    expect(screen.getByText('34. Sitzung · TOP 3')).toBeInTheDocument();
    expect(screen.getByText('Zweidrittelmehrheit')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Soll der Antrag gefördert werden?' })).toBeInTheDocument();
    expect(screen.getByText('5 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
    expect(getMeeting).toHaveBeenCalledWith('m1', { quiet: true });
  });

  it('casts in two steps over REST and reloads the vote', async () => {
    const { castBallot, getVote, railStatus, toast } = await setup();
    await userEvent.click(own().getByRole('button', { name: 'Ja' }));
    expect(castBallot).not.toHaveBeenCalled();
    await userEvent.click(confirmButton());
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', false);
    expect(screen.getByText('Danke! Deine Stimme: Ja')).toBeInTheDocument();
    expect(railStatus.refresh).toHaveBeenCalled();
    expect(getVote).toHaveBeenLastCalledWith('v1', { quiet: true });
    // The ballot says thanks itself; no toast repeats it.
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('restores the lock from the server ballot', async () => {
    await setup({ vote: vote({ myBallot: { cast: true, choice: 'no' } }) });
    expect(screen.getByText('Danke! Deine Stimme: Nein')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
  });

  it('shows a cast secret ballot without its choice', async () => {
    await setup({ vote: vote({ secret: true, myBallot: { cast: true, choice: null } }) });
    expect(screen.getByText('Danke! Deine Stimme ist abgegeben.')).toBeInTheDocument();
  });

  it('gates the own ballot on canCast', async () => {
    await setup({ canCast: false });
    expect(screen.getByText('Du bist für diese Abstimmung nicht stimmberechtigt.')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Deine Stimme' })).not.toBeInTheDocument();
  });

  it('treats a 403 on load as not eligible', async () => {
    await setup({ getError: { status: 403 } });
    expect(screen.getByRole('alert')).toHaveTextContent('Du bist für diese Abstimmung nicht stimmberechtigt.');
    expect(screen.getByRole('link', { name: 'Zu den Abstimmungen' })).toBeInTheDocument();
  });

  it('shows an error box when the vote cannot be loaded', async () => {
    await setup({ getError: { status: 500 } });
    expect(screen.getByText('Abstimmung nicht verfügbar')).toBeInTheDocument();
  });

  it('goes straight to the error box without a vote id', async () => {
    const { getVote } = await setup({ routeId: null });
    expect(getVote).not.toHaveBeenCalled();
    expect(screen.getByText('Abstimmung nicht verfügbar')).toBeInTheDocument();
  });

  it('locks the ballot on a 409 already_voted and reloads', async () => {
    const { toast, getVote } = await setup({ castError: conflict('already_voted') });
    getVote.mockClear();
    await castOwn();
    expect(toast.error).toHaveBeenCalledWith('Du hast bereits abgestimmt.');
    expect(screen.getByText('Danke! Deine Stimme ist abgegeben.')).toBeInTheDocument();
    expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
  });

  it('reports another 409 as a vote that is no longer open', async () => {
    const { toast } = await setup({ castError: conflict('vote_not_open') });
    await castOwn();
    expect(toast.error).toHaveBeenCalledWith('Die Abstimmung ist nicht mehr offen.');
  });

  it('marks not eligible on a 403 from an own cast', async () => {
    const { toast } = await setup({ castError: { status: 403 } });
    await castOwn();
    expect(toast.error).toHaveBeenCalledWith('Du bist für diese Abstimmung nicht stimmberechtigt.');
    expect(screen.queryByRole('group', { name: 'Deine Stimme' })).not.toBeInTheDocument();
  });

  it('hides only the represented row on a 403 from a represented cast and reads the state again', async () => {
    const { getVote, voteStatus, toast } = await setup({
      castError: { status: 403 },
      delegation: { ...NO_DELEGATION, exercising: true, delegatedByName: 'Jonas Weber' },
    });
    getVote.mockClear();
    voteStatus.mockClear();
    const proxy = within(screen.getByRole('group', { name: 'Als Vertretung für Jonas Weber' }));
    await userEvent.click(proxy.getByRole('button', { name: 'Nein' }));
    await userEvent.click(confirmButton());
    expect(toast.error).toHaveBeenCalledWith('Du bist für diese Abstimmung nicht stimmberechtigt.');
    expect(screen.getByRole('group', { name: 'Deine Stimme' })).toBeInTheDocument();
    expect(
      screen.queryByRole('group', { name: 'Als Vertretung für Jonas Weber' }),
    ).not.toBeInTheDocument();
    expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
    expect(voteStatus).toHaveBeenCalledWith('v1');
  });

  it('explains a voting right handed over after the load, on a 403 from an own cast', async () => {
    const { voteStatus } = await setup({ castError: { status: 403 } });
    voteStatus.mockReturnValue(of({ ...NO_DELEGATION, blocked: true, delegatedToName: 'Mara Keller' }));
    await castOwn();
    expect(screen.getByText(/Mara Keller/)).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Deine Stimme' })).not.toBeInTheDocument();
  });

  it('shows the problem detail of another failure, or a generic text', async () => {
    const { toast } = await setup({ castError: { status: 500, error: { detail: 'Kaputt' } } });
    await castOwn();
    expect(toast.error).toHaveBeenCalledWith('Kaputt');
  });

  it('falls back to the generic failure text', async () => {
    const { toast } = await setup({ castError: { status: 500 } });
    await castOwn();
    expect(toast.error).toHaveBeenCalledWith('Stimme konnte nicht gezählt werden.');
  });

  it('explains a handed-over voting right instead of a bare hint', async () => {
    await setup({ delegation: { ...NO_DELEGATION, blocked: true, delegatedToName: 'Mara Keller' } });
    expect(screen.getByText(/Mara Keller/)).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Deine Stimme' })).not.toBeInTheDocument();
  });

  it('names an unknown delegate with a placeholder', async () => {
    await setup({ delegation: { ...NO_DELEGATION, blocked: true } });
    expect(screen.getByText(/an \? übertragen/)).toBeInTheDocument();
  });

  it('offers own and represented rows; the represented one casts with asDelegation', async () => {
    const { castBallot } = await setup({
      delegation: { ...NO_DELEGATION, exercising: true, delegatedByName: 'Jonas Weber' },
    });
    const proxy = within(screen.getByRole('group', { name: 'Als Vertretung für Jonas Weber' }));
    await userEvent.click(proxy.getByRole('button', { name: 'Enthaltung' }));
    await userEvent.click(confirmButton());
    expect(castBallot).toHaveBeenCalledWith('v1', 'abstain', true);
    await castOwn('Nein');
    expect(castBallot).toHaveBeenLastCalledWith('v1', 'no', false);
  });

  it('names an unknown represented member with a placeholder', async () => {
    await setup({ delegation: { ...NO_DELEGATION, exercising: true } });
    expect(screen.getByRole('group', { name: 'Als Vertretung für ?' })).toBeInTheDocument();
  });

  it('restores the represented lock from representedCast', async () => {
    await setup({
      vote: vote({ representedCast: true }),
      delegation: { ...NO_DELEGATION, exercising: true, delegatedByName: 'Jonas Weber' },
    });
    expect(screen.getByText('Für Jonas Weber abgegeben.')).toBeInTheDocument();
  });

  it('keeps the page when the delegation lookup fails', async () => {
    await setup({ delegationError: true });
    expect(screen.getByRole('group', { name: 'Deine Stimme' })).toBeInTheDocument();
  });

  it('shows the result of a closed vote without a ballot; a tie is Abgelehnt', async () => {
    await setup({
      vote: vote({
        status: 'closed',
        result: 'tie',
        tally: { counts: { yes: 3, no: 3, abstain: 1 }, eligible: 12, voted: 7, present: 0, revealed: true, quorumMet: true, leading: null },
      }),
    });
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /abgeben/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/stimmberechtigt/)).not.toBeInTheDocument();
  });

  describe('standalone vote without a meeting', () => {
    it('links its application and counts the eligible voters', async () => {
      const { getMeeting } = await setup({
        vote: vote({ meetingId: null, agendaItemId: null, tally: { counts: { yes: 1 }, eligible: 9, voted: 1, present: 0, revealed: true, quorumMet: false, leading: 'yes' } }),
      });
      expect(getMeeting).not.toHaveBeenCalled();
      expect(screen.getByRole('link', { name: 'Antrag öffnen' })).toHaveAttribute('href', '/applications/a1');
      expect(screen.getByText('1 von 9 Stimmberechtigten haben abgestimmt')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Beamer-Ansicht' })).not.toBeInTheDocument();
    });
  });

  describe('beamer', () => {
    it('links the beamer of the meeting for a person who runs it', async () => {
      const { auth, fixture } = await setup({ sessionManage: true });
      const router = fixture.debugElement.injector.get(Router);
      const navigate = jest.spyOn(router, 'navigate');
      expect(auth.canInGremium).toHaveBeenCalledWith('g1', 'session.manage');
      await userEvent.click(screen.getByRole('button', { name: 'Beamer-Ansicht' }));
      expect(navigate).toHaveBeenCalledWith(['/voting/beamer', 'm1']);
    });

    it('falls back to any gremium when the meeting is not readable', async () => {
      const { auth } = await setup({ sessionManage: true, meetingError: true });
      expect(auth.canInAnyGremium).toHaveBeenCalledWith('session.manage');
      expect(screen.getByRole('button', { name: 'Beamer-Ansicht' })).toBeInTheDocument();
    });

    it('offers no beamer to a member', async () => {
      await setup({ sessionManage: false });
      expect(screen.queryByRole('button', { name: 'Beamer-Ansicht' })).not.toBeInTheDocument();
    });

    it('does nothing without a link', async () => {
      const { fixture } = await setup({ sessionManage: false });
      const router = fixture.debugElement.injector.get(Router);
      const navigate = jest.spyOn(router, 'navigate');
      fixture.componentInstance.goBeamer();
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  describe('phone (board Telefon-Abstimmen)', () => {
    let restore: () => void;
    beforeEach(() => (restore = matchMediaQueries(MEDIA.phone)));
    afterEach(() => restore());

    it('shows the phone header with the way back to the meeting', async () => {
      await setup();
      expect(screen.getByRole('link', { name: 'Zurück' })).toHaveAttribute('href', '/meetings/m1');
      expect(screen.getByText('TOP 3 · 34. Sitzung')).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Abstimmungen' })).not.toBeInTheDocument();
      expect(document.querySelector('app-ballot')).toHaveClass('ballot--phone');
    });

    it('leads back to the application of a standalone vote', async () => {
      await setup({ vote: vote({ meetingId: null }) });
      expect(screen.getByRole('link', { name: 'Zurück' })).toHaveAttribute('href', '/applications/a1');
    });

    it('leads back to the overview without both', async () => {
      await setup({ vote: vote({ meetingId: null, applicationId: null }) });
      expect(screen.getByRole('link', { name: 'Zurück' })).toHaveAttribute('href', '/voting');
    });

    it('names only the meeting when the item is unknown', async () => {
      await setup({ vote: vote({ agendaItemId: null }) });
      expect(screen.getByText('34. Sitzung')).toBeInTheDocument();
    });

    it('puts the delete into the menu', async () => {
      await setup({ vote: draftVote(), canManage: true });
      await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
      await userEvent.click(screen.getByRole('menuitem', { name: 'Abstimmung löschen' }));
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('ignores an unknown menu item', async () => {
      const { fixture } = await setup({ vote: draftVote(), canManage: true });
      fixture.componentInstance.onMenu('other');
      expect(fixture.componentInstance.confirmDelete()).toBe(false);
    });
  });

  describe('delete', () => {
    it('deletes a draft standalone vote after the confirmation', async () => {
      const { deleteVote, toast } = await setup({ vote: draftVote(), canManage: true });
      await userEvent.click(screen.getAllByRole('button', { name: 'Abstimmung löschen' })[0]);
      const buttons = screen.getAllByRole('button', { name: 'Abstimmung löschen' });
      await userEvent.click(buttons[buttons.length - 1]);
      expect(deleteVote).toHaveBeenCalledWith('v1');
      expect(toast.success).toHaveBeenCalledWith('Abstimmung gelöscht.');
    });

    it('falls back to the vote overview when the vote carries no application', async () => {
      const { fixture, deleteVote } = await setup({
        vote: draftVote({ applicationId: null }),
        canManage: true,
      });
      fixture.componentInstance.doDelete();
      expect(deleteVote).toHaveBeenCalledWith('v1');
    });

    it('offers no delete without the server flag canManage', async () => {
      await setup({ vote: draftVote(), canManage: false });
      expect(screen.queryByRole('button', { name: 'Abstimmung löschen' })).not.toBeInTheDocument();
    });

    it('offers no delete for a vote that already opened', async () => {
      await setup({ vote: vote({ meetingId: null }), canManage: true });
      expect(screen.queryByRole('button', { name: 'Abstimmung löschen' })).not.toBeInTheDocument();
    });

    it('offers no delete for a meeting-bound draft', async () => {
      await setup({ vote: draftVote({ meetingId: 'm1' }), canManage: true });
      expect(screen.queryByRole('button', { name: 'Abstimmung löschen' })).not.toBeInTheDocument();
    });

    it.each([
      ['vote_not_draft', 'Die Abstimmung war bereits geöffnet. Statt zu löschen, brich sie ab.'],
      ['vote_has_ballots', 'Es liegen bereits Stimmen vor. Die Abstimmung lässt sich nicht mehr löschen.'],
      ['vote_meeting_bound', 'Diese Abstimmung gehört zu einer Sitzung. Sie wird dort gelöscht.'],
      ['something_else', 'Die Abstimmung ist in einem Zustand, der das Löschen ausschließt.'],
    ])('explains the 409 code %s and reloads the vote', async (code, message) => {
      const { fixture, toast, getVote } = await setup({
        vote: draftVote(),
        canManage: true,
        deleteError: conflict(code),
      });
      getVote.mockClear();
      fixture.componentInstance.doDelete();
      expect(toast.error).toHaveBeenCalledWith(message);
      expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
    });

    it('explains a 409 without a code', async () => {
      const { fixture, toast } = await setup({
        vote: draftVote(),
        canManage: true,
        deleteError: { status: 409 },
      });
      fixture.componentInstance.doDelete();
      expect(toast.error).toHaveBeenCalledWith(
        'Die Abstimmung ist in einem Zustand, der das Löschen ausschließt.',
      );
    });

    it.each([
      [403, 'Keine Berechtigung, diese Abstimmung zu löschen.'],
      [500, 'Die Abstimmung konnte nicht gelöscht werden.'],
    ])('reports a %s failure with its own message', async (status, message) => {
      const { fixture, toast } = await setup({
        vote: draftVote(),
        canManage: true,
        deleteError: { status },
      });
      fixture.componentInstance.doDelete();
      expect(toast.error).toHaveBeenCalledWith(message);
    });

    it('ignores a second delete while one runs', async () => {
      const { fixture, deleteVote } = await setup({ vote: draftVote(), canManage: true });
      fixture.componentInstance.deleting.set(true);
      fixture.componentInstance.doDelete();
      expect(deleteVote).not.toHaveBeenCalled();
    });

    it('cancels the confirmation', async () => {
      const { deleteVote } = await setup({ vote: draftVote(), canManage: true });
      await userEvent.click(screen.getAllByRole('button', { name: 'Abstimmung löschen' })[0]);
      await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' })[0]);
      expect(deleteVote).not.toHaveBeenCalled();
    });
  });
});
