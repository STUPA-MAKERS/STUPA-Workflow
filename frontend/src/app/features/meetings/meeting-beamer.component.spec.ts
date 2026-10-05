import { render, screen } from '@testing-library/angular';
import { type BeamerVote, MeetingBeamerComponent } from './meeting-beamer.component';

function vote(over: Partial<BeamerVote> = {}): BeamerVote {
  return {
    question: 'Soll der Antrag gefördert werden?',
    options: ['yes', 'no', 'abstain'],
    status: 'open',
    majorityRule: 'simple',
    secret: false,
    quorum: { type: 'count', value: 12 },
    quorumMet: true,
    voted: 14,
    present: 19,
    counts: null,
    result: null,
    failedReason: null,
    ...over,
  };
}

async function setup(inputs: {
  vote?: BeamerVote | null;
  topLine?: string | null;
  meetingTitle?: string | null;
}) {
  return render(MeetingBeamerComponent, {
    inputs: {
      logoSrc: 'assets/logos/stupa-wordmark-dark.svg',
      meetingTitle: '34. Sitzung',
      topLine: 'TOP 3 · Zuschuss',
      ...inputs,
    },
  });
}

describe('MeetingBeamerComponent', () => {
  it('shows the item of the room and no vote while idle', async () => {
    await setup({ vote: null });
    expect(screen.getByText('Jetzt')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'TOP 3 · Zuschuss' })).toBeInTheDocument();
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
    // The head names the meeting, but not the item a second time.
    expect(screen.getByText('34. Sitzung')).toBeInTheDocument();
    expect(screen.getAllByText('TOP 3 · Zuschuss')).toHaveLength(1);
  });

  it('shows only the idle line without a current item and without a meeting', async () => {
    await setup({ vote: null, topLine: null, meetingTitle: null });
    expect(screen.queryByText('Jetzt')).toBeNull();
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
  });

  it('shows the turnout of an open vote in large type and no tally', async () => {
    const { container } = await setup({ vote: vote() });
    expect(screen.getByRole('heading', { level: 1, name: 'Soll der Antrag gefördert werden?' })).toBeInTheDocument();
    expect(container.querySelector('.bm__big')?.textContent?.trim()).toBe('14');
    expect(screen.getByText('von 19 Anwesenden haben abgestimmt')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '14 von 19 Anwesenden haben abgestimmt' })).toBeInTheDocument();
    expect(screen.getByText('Zwischenstand sichtbar, sobald alle Anwesenden abgestimmt haben.')).toBeInTheDocument();
    expect(container.querySelector('app-vote-bars')).toBeNull();
    // The foot: the status and the rules, the quorum while it is reached.
    expect(screen.getByText('Offen')).toBeInTheDocument();
    expect(screen.getByText('Einfache Mehrheit · offene Abstimmung · Quorum 12')).toBeInTheDocument();
    expect(container.querySelector('.bm__warn')).toBeNull();
  });

  it('warns while an open vote misses its quorum', async () => {
    const { container } = await setup({ vote: vote({ quorumMet: false, voted: 11 }) });
    expect(screen.getByText('Einfache Mehrheit · offene Abstimmung')).toBeInTheDocument();
    expect(container.querySelector('.bm__warn')?.textContent?.trim()).toBe('Quorum 12 · noch nicht erreicht');
  });

  it('names a secret vote and keeps its counts until the close', async () => {
    const { container } = await setup({
      vote: vote({ secret: true, quorum: { type: 'percent', value: 50 }, counts: { yes: 3 } }),
    });
    expect(container.querySelector('app-vote-bars')).toBeNull();
    expect(screen.getByText('Geheime Abstimmung: Das Ergebnis zeigt sich nach dem Schließen.')).toBeInTheDocument();
    expect(screen.getByText('Einfache Mehrheit · geheime Abstimmung · Quorum 50 %')).toBeInTheDocument();
  });

  it('shows the revealed counts of an open vote as bars', async () => {
    const { container } = await setup({ vote: vote({ counts: { yes: 15, no: 2, abstain: 2 }, voted: 19 }) });
    expect(container.querySelector('app-vote-bars')).not.toBeNull();
    expect(screen.getByRole('img', { name: 'Ja: 15 Stimmen, 79 %' })).toBeInTheDocument();
    expect(container.querySelector('.bm__turnout')).toBeNull();
  });

  it('shows a passed vote with the rule, the quorum and the ballots', async () => {
    const { container } = await setup({
      vote: vote({ status: 'closed', result: 'passed', counts: { yes: 15, no: 3, abstain: 2 }, voted: 20 }),
    });
    expect(screen.getByRole('img', { name: 'Ja: 15 Stimmen, 75 %' })).toBeInTheDocument();
    const result = container.querySelector('.bm__result');
    expect(result?.textContent).toContain('Angenommen');
    expect(result).toHaveClass('bm__result--passed');
    expect(screen.getByText('Einfache Mehrheit · Quorum erreicht · 20 Stimmen')).toBeInTheDocument();
  });

  it('shows a tie as rejected: the simple majority is not reached (O18)', async () => {
    const { container } = await setup({
      vote: vote({ status: 'closed', result: 'tie', counts: { yes: 9, no: 9, abstain: 2 }, voted: 20 }),
    });
    const result = container.querySelector('.bm__result');
    expect(result?.textContent).toContain('Abgelehnt');
    expect(result).not.toHaveClass('bm__result--passed');
    expect(screen.queryByText(/Stimmengleichheit/)).toBeNull();
    expect(screen.getByText('Einfache Mehrheit nicht erreicht · Quorum erreicht · 20 Stimmen')).toBeInTheDocument();
  });

  it('names a missed quorum and leaves the rule as it is', async () => {
    await setup({
      vote: vote({
        status: 'closed',
        result: 'rejected',
        failedReason: 'quorum',
        quorumMet: false,
        counts: { yes: 1, no: 0, abstain: 0 },
        voted: 1,
      }),
    });
    expect(screen.getByText('Einfache Mehrheit · Quorum nicht erreicht · 1 Stimme')).toBeInTheDocument();
  });

  it('leaves the quorum out of a vote without one', async () => {
    await setup({
      vote: vote({
        status: 'closed',
        result: 'rejected',
        failedReason: 'majority',
        majorityRule: 'two_thirds',
        quorum: null,
        counts: { yes: 5, no: 4, abstain: 0 },
        voted: 9,
      }),
    });
    expect(screen.getByText('Zweidrittelmehrheit nicht erreicht · 9 Stimmen')).toBeInTheDocument();
  });
});
