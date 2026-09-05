import { render, screen } from '@testing-library/angular';
import type { AgendaItem, MeetingVote } from '@core/api/models';
import { MeetingBeamerComponent } from './meeting-beamer.component';

function vote(over: Partial<MeetingVote> = {}): MeetingVote {
  return {
    id: 'v-1',
    applicationId: null,
    agendaItemId: 't-1',
    title: null,
    question: 'Wird der Nachtragshaushalt beschlossen?',
    options: ['yes', 'no', 'abstain'],
    status: 'open',
    result: null,
    counts: { yes: 3, no: 1 },
    leading: 'yes',
    closesAt: null,
    voted: 4,
    present: 4,
    revealed: true,
    failedReason: null,
    ...over,
  };
}

const TOP: AgendaItem = { id: 't-1', applicationId: null, title: 'Bericht des Finanzreferats', position: 3 };

describe('MeetingBeamerComponent', () => {
  it('shows the current item, the question and the revealed tally', async () => {
    const { container } = await render(MeetingBeamerComponent, {
      inputs: { vote: vote(), top: TOP, topIndex: 3 },
    });
    expect(screen.getByText('TOP 4 · Bericht des Finanzreferats')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Wird der Nachtragshaushalt beschlossen?');
    expect(screen.getByText('4 von 4 Anwesenden haben abgestimmt')).toBeInTheDocument();
    expect(screen.getByText('Ja')).toBeInTheDocument();
    expect(container.querySelector('.mtg__beamerOpt--lead')).toHaveTextContent('3');
  });

  it('hides the tally of a concealed vote and names the result after the close', async () => {
    const { rerender } = await render(MeetingBeamerComponent, {
      inputs: { vote: vote({ revealed: false, counts: null, leading: null }) },
    });
    expect(screen.getByText(/Zwischenstand sichtbar/)).toBeInTheDocument();
    await rerender({
      inputs: { vote: vote({ status: 'closed', result: 'passed' }) },
      partialUpdate: true,
    });
    expect(screen.getByText('Angenommen')).toBeInTheDocument();
  });

  it('falls back to the untitled label and the idle hint', async () => {
    await render(MeetingBeamerComponent, {
      inputs: { vote: null, top: { ...TOP, title: null }, topIndex: 0 },
    });
    expect(screen.getByText('TOP 1 · Unbenannter TOP')).toBeInTheDocument();
    expect(screen.getByText('Zurzeit keine aktive Abstimmung.')).toBeInTheDocument();
  });
});
