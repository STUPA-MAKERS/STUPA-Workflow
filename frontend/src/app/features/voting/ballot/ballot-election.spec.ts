import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { ElectionConfig, MyBallot } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { BallotComponent, type BallotCaster } from './ballot.component';

const CANDIDATES = [
  { id: 'c1', name: 'Anna Berg' },
  { id: 'c2', name: 'Ben Ott' },
  { id: 'c3', name: 'Cem Aydin' },
];

async function setup(
  seats: number,
  opts: { own?: MyBallot | null; proxyName?: string; secret?: boolean; caster?: BallotCaster } = {},
) {
  const election: ElectionConfig = { seats, candidates: CANDIDATES, secret: !!opts.secret };
  const caster = jest.fn(opts.caster ?? (() => of({ status: 'cast' })));
  const castDone = jest.fn();
  const castFailed = jest.fn();
  const r = await render(BallotComponent, {
    inputs: {
      voteId: 'e1',
      options: ['c1', 'c2', 'c3', 'abstain'],
      own: opts.own === undefined ? { cast: false, choice: null } : opts.own,
      proxyName: opts.proxyName ?? null,
      secret: !!opts.secret,
      caster,
      election,
    },
    on: { castDone, castFailed },
  });
  return { ...r, caster, castDone, castFailed };
}

const confirmButton = () => screen.getByRole('button', { name: /abgeben/ });

describe('BallotComponent · election (F2)', () => {
  it('one seat: a radio list with a separate abstention row', async () => {
    const { caster, castDone, container } = await setup(1);
    const user = userEvent.setup();
    expect(screen.getByRole('radiogroup', { name: 'Deine Stimme' })).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Ben Ott' }));
    expect(screen.getByRole('radio', { name: 'Ben Ott' })).toHaveAttribute('aria-checked', 'true');
    expect(confirmButton()).toHaveTextContent('Stimme abgeben: Ben Ott');
    // A second pick replaces the first one.
    await user.click(screen.getByRole('radio', { name: 'Anna Berg' }));
    expect(screen.getByRole('radio', { name: 'Ben Ott' })).toHaveAttribute('aria-checked', 'false');
    await user.click(screen.getByRole('radio', { name: 'Enthaltung' }));
    expect(confirmButton()).toHaveTextContent('Stimme abgeben: Enthaltung');
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith([], false);
    expect(castDone).toHaveBeenCalledWith({ choice: [], asDelegation: false });
    // The open ballot keeps the pick after the cast: "Danke! Deine Stimme: Enthaltung".
    expect(screen.getByText('Danke! Deine Stimme: Enthaltung')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('several seats: check boxes, the counter and a vote count in the label', async () => {
    const { caster } = await setup(2);
    const user = userEvent.setup();
    expect(screen.getByText('0 von 2 Stimmen vergeben')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Anna Berg' }));
    expect(screen.getByText('1 von 2 Stimmen vergeben')).toBeInTheDocument();
    // The button counts instead of naming, so it stays whole on a phone (names and abstentions).
    expect(confirmButton()).toHaveTextContent(/^Stimmen abgeben \(1 Name, 1 Enthaltung\)$/);
    // The accessible name keeps the names.
    expect(confirmButton()).toHaveAccessibleName('Stimmen abgeben (1 Name, 1 Enthaltung): Anna Berg');
    await user.click(screen.getByRole('checkbox', { name: 'Cem Aydin' }));
    // All votes given: the further box stays off.
    expect(screen.getByRole('checkbox', { name: 'Ben Ott' })).toBeDisabled();
    // Only names: every seat has a vote.
    expect(confirmButton()).toHaveTextContent(/^Stimmen abgeben \(2 Namen\)$/);
    expect(confirmButton()).toHaveAccessibleName('Stimmen abgeben (2 Namen): Anna Berg, Cem Aydin');
    // A click on a chosen box takes the vote back.
    await user.click(screen.getByRole('checkbox', { name: 'Cem Aydin' }));
    expect(screen.getByRole('checkbox', { name: 'Ben Ott' })).toBeEnabled();
    await user.click(screen.getByRole('checkbox', { name: 'Ben Ott' }));
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith(['c1', 'c2'], false);
  });

  it('"Ganz enthalten" sends an empty list', async () => {
    const { caster } = await setup(2);
    const user = userEvent.setup();
    await user.click(screen.getByRole('checkbox', { name: 'Anna Berg' }));
    await user.click(screen.getByRole('button', { name: 'Ganz enthalten' }));
    expect(screen.getByRole('checkbox', { name: 'Anna Berg' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('button', { name: 'Ganz enthalten' })).toHaveAttribute('aria-pressed', 'true');
    // Only abstentions: no names to add to the accessible name.
    expect(confirmButton()).toHaveTextContent(/^Stimmen abgeben \(2 Enthaltungen\)$/);
    expect(confirmButton()).not.toHaveAttribute('aria-label');
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith([], false);
  });

  it('shows the cast candidates of an open ballot and nothing of a secret one', async () => {
    await setup(2, { own: { cast: true, choice: null, choices: ['c2'] } });
    expect(screen.getByRole('checkbox', { name: 'Ben Ott' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText('Danke! Deine Stimme: Ben Ott · 1 Enthaltung')).toBeInTheDocument();
    expect(screen.queryByText(/Stimmen vergeben/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Ganz enthalten' })).toBeNull();
  });

  it('keeps a secret ballot secret after the cast', async () => {
    const { caster } = await setup(1, { secret: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole('radio', { name: 'Cem Aydin' }));
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith(['c3'], false);
    expect(screen.getByText('Danke! Deine Stimme ist abgegeben.')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Cem Aydin' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByRole('radio', { name: 'Enthaltung' })).toHaveAttribute('aria-checked', 'false');
  });

  it('gives the represented member a candidate list of its own', async () => {
    const { caster } = await setup(1, { own: null, proxyName: 'Jonas Weber' });
    const user = userEvent.setup();
    expect(screen.getByRole('radiogroup', { name: 'Als Vertretung für Jonas Weber' })).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Anna Berg' }));
    expect(confirmButton()).toHaveTextContent('Für Jonas Weber abgeben: Anna Berg');
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith(['c1'], true);
    expect(screen.getByText('Für Jonas Weber abgegeben: Anna Berg')).toBeInTheDocument();
  });

  it('counts the votes of a represented member on several seats', async () => {
    const { caster } = await setup(3, { own: null, proxyName: 'Jonas Weber' });
    const user = userEvent.setup();
    await user.click(screen.getByRole('checkbox', { name: 'Anna Berg' }));
    expect(confirmButton()).toHaveTextContent(/^Für Jonas Weber abgeben \(1 Name, 2 Enthaltungen\)$/);
    await user.click(screen.getByRole('checkbox', { name: 'Ben Ott' }));
    expect(confirmButton()).toHaveAccessibleName(
      'Für Jonas Weber abgeben (2 Namen, 1 Enthaltung): Anna Berg, Ben Ott',
    );
    await user.click(confirmButton());
    expect(caster).toHaveBeenCalledWith(['c1', 'c2'], true);
  });

  it('keeps the plain label and no extra accessible name before a pick', async () => {
    await setup(2);
    expect(confirmButton()).toHaveTextContent(/^Stimme abgeben$/);
    expect(confirmButton()).not.toHaveAttribute('aria-label');
  });

  it('has no counter and no extra accessible name once every row is cast', async () => {
    const { fixture } = await setup(2, { own: { cast: true, choice: null, choices: ['c1'] } });
    const cmp = fixture.componentInstance as unknown as { confirmLabel(): string; confirmAria(): string };
    expect(cmp.confirmLabel()).toBe('Stimme abgeben');
    expect(cmp.confirmAria()).toBe('');
  });

  it('takes no pick while the row is cast or a cast runs', async () => {
    const { fixture } = await setup(2, {
      caster: () => throwError(() => ({ status: 409, error: { code: 'already_voted' } })),
    });
    const user = userEvent.setup();
    await user.click(screen.getByRole('checkbox', { name: 'Anna Berg' }));
    await user.click(confirmButton());
    // The 409 locks the row: a further toggle or abstention changes nothing.
    const cmp = fixture.componentInstance as unknown as {
      toggle(row: 'own', id: string): void;
      abstainAll(row: 'own'): void;
      picked(): Record<string, unknown>;
    };
    cmp.toggle('own', 'c2');
    cmp.abstainAll('own');
    expect(cmp.picked()['own']).toBeNull();
  });

  it('takes no further candidate once every seat has a vote; the proxy row abstains on its own', async () => {
    const { fixture } = await setup(2, { own: null, proxyName: 'Jonas Weber' });
    const cmp = fixture.componentInstance as unknown as {
      toggle(row: 'proxy', id: string): void;
      abstainAll(row: 'proxy'): void;
      picked(): Record<string, unknown>;
      candidateMode(): boolean;
    };
    cmp.toggle('proxy', 'c1');
    cmp.toggle('proxy', 'c2');
    cmp.toggle('proxy', 'c3');
    expect(cmp.picked()['proxy']).toEqual(['c1', 'c2']);
    cmp.abstainAll('proxy');
    expect(cmp.picked()['proxy']).toEqual([]);
    expect(cmp.candidateMode()).toBe(true);
    // A plain vote has no candidates and one seat.
    fixture.componentRef.setInput('election', null);
    const plain = fixture.componentInstance as unknown as { candidateMode(): boolean; multiSeat(): boolean; seats(): number };
    expect(plain.candidateMode()).toBe(false);
    expect(plain.multiSeat()).toBe(false);
    expect(plain.seats()).toBe(1);
  });
});
