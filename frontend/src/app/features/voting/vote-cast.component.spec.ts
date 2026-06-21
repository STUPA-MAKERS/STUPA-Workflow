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
}) {
  const getVote = opts.getError
    ? jest.fn(() => throwError(() => opts.getError))
    : jest.fn(() => of(opts.vote ?? vote()));
  const castBallot = opts.castError
    ? jest.fn(() => throwError(() => opts.castError))
    : jest.fn(() => of(opts.castResult ?? { status: 'cast' as const }));
  const api = { getVote, castBallot };
  const auth = { can: () => opts.canVote ?? true };
  // Delegations-Status (#delegation-rework): Default = unbeteiligt.
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
      provideRouter([]),
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
  return { ...r, getVote, castBallot, voteStatus, toast };
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

  it('offers a separate proxy cast when exercising a delegation', async () => {
    // Externe:r Stellvertreter:in ohne eigenes Stimmrecht: NUR der
    // Vertretungs-Block ist sichtbar; die Abgabe läuft mit asDelegation=true.
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
    // Zwei getrennte Options-Gruppen → zwei »Ja«-Buttons.
    const yesButtons = screen.getAllByRole('button', { name: 'Ja' });
    expect(yesButtons).toHaveLength(2);
    await userEvent.click(yesButtons[0]);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', false);
    await userEvent.click(yesButtons[1]);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', true);
  });

  // --- Edge cases / branches ------------------------------------------------
  it('goes straight to error when the route has no vote id', async () => {
    const { getVote, voteStatus } = await setup({ routeId: null });
    // Ohne id kein Load: weder Vote- noch Delegations-Abruf.
    expect(getVote).not.toHaveBeenCalled();
    expect(voteStatus).not.toHaveBeenCalled();
    expect(screen.getByText(/nicht geladen/i)).toBeInTheDocument();
  });

  it('swallows a failing delegation-status lookup without breaking the vote UI', async () => {
    await setup({ delegationError: true, canVote: true });
    // Vote lädt trotzdem; Optionen erscheinen.
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
    // Nach dem 403 ist der Hinweis sichtbar und die Buttons verschwunden.
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
    // Proxy-Block (zweite Optionsgruppe) anklicken → 403 darf den eigenen Block NICHT sperren.
    const yesButtons = screen.getAllByRole('button', { name: 'Ja' });
    await userEvent.click(yesButtons[1]);
    expect(castBallot).toHaveBeenCalledWith('v1', 'yes', true);
    // Eigene Optionen weiterhin sichtbar (kein not-eligible-Flag gesetzt).
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
    // Kopfzeile (Mehrheitsregel · Quorum 7) — count-Quorum ohne %-Zeichen.
    const header = container.querySelector('header p') as HTMLElement;
    expect(header.textContent).toMatch(/Quorum\s*7/);
    expect(header.textContent).not.toContain('7%');
  });

  it('does nothing when casting an already-chosen, change-locked option', async () => {
    const { castBallot } = await setup({
      vote: vote({ config: { options: ['yes', 'no'], majorityRule: 'simple', allowChange: false } }),
    });
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledTimes(1);
    // Re-Klick auf dieselbe (nun gewählte) Option ist ein No-op: kein zweiter Call.
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
    // Unbekannter Key bleibt roh (kein durchgesickerter i18n-Key).
    expect(screen.getByRole('button', { name: 'wildcard' })).toBeInTheDocument();
  });

  it('falls back to simple majority and tie result when the config omits them', async () => {
    // majorityRule/result fehlen → Fallback-Keys vote.majority.simple / vote.result.tie.
    const v = vote();
    delete (v.config as { majorityRule?: unknown }).majorityRule;
    v.result = null;
    await setup({ vote: v });
    expect(screen.getByText('Einfache Mehrheit')).toBeInTheDocument();
  });

  it('ignores casts while a ballot is closed (guarded by isOpen)', async () => {
    const { castBallot } = await setup({ vote: vote({ status: 'closed', result: 'passed' }) });
    // Geschlossen → keine Options-Buttons; selbst ein direkter Cast wäre ein No-op.
    expect(screen.queryByRole('button', { name: 'Ja' })).not.toBeInTheDocument();
    expect(castBallot).not.toHaveBeenCalled();
  });

  it('does not allow a proxy cast when not exercising a delegation', async () => {
    // exercising=false → Vertretungs-Block fehlt, kein zweiter »Ja«-Button.
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
    // allowChange defaulted true → Umstimmen erlaubt, kein Lock-Hinweis.
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

  // --- Internal cast() guards (buttons disabled in DOM → call directly) -------
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
    // proxyChoice gesetzt + allowChange=false → weitere Proxy-Casts blocken.
    fixture.componentInstance.cast('no', true);
    expect(castBallot).toHaveBeenCalledTimes(1);
  });

  it('renders no option buttons when the config carries no options array', async () => {
    const v = vote();
    delete (v.config as { options?: unknown }).options;
    await setup({ vote: v });
    // options() fällt auf [] zurück → keine Buttons, aber kein Crash.
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
    // Erste Proxy-Stimme zählt …
    await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
    expect(castBallot).toHaveBeenCalledTimes(1);
    // … die zweite (anderes Feld) ist bei allowChange=false gesperrt.
    expect(screen.getByRole('button', { name: 'Nein' })).toBeDisabled();
  });
});
