import { signal } from '@angular/core';
import { ActivatedRoute, type ParamMap, Router, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject, Subject, of, throwError } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import type { Vote } from '@core/api/models';
import { LiveVoteService, type ConnectionState } from '@core/ws/live-vote.service';
import type { VoteClosedMsg, VoteOpenedMsg, VoteTallyMsg } from '@core/ws/ws-messages';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../testing/meeting-fixtures';
import { VoteCastComponent } from './vote-cast.component';
import { VotingPageService, type ShownVote } from './voting-page/voting-page.service';
import { RailStatusService } from '../../layout/rail-status.service';

/** A live-vote channel as signals, driven by the test. */
function fakeSession() {
  return {
    connection: signal<ConnectionState>('open'),
    openVote: signal<VoteOpenedMsg | null>(null),
    tally: signal<VoteTallyMsg | null>(null),
    result: signal<VoteClosedMsg | null>(null),
    close: jest.fn(),
  };
}
type FakeSession = ReturnType<typeof fakeSession>;

const opened = (voteId: string): VoteOpenedMsg => ({
  type: 'vote_opened',
  voteId,
  options: ['yes', 'no', 'abstain'],
  closesAt: null,
});

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
  /** The list page around the pane: `split` side by side. */
  page?: { split: boolean };
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
      : of({ id: 'm1', title: '34. Sitzung', gremiumId: 'g1', gremiumName: 'StuPa' }),
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
  const params = new BehaviorSubject<ParamMap>(convertToParamMap(id === null ? {} : { id }));
  const sessions: FakeSession[] = [];
  const live = {
    open: jest.fn(() => {
      const session = fakeSession();
      sessions.push(session);
      return session;
    }),
  };
  const page = opts.page
    ? {
        split: signal(opts.page.split),
        gremiumNames: signal(new Map([['v1', 'Haushaltsausschuss']])),
        shown: signal<ShownVote | null>(null),
        notify: jest.fn(),
        follow: jest.fn(() => {
          const session = fakeSession();
          sessions.push(session);
          return session;
        }),
      }
    : null;
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
      { provide: LiveVoteService, useValue: live },
      ...(page ? [{ provide: VotingPageService, useValue: page }] : []),
      { provide: ActivatedRoute, useValue: { paramMap: params } },
    ],
  });
  return {
    ...r,
    getVote,
    castBallot,
    deleteVote,
    getMeeting,
    voteStatus,
    toast,
    railStatus,
    auth,
    params,
    sessions,
    live,
    page,
  };
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
    expect(screen.getByRole('article', { name: 'Abstimmung' })).toBeInTheDocument();
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
    expect(
      screen.getByRole('heading', { name: 'Du bist für diese Abstimmung nicht stimmberechtigt.' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zu den Abstimmungen' })).toHaveAttribute('href', '/voting');
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
      expect(navigate).toHaveBeenCalledWith(['/voting/beamer', 'm1'], { queryParams: { from: '/' } });
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

    it('shows the phone header with the way back to the list', async () => {
      await setup();
      expect(screen.getByRole('link', { name: 'Zurück' })).toHaveAttribute('href', '/voting');
      // The way back goes to the list; the meeting line goes to the meeting.
      expect(screen.getByRole('link', { name: 'TOP 3 · 34. Sitzung' })).toHaveAttribute(
        'href',
        '/meetings/m1',
      );
      expect(document.querySelector('.vc__bar')).toBeNull();
      expect(document.querySelector('app-ballot')).toHaveClass('ballot--phone');
    });

    it('links the application of a vote without a meeting', async () => {
      await setup({ vote: vote({ meetingId: null, agendaItemId: null }) });
      expect(screen.getByRole('link', { name: 'Antrag öffnen' })).toHaveAttribute(
        'href',
        '/applications/a1',
      );
    });

    it('shows no line when the meeting cannot be read', async () => {
      await setup({ meetingError: true });
      expect(document.querySelector('.ph__sub')).toBeNull();
    });

    it('shows no line for a vote without a meeting and without an application', async () => {
      await setup({ vote: vote({ meetingId: null, agendaItemId: null, applicationId: null }) });
      expect(document.querySelector('.ph__sub')).toBeNull();
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
    async function openDelete(): Promise<void> {
      await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen' }));
      await userEvent.click(screen.getByRole('menuitem', { name: 'Abstimmung löschen' }));
    }

    it('deletes a draft standalone vote after the confirmation and goes back to the list', async () => {
      const { deleteVote, toast, fixture, page } = await setup({
        vote: draftVote(),
        canManage: true,
        page: { split: true },
      });
      const router = fixture.debugElement.injector.get(Router);
      const navigate = jest.spyOn(router, 'navigate');
      await openDelete();
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung löschen' }));
      expect(deleteVote).toHaveBeenCalledWith('v1');
      expect(toast.success).toHaveBeenCalledWith('Abstimmung gelöscht.');
      expect(page?.notify).toHaveBeenCalledWith({ id: 'v1', kind: 'deleted' });
      expect(navigate).toHaveBeenCalledWith(['/voting'], { queryParamsHandling: 'preserve' });
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
      expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).not.toBeInTheDocument();
    });

    it('offers no delete for a vote that already opened', async () => {
      await setup({ vote: vote({ meetingId: null }), canManage: true });
      expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).not.toBeInTheDocument();
    });

    it('offers no delete for a meeting-bound draft', async () => {
      await setup({ vote: draftVote({ meetingId: 'm1' }), canManage: true });
      expect(screen.queryByRole('button', { name: 'Weitere Aktionen' })).not.toBeInTheDocument();
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
      await openDelete();
      await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' })[0]);
      expect(deleteVote).not.toHaveBeenCalled();
    });
  });

  describe('in the list page', () => {
    it('is a sheet beside the list, with a flat panel', async () => {
      await setup({ page: { split: true } });
      expect(document.querySelector('.vc')).toHaveClass('vc--sheet');
      expect(document.querySelector('app-vote-panel')).toHaveClass('vpn--flat');
    });

    it('keeps the card one pane at a time', async () => {
      await setup({ page: { split: false } });
      expect(document.querySelector('.vc')).not.toHaveClass('vc--sheet');
      expect(document.querySelector('app-vote-panel')).not.toHaveClass('vpn--flat');
    });

    it('names the gremium of the meeting in the bar', async () => {
      await setup({ page: { split: true } });
      expect(document.querySelector('.vc__meta')).toHaveTextContent('StuPa');
    });

    it('names the gremium of the list row for a vote without a meeting', async () => {
      await setup({ page: { split: true }, vote: vote({ meetingId: null }) });
      expect(document.querySelector('.vc__meta')).toHaveTextContent('Haushaltsausschuss');
    });

    it('leaves the bar line empty without a gremium', async () => {
      await setup({ page: { split: true }, vote: vote({ id: 'v9', meetingId: null }) });
      expect(document.querySelector('.vc__meta')).toHaveTextContent('');
    });

    it('tells the list about a cast and stays on the vote', async () => {
      const { page, fixture } = await setup({ page: { split: true } });
      const router = fixture.debugElement.injector.get(Router);
      const navigate = jest.spyOn(router, 'navigate');
      await castOwn();
      expect(page?.notify).toHaveBeenCalledWith({ id: 'v1', kind: 'cast' });
      expect(navigate).not.toHaveBeenCalled();
      expect(screen.getByText('Danke! Deine Stimme: Ja')).toBeInTheDocument();
    });

    it('tells the list which vote it shows, and nothing after it goes away', async () => {
      const { page, fixture } = await setup({ page: { split: true } });
      expect(page?.shown()).toEqual({ id: 'v1', meetingId: 'm1', status: 'open' });
      fixture.destroy();
      expect(page?.shown()).toBeNull();
    });

    it('shares the live channel of the page for its meeting', async () => {
      const { page, live } = await setup({ page: { split: true } });
      expect(page?.follow).toHaveBeenCalledWith('m1');
      expect(live.open).not.toHaveBeenCalled();
    });

    it('loads the next vote when the route moves on, and drops a late answer', async () => {
      const { params, getVote, getMeeting, fixture } = await setup();
      const slow = new Subject<Vote>();
      const slowMeeting = new Subject<never>();
      getVote.mockImplementation(((id: string) =>
        id === 'v2' ? slow : of(vote({ id: 'v3', question: 'Dritte Frage?' }))) as never);
      params.next(convertToParamMap({ id: 'v2' }));
      fixture.detectChanges();
      expect(screen.getByRole('status')).toHaveTextContent('Abstimmung wird geladen …');
      getMeeting.mockReturnValueOnce(slowMeeting as never);
      params.next(convertToParamMap({ id: 'v3' }));
      fixture.detectChanges();
      slow.next(vote({ id: 'v2', question: 'Späte Frage?' }));
      fixture.detectChanges();
      expect(screen.getByRole('heading', { name: 'Dritte Frage?' })).toBeInTheDocument();
      expect(screen.queryByRole('heading', { name: 'Späte Frage?' })).not.toBeInTheDocument();
    });
  });

  describe('without a vote', () => {
    it('sends nothing and reads nothing again', async () => {
      const { fixture, getVote, voteStatus, castBallot, page } = await setup({
        getError: { status: 403 },
        page: { split: false },
      });
      getVote.mockClear();
      voteStatus.mockClear();
      const cmp = fixture.componentInstance;
      cmp.onCastDone();
      cmp.onCastFailed({ asDelegation: false, alreadyVoted: false, error: { status: 403 } } as never);
      cmp.caster('yes', false).subscribe();
      expect(castBallot).toHaveBeenCalledWith('', 'yes', false);
      expect(getVote).not.toHaveBeenCalled();
      expect(voteStatus).not.toHaveBeenCalled();
      expect(page?.notify).not.toHaveBeenCalled();
    });

    it('drops the late answers of the vote it left', async () => {
      const ctx = new Subject<never>();
      const meeting = new Subject<{ id: string; title: string }>();
      const status = new Subject<VoteDelegationStatus>();
      const failing = new Subject<Vote>();
      const reloadSlow = new Subject<Vote>();
      const { params, getVote, getMeeting, voteStatus, fixture } = await setup();
      // A reload of v1 that answers after the move to v2.
      getVote.mockReturnValueOnce(reloadSlow as never);
      fixture.componentInstance.onCastDone();
      // v2: its read fails late, its context and its delegation answer late.
      getVote.mockReturnValueOnce(failing as never);
      getMeeting.mockReturnValueOnce(meeting as never);
      voteStatus.mockReturnValueOnce(status as never);
      params.next(convertToParamMap({ id: 'v2' }));
      fixture.detectChanges();
      // v3 is shown at once.
      getVote.mockReturnValue(of(vote({ id: 'v3', question: 'Dritte Frage?' })) as never);
      getMeeting.mockReturnValue(ctx as never);
      params.next(convertToParamMap({ id: 'v3' }));
      fixture.detectChanges();
      reloadSlow.next(vote({ question: 'Alte Frage?' }));
      failing.error({ status: 500 });
      status.next({ ...NO_DELEGATION, blocked: true, delegatedToName: 'Mara Keller' });
      fixture.detectChanges();
      expect(screen.getByRole('heading', { name: 'Dritte Frage?' })).toBeInTheDocument();
      expect(screen.queryByText(/Mara Keller/)).not.toBeInTheDocument();
      expect(screen.queryByText('Abstimmung nicht verfügbar')).not.toBeInTheDocument();
    });

    it('drops the late context of the vote it left', async () => {
      const meeting = new Subject<{ id: string; title: string; gremiumId: string }>();
      const { params, getVote, getMeeting, fixture } = await setup();
      getMeeting.mockReturnValueOnce(meeting as never);
      getVote.mockReturnValueOnce(of(vote({ id: 'v2' })) as never);
      params.next(convertToParamMap({ id: 'v2' }));
      fixture.detectChanges();
      getVote.mockReturnValue(of(vote({ id: 'v3', meetingId: null })) as never);
      params.next(convertToParamMap({ id: 'v3' }));
      fixture.detectChanges();
      meeting.next({ id: 'm1', title: 'Späte Sitzung', gremiumId: 'g1' });
      meeting.complete();
      fixture.detectChanges();
      expect(screen.queryByText(/Späte Sitzung/)).not.toBeInTheDocument();
    });
  });

  describe('live', () => {
    it('follows the meeting of an open vote and shows the turnout of the socket', async () => {
      const { live, sessions, fixture } = await setup();
      expect(live.open).toHaveBeenCalledWith('m1');
      sessions[0].tally.set({
        type: 'vote_tally',
        voteId: 'v1',
        counts: {},
        eligible: 12,
        quorumMet: true,
        leading: null,
        cast: 9,
        present: 12,
        revealed: false,
      });
      fixture.detectChanges();
      expect(screen.getByText('9 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
    });

    it('shows the counts the socket revealed', async () => {
      const { sessions, fixture } = await setup();
      sessions[0].tally.set({
        type: 'vote_tally',
        voteId: 'v1',
        counts: { yes: 8, no: 3, abstain: 1 },
        eligible: 12,
        quorumMet: true,
        leading: 'yes',
        revealed: true,
      });
      fixture.detectChanges();
      expect(screen.getByText('5 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
      expect(document.querySelector('app-vote-bars')).toBeInTheDocument();
    });

    it('ignores the turnout of another vote', async () => {
      const { sessions, fixture } = await setup();
      sessions[0].tally.set({
        type: 'vote_tally',
        voteId: 'other',
        counts: {},
        eligible: 12,
        quorumMet: true,
        leading: null,
        cast: 11,
      });
      fixture.detectChanges();
      expect(screen.getByText('5 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
    });

    it('reads the vote again on its close', async () => {
      const { sessions, getVote, fixture } = await setup();
      getVote.mockClear();
      sessions[0].result.set({ type: 'vote_closed', voteId: 'v1', result: 'passed', counts: {} });
      fixture.detectChanges();
      expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
    });

    it('reads the vote again when it was cancelled', async () => {
      const { sessions, getVote, fixture } = await setup();
      sessions[0].openVote.set(opened('v1'));
      fixture.detectChanges();
      getVote.mockClear();
      sessions[0].openVote.set(null);
      fixture.detectChanges();
      expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
    });

    it('reads a draft again when it opens', async () => {
      const { sessions, getVote, fixture } = await setup({ vote: draftVote({ meetingId: 'm1' }) });
      getVote.mockClear();
      sessions[0].openVote.set(opened('other'));
      fixture.detectChanges();
      expect(getVote).not.toHaveBeenCalled();
      sessions[0].openVote.set(opened('v1'));
      fixture.detectChanges();
      expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
    });

    it('keeps the turnout hidden while neither the socket nor the read revealed it', async () => {
      const hidden = await setup();
      hidden.sessions[0].tally.set({
        type: 'vote_tally',
        voteId: 'v1',
        counts: { yes: 1 },
        eligible: 12,
        quorumMet: true,
        leading: null,
        cast: 6,
      });
      hidden.fixture.detectChanges();
      expect(screen.getByText('6 von 12 Anwesenden haben abgestimmt')).toBeInTheDocument();
      expect(document.querySelector('app-vote-bars')).toBeNull();
    });

    it('shows the counts when an old read has no reveal flag', async () => {
      const { sessions, fixture } = await setup({
        vote: vote({ tally: { counts: {}, eligible: 12, voted: 5, quorumMet: true, leading: null } }),
      });
      sessions[0].tally.set({
        type: 'vote_tally',
        voteId: 'v1',
        counts: { yes: 4, no: 1 },
        eligible: 12,
        quorumMet: true,
        leading: 'yes',
      });
      fixture.detectChanges();
      expect(document.querySelector('app-vote-bars')).toBeInTheDocument();
    });

    it('shows a lost connection', async () => {
      const { sessions, fixture } = await setup();
      sessions[0].connection.set('reconnecting');
      fixture.detectChanges();
      expect(screen.getByText('Verbindung verloren – verbinde neu …')).toBeInTheDocument();
    });

    it('does not follow a closed vote', async () => {
      const { live } = await setup({ vote: vote({ status: 'closed', result: 'passed' }) });
      expect(live.open).not.toHaveBeenCalled();
    });

    it('does not follow a vote without a meeting', async () => {
      const { live } = await setup({ vote: vote({ meetingId: null }) });
      expect(live.open).not.toHaveBeenCalled();
    });

    it('closes its own channel on a new meeting and on destroy', async () => {
      const { params, sessions, getVote, fixture } = await setup();
      getVote.mockReturnValue(of(vote({ id: 'v2', meetingId: 'm2' })));
      params.next(convertToParamMap({ id: 'v2' }));
      fixture.detectChanges();
      await fixture.whenStable();
      expect(sessions).toHaveLength(2);
      expect(sessions[0].close).toHaveBeenCalled();
      fixture.destroy();
      expect(sessions[1].close).toHaveBeenCalled();
    });
  });
});
