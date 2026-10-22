import { of } from 'rxjs';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { MyBallot, PollConfig } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { BallotComponent, type BallotCaster } from './ballot.component';

const DATE_POLL: PollConfig = {
  mode: 'date',
  options: [
    { id: 'o1', start: '2026-11-03T17:00:00Z', end: '2026-11-03T19:00:00Z' },
    { id: 'o2', start: '2026-11-04T16:00:00Z' },
  ],
  secret: false,
};
const TEXT_OPTIONS = [
  { id: 'o1', label: 'Pizza' },
  { id: 'o2', label: 'Pasta' },
  { id: 'o3', label: 'Salat' },
];

async function setup(poll: PollConfig, opts: { own?: MyBallot; secret?: boolean } = {}) {
  const caster = jest.fn<ReturnType<BallotCaster>, Parameters<BallotCaster>>(() =>
    of({ status: 'cast' }),
  );
  const castDone = jest.fn();
  const r = await render(BallotComponent, {
    inputs: {
      voteId: 'p1',
      options: poll.mode === 'date' ? [] : [...poll.options.map((o) => o.id), 'abstain'],
      own: opts.own ?? { cast: false, choice: null },
      secret: !!opts.secret,
      caster,
      poll,
    },
    on: { castDone },
  });
  return { ...r, caster, castDone };
}

/** The three buttons of a date row, by the label of its date. */
function row(text: RegExp) {
  return within(screen.getByRole('radiogroup', { name: text }));
}

describe('BallotComponent · poll', () => {
  describe('date mode', () => {
    it('asks Ja, Vielleicht and Nein for every date and sends once each has an answer', async () => {
      const { caster, castDone, container } = await setup(DATE_POLL);
      const user = userEvent.setup();
      expect(screen.getAllByRole('radiogroup')).toHaveLength(2);
      const first = row(/03\.11\./);
      expect(first.getAllByRole('radio').map((b) => b.textContent?.trim())).toEqual([
        'Ja',
        'Vielleicht',
        'Nein',
      ]);
      await user.click(first.getByRole('radio', { name: 'Ja' }));
      expect(first.getByRole('radio', { name: 'Ja' })).toHaveAttribute('aria-checked', 'true');
      // One date still lacks its answer: the button stays off.
      const submit = screen.getByRole('button', { name: 'Antworten abgeben' });
      expect(submit).toBeDisabled();
      // A second click changes the answer before the cast.
      await user.click(first.getByRole('radio', { name: 'Vielleicht' }));
      await user.click(row(/04\.11\./).getByRole('radio', { name: 'Nein' }));
      expect(submit).toBeEnabled();
      expect(await runAxe(container)).toHaveNoViolations();

      await user.click(submit);
      expect(caster).toHaveBeenCalledWith({ o1: 'maybe', o2: 'no' }, false);
      expect(castDone).toHaveBeenCalled();
      // The answer never changes after the cast: the rows lock and keep the answers.
      for (const b of screen.getAllByRole('radio')) expect(b).toBeDisabled();
      expect(row(/03\.11\./).getByRole('radio', { name: 'Vielleicht' })).toHaveAttribute(
        'aria-checked',
        'true',
      );
      expect(screen.getByText(/Deine Stimme ist gespeichert|Danke/)).toBeInTheDocument();
    });

    it('shows the cast answers of an open poll, none of a secret one', async () => {
      const own: MyBallot = { cast: true, choice: null, answers: { o1: 'yes', o2: 'no' } };
      await setup(DATE_POLL, { own });
      expect(row(/03\.11\./).getByRole('radio', { name: 'Ja' })).toHaveAttribute('aria-checked', 'true');
      expect(screen.queryByRole('button', { name: 'Antworten abgeben' })).toBeNull();
    });

    it('a secret poll shows no answer after the cast', async () => {
      const own: MyBallot = { cast: true, choice: null, answers: { o1: 'yes', o2: 'no' } };
      await setup({ ...DATE_POLL, secret: true }, { own, secret: true });
      for (const b of screen.getAllByRole('radio')) expect(b).toHaveAttribute('aria-checked', 'false');
    });
  });

  it('a single poll reuses the radio rows with the abstention', async () => {
    const { caster } = await setup({ mode: 'single', options: TEXT_OPTIONS, secret: false });
    const user = userEvent.setup();
    expect(screen.getByRole('radio', { name: 'Enthaltung' })).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Pasta' }));
    await user.click(screen.getByRole('button', { name: /abgeben/ }));
    expect(caster).toHaveBeenCalledWith(['o2'], false);
  });

  it('a multi poll counts "n von höchstens m gewählt" and sends the picks', async () => {
    const { caster } = await setup({ mode: 'multi', options: TEXT_OPTIONS, maxChoices: 2, secret: false });
    const user = userEvent.setup();
    await user.click(screen.getByRole('checkbox', { name: 'Pizza' }));
    expect(screen.getByText('1 von höchstens 2 gewählt')).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Salat' }));
    expect(screen.getByText('2 von höchstens 2 gewählt')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Pasta' })).toBeDisabled();
    const submit = screen.getByRole('button', { name: /abgeben/ });
    expect(submit).toHaveTextContent('2 Optionen');
    await user.click(submit);
    expect(caster).toHaveBeenCalledWith(['o1', 'o3'], false);
  });
});
