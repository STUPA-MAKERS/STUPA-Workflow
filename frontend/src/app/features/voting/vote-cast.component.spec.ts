import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApiClient } from '@core/api/api-client.service';
import { DelegationsApiService, type VoteDelegationStatus } from '@core/api/delegations.service';
import { AuthService } from '@core/auth/auth.service';
import type { Vote } from '@core/api/models';
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
  canVote?: boolean;
  delegation?: VoteDelegationStatus;
}) {
  const getVote = opts.getError
    ? jest.fn(() => throwError(() => opts.getError))
    : jest.fn(() => of(opts.vote ?? vote()));
  const castBallot = opts.castError
    ? jest.fn(() => throwError(() => opts.castError))
    : jest.fn(() => of({ status: 'cast' as const }));
  const api = { getVote, castBallot };
  const auth = { can: () => opts.canVote ?? true };
  // Delegations-Status (#delegation-rework): Default = unbeteiligt.
  const voteStatus = jest.fn(() =>
    of(
      opts.delegation ?? {
        blocked: false,
        delegatedToName: null,
        exercising: false,
        delegatedByName: null,
      },
    ),
  );

  await render(VoteCastComponent, {
    providers: [
      provideRouter([]),
      { provide: ApiClient, useValue: api },
      { provide: DelegationsApiService, useValue: { voteStatus } },
      { provide: AuthService, useValue: auth },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ id: 'v1' }) } },
      },
    ],
  });
  return { getVote, castBallot };
}

describe('VoteCastComponent', () => {
  it('shows options for an open, eligible vote and casts a ballot', async () => {
    const { castBallot } = await setup({ canVote: true });
    const yes = screen.getByRole('button', { name: 'Ja' });
    expect(yes).toBeInTheDocument();
    await userEvent.click(yes);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes');
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
    // Andere Option ist jetzt gesperrt.
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
    // initialer Load + Refetch nach Konflikt
    expect(getVote).toHaveBeenCalledTimes(2);
  });

  // --- Delegations-Feedback (#delegation-rework) -----------------------------
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

  it('shows a proxy badge and enables voting when exercising a delegation', async () => {
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
    expect(screen.getByText(/Vertretung von Alice Beispiel/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes');
  });
});
