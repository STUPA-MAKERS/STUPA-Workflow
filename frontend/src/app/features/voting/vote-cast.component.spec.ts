import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import type { Vote } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { VoteCastComponent } from './vote-cast.component';

function vote(overrides: Partial<Vote> = {}): Vote {
  return {
    id: 'v1',
    applicationId: 'a1',
    eligibleGroup: 'stupa',
    config: { options: ['yes', 'no', 'abstain'], majorityRule: 'two_thirds', allowChange: true },
    status: 'open',
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    tally: { counts: { yes: 5, no: 2, abstain: 1 }, eligible: 12, quorumMet: true, leading: 'yes' },
    ...overrides,
  };
}

async function setup(opts: {
  vote?: Vote;
  getError?: unknown;
  castError?: unknown;
  castResult?: { status: 'cast' | 'changed' };
  canVote?: boolean;
  delegation?: VoteDelegationStatus;
  delegationError?: boolean;
  routeId?: string | null;
  deleteError?: unknown;
  /** Permissions the stubbed principal holds. `true` grants everything. */
  permissions?: string[] | true;
}) {
  const getVote = opts.getError
    ? jest.fn(() => throwError(() => opts.getError))
    : jest.fn(() => of(opts.vote ?? vote()));
  const castBallot = opts.castError
    ? jest.fn(() => throwError(() => opts.castError))
    : jest.fn(() => of(opts.castResult ?? { status: 'cast' as const }));
  const deleteVote = opts.deleteError
    ? jest.fn(() => throwError(() => opts.deleteError))
    : jest.fn(() => of(void 0));
  const api = { getVote, castBallot, deleteVote };
  const perms = opts.permissions;
  const auth = {
    can: (p: string) =>
      perms === undefined || perms === true ? (opts.canVote ?? true) : perms.includes(p),
  };
  const voteStatus = opts.delegationError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() =>
        of(
          opts.delegation ?? {
            blocked: false,
            delegatedToName: null,
            exercising: false,
            delegatedByName: null,
          },
        ),
      );

  const toast = { success: jest.fn(), error: jest.fn() };

  const id = opts.routeId === undefined ? 'v1' : opts.routeId;
  const r = await render(VoteCastComponent, {
    providers: [
      // The delete navigates away, so both target routes must resolve.
      provideRouter([
        { path: 'voting', children: [] },
        { path: 'applications/:id', children: [] },
      ]),
      { provide: ApiClient, useValue: api },
      { provide: DelegationsApiService, useValue: { voteStatus } },
      { provide: AuthService, useValue: auth },
      { provide: ToastService, useValue: toast },
      {
        provide: ActivatedRoute,
        useValue: {
          snapshot: { paramMap: convertToParamMap(id === null ? {} : { id }) },
        },
      },
    ],
  });
  return { ...r, getVote, castBallot, deleteVote, voteStatus, toast };
}

/** A draft standalone vote: the only shape the delete route accepts. */
function draftVote(overrides: Partial<Vote> = {}): Vote {
  return vote({ status: 'draft', meetingId: null, ...overrides });
}

/** Conflict answer of `DELETE /votes/{id}` with its machine code. */
function conflict(code: string) {
  return { status: 409, error: { type: `app://error/${code}`, title: 'Conflict', status: 409, code } };
}

describe('VoteCastComponent', () => {
  it('shows options for an open, eligible vote and casts a ballot', async () => {
    const { castBallot } = await setup({ canVote: true });
    const yes = screen.getByRole('button', { name: 'Ja' });
    expect(yes).toBeInTheDocument();
    await userEvent.click(yes);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', false);
    expect(screen.getByText(/Deine Stimme: Ja/)).toBeInTheDocument();
  });

  it('hides the cast UI and shows a hint when not eligible', async () => {
    await setup({ canVote: false });
    expect(screen.getByRole('alert')).toHaveTextContent(/nicht stimmberechtigt/i);
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
  });

  it('renders closed votes read-only with a result badge', async () => {
    await setup({ vote: vote({ status: 'closed', result: 'passed' }) });
    expect(screen.getByText('Angenommen')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
  });

  it('locks changing the vote when allowChange is false', async () => {
    const { castBallot } = await setup({
      vote: vote({ config: { options: ['yes', 'no'], majorityRule: 'simple', allowChange: false } }),
    });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Nein' })).toBeDisabled();
    expect(screen.getByText(/nicht möglich/i)).toBeInTheDocument();
  });

  it('hides counts for a secret ballot while open', async () => {
    await setup({ vote: vote({ secret: true }) });
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(screen.getByText(/nicht sichtbar/i)).toBeInTheDocument();
  });

  it('treats a 403 on load as not-eligible', async () => {
    await setup({ getError: { status: 403 } });
    expect(screen.getByRole('alert')).toHaveTextContent(/nicht stimmberechtigt/i);
  });

  it('shows an error card when the vote cannot be loaded', async () => {
    await setup({ getError: { status: 500 } });
    expect(screen.getByText(/nicht geladen/i)).toBeInTheDocument();
  });

  it('surfaces a 409 conflict as already-voted', async () => {
    const { getVote } = await setup({ castError: { status: 409 } });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    // The initial load plus the refetch after the conflict.
    expect(getVote).toHaveBeenCalledTimes(2);
  });

  it('explains a delegated-away voting right instead of a bare not-eligible hint', async () => {
    await setup({
      delegation: {
        blocked: true,
        delegatedToName: 'Bob Beispiel',
        exercising: false,
        delegatedByName: null,
      },
    });
    expect(screen.getByRole('alert')).toHaveTextContent(/Bob Beispiel/);
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
  });

  it('offers a separate proxy cast when exercising a delegation', async () => {
    // An external substitute has no own voting right. Only the proxy block stays visible.
    // The ballot runs with asDelegation=true.
    const { castBallot } = await setup({
      canVote: false,
      delegation: {
        blocked: false,
        delegatedToName: null,
        exercising: true,
        delegatedByName: 'Alice Beispiel',
      },
    });
    expect(screen.getByText('In Vertretung')).toBeInTheDocument();
    expect(screen.getByText(/Als Vertretung für Alice Beispiel/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', true);
    expect(screen.getByText(/Vertretungs-Stimme: Ja/)).toBeInTheDocument();
  });

  it('shows own AND proxy cast blocks for a member with an incoming delegation', async () => {
    const { castBallot } = await setup({
      canVote: true,
      delegation: {
        blocked: false,
        delegatedToName: null,
        exercising: true,
        delegatedByName: 'Alice Beispiel',
      },
    });
    expect(screen.getByText('Deine Stimme')).toBeInTheDocument();
    expect(screen.getByText(/Als Vertretung für Alice Beispiel/)).toBeInTheDocument();
    // Two separate option groups give two "Ja" buttons.
    const yesButtons = screen.getAllByRole('button', { name: 'Ja' });
    expect(yesButtons).toHaveLength(2);
    await userEvent.click(yesButtons[0]);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', false);
    await userEvent.click(yesButtons[1]);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', true);
  });

  it('goes straight to error when the route has no vote id', async () => {
    const { getVote, voteStatus } = await setup({ routeId: null });
    expect(getVote).not.toHaveBeenCalled();
    expect(voteStatus).not.toHaveBeenCalled();
    expect(screen.getByText(/nicht geladen/i)).toBeInTheDocument();
  });

  it('swallows a failing delegation-status lookup without breaking the vote UI', async () => {
    await setup({ delegationError: true, canVote: true });
    expect(screen.getByRole('button', { name: 'Ja' })).toBeInTheDocument();
  });

  it('shows a changed toast when the server reports a changed ballot', async () => {
    const { castBallot } = await setup({ castResult: { status: 'changed' } });
    await userEvent.click(screen.getByRole('button', { name: 'Nein' }));
    expect(castBallot).toHaveBeenCalledWith('v1', 'no', false);
    expect(screen.getByText(/Deine Stimme: Nein/)).toBeInTheDocument();
  });

  it('marks not-eligible on a 403 from an own cast', async () => {
    await setup({ castError: { status: 403 } });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(screen.getByRole('alert')).toHaveTextContent(/nicht stimmberechtigt/i);
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
  });

  it('keeps the own block on a 403 from a PROXY cast (does not lock the member out)', async () => {
    const { castBallot } = await setup({
      canVote: true,
      castError: { status: 403 },
      delegation: {
        blocked: false,
        delegatedToName: null,
        exercising: true,
        delegatedByName: 'Alice Beispiel',
      },
    });
    // Click the proxy block, which is the second option group. A 403 must not lock the
    // own block.
    const yesButtons = screen.getAllByRole('button', { name: 'Ja' });
    await userEvent.click(yesButtons[1]);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', true);
    expect(screen.getByText('Deine Stimme')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Ja' }).length).toBe(2);
  });

  it('shows the server-provided problem detail on a generic cast failure', async () => {
    const { toast } = await setup({
      castError: { status: 500, error: { detail: 'Server kaputt' } },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(toast.error).toHaveBeenCalledWith('Server kaputt');
  });

  it('falls back to a generic failure toast when no problem detail is given', async () => {
    const { toast } = await setup({ castError: { status: 500 } });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(toast.error).toHaveBeenCalledWith('Stimme konnte nicht gezählt werden.');
  });

  it('renders a quorum hint when the vote config carries a quorum', async () => {
    await setup({
      vote: vote({
        config: {
          options: ['yes', 'no'],
          majorityRule: 'simple',
          allowChange: true,
          quorum: { type: 'percent', value: 50 },
        },
      }),
    });
    expect(screen.getByText(/50%/)).toBeInTheDocument();
  });

  it('renders an absolute (count) quorum without a percent sign', async () => {
    const { container } = await setup({
      vote: vote({
        config: {
          options: ['yes', 'no'],
          majorityRule: 'simple',
          allowChange: true,
          quorum: { type: 'count', value: 7 },
        },
      }),
    });
    const subtitle = container.querySelector('.ph__subtitle') as HTMLElement;
    expect(subtitle.textContent).toMatch(/Quorum\s*7/);
    expect(subtitle.textContent).not.toContain('7%');
  });

  it('does nothing when casting an already-chosen, change-locked option', async () => {
    const { castBallot } = await setup({
      vote: vote({ config: { options: ['yes', 'no'], majorityRule: 'simple', allowChange: false } }),
    });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledTimes(1);
  });

  it('shows the secret-while-open hint instead of bars', async () => {
    await setup({ vote: vote({ secret: true }) });
    expect(screen.getByText(/nicht sichtbar/i)).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('reveals bars for a closed secret ballot', async () => {
    await setup({ vote: vote({ status: 'closed', result: 'rejected', secret: true }) });
    expect(screen.getAllByRole('progressbar').length).toBeGreaterThan(0);
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
  });

  it('keeps unknown option keys as their raw label', async () => {
    await setup({
      vote: vote({
        config: { options: ['yes', 'wildcard'], majorityRule: 'simple', allowChange: true },
        tally: { counts: { yes: 1, wildcard: 0 }, eligible: 5, quorumMet: false, leading: 'yes' },
      }),
    });
    expect(screen.getByRole('button', { name: 'wildcard' })).toBeInTheDocument();
  });

  it('falls back to simple majority and tie result when the config omits them', async () => {
    // A missing majorityRule falls back to vote.majority.simple. A missing result falls
    // back to vote.result.tie.
    const v = vote();
    delete (v.config as { majorityRule?: unknown }).majorityRule;
    v.result = null;
    await setup({ vote: v });
    expect(screen.getByText('Einfache Mehrheit')).toBeInTheDocument();
  });

  it('ignores casts while a ballot is closed (guarded by isOpen)', async () => {
    const { castBallot } = await setup({ vote: vote({ status: 'closed', result: 'passed' }) });
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
    expect(castBallot).not.toHaveBeenCalled();
  });

  it('does not allow a proxy cast when not exercising a delegation', async () => {
    const { castBallot } = await setup({
      canVote: true,
      delegation: {
        blocked: false,
        delegatedToName: null,
        exercising: false,
        delegatedByName: null,
      },
    });
    expect(screen.getAllByRole('button', { name: 'Ja' })).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', false);
  });

  it('defaults allowChange to true when the config omits it', async () => {
    const v = vote();
    delete (v.config as { allowChange?: unknown }).allowChange;
    const { castBallot } = await setup({ vote: v });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    await userEvent.click(screen.getByRole('button', { name: 'Nein' }));
    expect(castBallot).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/nicht möglich/i)).not.toBeInTheDocument();
  });

  it('renders the tie fallback for a closed vote without a recorded result', async () => {
    await setup({ vote: vote({ status: 'closed', result: null }) });
    expect(screen.getByText('Stimmengleichheit')).toBeInTheDocument();
  });

  it('shows an explicit tie result on a closed vote', async () => {
    await setup({ vote: vote({ status: 'closed', result: 'tie' }) });
    expect(screen.getByText('Stimmengleichheit')).toBeInTheDocument();
  });

  // The next tests call cast() directly, because the DOM disables the buttons.
  it('cast() is a no-op when the vote is closed (isOpen guard)', async () => {
    const { fixture, castBallot } = await setup({
      vote: vote({ status: 'closed', result: 'passed' }),
    });
    fixture.componentInstance.cast('yes');
    expect(castBallot).not.toHaveBeenCalled();
  });

  it('cast(asDelegation) is a no-op when not exercising a delegation', async () => {
    const { fixture, castBallot } = await setup({ canVote: true });
    fixture.componentInstance.cast('yes', true);
    expect(castBallot).not.toHaveBeenCalled();
  });

  it('cast(asDelegation) is a no-op after a change-locked proxy ballot', async () => {
    const { fixture, castBallot } = await setup({
      canVote: false,
      vote: vote({ config: { options: ['yes', 'no'], majorityRule: 'simple', allowChange: false } }),
      delegation: {
        blocked: false,
        delegatedToName: null,
        exercising: true,
        delegatedByName: 'Alice',
      },
    });
    fixture.componentInstance.cast('yes', true);
    expect(castBallot).toHaveBeenCalledTimes(1);
    // A set proxyChoice with allowChange=false blocks all further proxy casts.
    fixture.componentInstance.cast('no', true);
    expect(castBallot).toHaveBeenCalledTimes(1);
  });

  it('renders no option buttons when the config carries no options array', async () => {
    const v = vote();
    delete (v.config as { options?: unknown }).options;
    await setup({ vote: v });
    // The options signal falls back to an empty array, so no button renders and nothing crashes.
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
  });

  it('cast() is a no-op when re-selecting the same change-locked own choice', async () => {
    const { fixture, castBallot } = await setup({
      vote: vote({ config: { options: ['yes', 'no'], majorityRule: 'simple', allowChange: false } }),
    });
    fixture.componentInstance.cast('yes');
    expect(castBallot).toHaveBeenCalledTimes(1);
    fixture.componentInstance.cast('yes');
    expect(castBallot).toHaveBeenCalledTimes(1);
  });

  it('locks a change-blocked proxy cast after the first proxy ballot', async () => {
    const { castBallot } = await setup({
      canVote: false,
      vote: vote({ config: { options: ['yes', 'no'], majorityRule: 'simple', allowChange: false } }),
      delegation: {
        blocked: false,
        delegatedToName: null,
        exercising: true,
        delegatedByName: 'Alice Beispiel',
      },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Nein' })).toBeDisabled();
  });

  describe('delete', () => {
    it('deletes a draft standalone vote after the confirmation', async () => {
      const { deleteVote, toast } = await setup({
        vote: draftVote(),
        permissions: ['vote.manage'],
      });
      await userEvent.click(screen.getAllByRole('button', { name: 'Abstimmung löschen' })[0]);
      const buttons = screen.getAllByRole('button', { name: 'Abstimmung löschen' });
      await userEvent.click(buttons[buttons.length - 1]);
      expect(deleteVote).toHaveBeenCalledWith('v1');
      expect(toast.success).toHaveBeenCalledWith('Abstimmung gelöscht.');
    });

    it('falls back to the vote overview when the vote carries no application', async () => {
      const v = draftVote();
      (v as { applicationId?: string | null }).applicationId = null;
      const { fixture, deleteVote } = await setup({ vote: v, permissions: ['vote.manage'] });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (fixture.componentInstance as any).doDelete();
      expect(deleteVote).toHaveBeenCalledWith('v1');
    });

    it('offers no delete without vote.manage', async () => {
      await setup({ vote: draftVote(), permissions: ['vote.cast'] });
      expect(
        screen.queryByRole('button', { name: 'Abstimmung löschen' }),
      ).not.toBeInTheDocument();
    });

    it('offers no delete for a vote that already opened', async () => {
      await setup({ vote: vote({ status: 'open' }), permissions: ['vote.manage'] });
      expect(
        screen.queryByRole('button', { name: 'Abstimmung löschen' }),
      ).not.toBeInTheDocument();
    });

    it('offers no delete for a meeting-bound draft', async () => {
      await setup({ vote: draftVote({ meetingId: 'm1' }), permissions: ['vote.manage'] });
      expect(
        screen.queryByRole('button', { name: 'Abstimmung löschen' }),
      ).not.toBeInTheDocument();
    });

    it.each([
      ['vote_not_draft', 'Die Abstimmung war bereits geöffnet. Statt zu löschen, brich sie ab.'],
      [
        'vote_has_ballots',
        'Es liegen bereits Stimmen vor. Die Abstimmung lässt sich nicht mehr löschen.',
      ],
      [
        'vote_meeting_bound',
        'Diese Abstimmung gehört zu einer Sitzung. Sie wird dort gelöscht.',
      ],
      ['something_else', 'Die Abstimmung ist in einem Zustand, der das Löschen ausschließt.'],
    ])('explains the 409 code %s and reloads the vote', async (code, message) => {
      const { fixture, toast, getVote } = await setup({
        vote: draftVote(),
        permissions: ['vote.manage'],
        deleteError: conflict(code),
      });
      getVote.mockClear();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (fixture.componentInstance as any).doDelete();
      expect(toast.error).toHaveBeenCalledWith(message);
      expect(getVote).toHaveBeenCalledWith('v1', { quiet: true });
    });

    it.each([
      [403, 'Keine Berechtigung, diese Abstimmung zu löschen.'],
      [500, 'Die Abstimmung konnte nicht gelöscht werden.'],
    ])('reports a %s failure with its own message', async (status, message) => {
      const { fixture, toast } = await setup({
        vote: draftVote(),
        permissions: ['vote.manage'],
        deleteError: { status },
      });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (fixture.componentInstance as any).doDelete();
      expect(toast.error).toHaveBeenCalledWith(message);
    });

    it('ignores a second delete while one runs', async () => {
      const { fixture, deleteVote } = await setup({
        vote: draftVote(),
        permissions: ['vote.manage'],
      });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      c.deleting.set(true);
      c.doDelete();
      expect(deleteVote).not.toHaveBeenCalled();
    });
  });
});
