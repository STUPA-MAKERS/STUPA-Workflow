import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Meeting, MyBallot, Vote } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { VotePanelComponent } from './vote-panel.component';
import type { VoteContext } from './vote-context';

function vote(overrides: Partial<Vote> = {}): Vote {
  return {
    id: 'v1',
    applicationId: 'a1',
    meetingId: 'm1',
    agendaItemId: 'ag3',
    question: 'Soll der Antrag gefördert werden?',
    eligibleGroup: 'g1',
    config: { options: ['yes', 'no', 'abstain'], majorityRule: 'simple' },
    status: 'open',
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    majorityRule: 'simple',
    tally: { counts: {}, eligible: 19, voted: 14, present: 19, revealed: false, quorumMet: true, leading: null },
    ...overrides,
  };
}

const CONTEXT: VoteContext = {
  meeting: { id: 'm1', title: '34. Sitzung des Studierendenparlaments' } as Meeting,
  position: 3,
};

async function setup(inputs: {
  vote?: Vote;
  context?: VoteContext;
  own?: MyBallot | null;
  proxyName?: string | null;
  notice?: string | null;
  layout?: 'page' | 'phone';
} = {}) {
  const caster = jest.fn(() => of({ status: 'cast' }));
  const castDone = jest.fn();
  const castFailed = jest.fn();
  const r = await render(VotePanelComponent, {
    providers: [provideRouter([])],
    inputs: {
      vote: inputs.vote ?? vote(),
      context: inputs.context ?? CONTEXT,
      own: inputs.own === undefined ? { cast: false, choice: null } : inputs.own,
      proxyName: inputs.proxyName ?? null,
      notice: inputs.notice ?? null,
      layout: inputs.layout ?? 'page',
      caster,
    },
    on: { castDone, castFailed },
  });
  return { ...r, caster, castDone, castFailed };
}

describe('VotePanelComponent', () => {
  it('shows status, meeting, item, rule and question (board Arbeit-Abstimmungen)', async () => {
    await setup();
    expect(screen.getByText('Offen')).toHaveClass('st--accent');
    expect(screen.getByText('34. Sitzung des Studierendenparlaments · TOP 3')).toBeInTheDocument();
    expect(screen.getByText('Einfache Mehrheit')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Soll der Antrag gefördert werden?' })).toBeInTheDocument();
    expect(screen.getByText('14 von 19 Anwesenden haben abgestimmt')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stimme abgeben' })).toBeInTheDocument();
  });

  it('forwards the outcome of the ballot', async () => {
    const { caster, castDone } = await setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /^Ja$/ }));
    await user.click(screen.getByRole('button', { name: 'Stimme abgeben: Ja' }));
    expect(caster).toHaveBeenCalledWith('yes', false);
    expect(castDone).toHaveBeenCalledWith({ choice: 'yes', asDelegation: false });
  });

  it('names the quorum and a secret vote in the rules', async () => {
    await setup({
      vote: vote({ secret: true, quorum: { type: 'count', value: 12 }, majorityRule: 'absolute' }),
    });
    expect(screen.getByText('Absolute Mehrheit · Quorum 12 · geheime Abstimmung')).toBeInTheDocument();
    expect(
      screen.getByText('Geheime Abstimmung: Das Ergebnis zeigt sich nach dem Schließen.'),
    ).toBeInTheDocument();
  });

  it('reads the rule and a percent quorum from the config', async () => {
    await setup({
      vote: vote({
        majorityRule: undefined,
        config: { options: ['yes', 'no'], majorityRule: 'two_thirds', quorum: { type: 'percent', value: 50 } },
      }),
    });
    expect(screen.getByText('Zweidrittelmehrheit · Quorum 50 %')).toBeInTheDocument();
  });

  it('falls back to the simple majority and a generic question', async () => {
    await setup({
      vote: vote({
        majorityRule: undefined,
        question: null,
        config: { options: ['yes'] } as unknown as Vote['config'],
      }),
    });
    expect(screen.getByText('Einfache Mehrheit')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Beschlussfrage' })).toBeInTheDocument();
  });

  it('reads a secret vote from the config and survives a tally without attendance', async () => {
    const t = vote().tally;
    await setup({
      vote: vote({
        secret: false,
        config: { options: ['yes', 'no'], majorityRule: 'simple', secret: true },
        tally: { ...t, present: undefined, voted: undefined },
      }),
    });
    expect(screen.getByText('Einfache Mehrheit · geheime Abstimmung')).toBeInTheDocument();
    expect(screen.getByText('0 von 0 Anwesenden haben abgestimmt')).toBeInTheDocument();
  });

  it('names only the meeting when the item number is unknown', async () => {
    await setup({ context: { meeting: CONTEXT.meeting, position: null } });
    expect(screen.getByText('34. Sitzung des Studierendenparlaments')).toBeInTheDocument();
  });

  it('links the application of a vote without a meeting and counts the eligible voters', async () => {
    await setup({
      context: { meeting: null, position: null },
      vote: vote({
        meetingId: null,
        tally: { counts: { yes: 2, no: 1 }, eligible: 12, voted: 3, present: 0, revealed: true, quorumMet: false, leading: 'yes' },
      }),
    });
    expect(screen.getByRole('link', { name: 'Antrag öffnen' })).toHaveAttribute('href', '/applications/a1');
    expect(screen.getByText('3 von 12 Stimmberechtigten haben abgestimmt')).toBeInTheDocument();
    // The server shows the counts of a vote without a meeting while it runs.
    expect(screen.getByRole('list', { name: 'Ergebnis, 3 Stimmen' })).toBeInTheDocument();
    expect(screen.queryByText(/Zwischenstand/)).not.toBeInTheDocument();
  });

  it('shows no meeting line and no link for a motion without both', async () => {
    await setup({ context: { meeting: null, position: null }, vote: vote({ meetingId: null, applicationId: null }) });
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByText('·')).not.toBeInTheDocument();
  });

  it('shows the result of a closed vote and no ballot', async () => {
    await setup({
      vote: vote({
        status: 'closed',
        result: 'tie',
        tally: { counts: { yes: 4, no: 4, abstain: 0 }, eligible: 19, voted: 8, present: 0, revealed: true, quorumMet: true, leading: null },
      }),
    });
    expect(screen.getByText('Geschlossen')).toBeInTheDocument();
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByText(/Anwesenden haben abgestimmt/)).not.toBeInTheDocument();
  });

  describe('closed vote summary', () => {
    const closed = (tally: Partial<Vote['tally']>, extra: Partial<Vote> = {}) =>
      vote({
        status: 'closed',
        result: 'passed',
        quorum: { type: 'count', value: 10 },
        tally: { counts: { yes: 12, no: 6, abstain: 2 }, eligible: 20, voted: 20, present: 0, revealed: true, quorumMet: true, leading: 'yes', ...tally },
        ...extra,
      });

    it('names the ballots and the quorum state below the result', async () => {
      await setup({ vote: closed({}) });
      expect(screen.getByText('20 von 20 Stimmen · Quorum: erreicht')).toBeInTheDocument();
    });

    it('names a missed quorum of a vote that failed on majority', async () => {
      await setup({
        vote: closed({ voted: undefined, quorumMet: false, failedReason: 'majority' }, { result: 'failed' }),
      });
      // Without `voted`, the sum of the counts is the number of ballots.
      expect(screen.getByText('20 von 20 Stimmen · Quorum: nicht erreicht')).toBeInTheDocument();
    });

    it('does not repeat the quorum when the result already names it', async () => {
      await setup({
        vote: closed({ voted: 5, quorumMet: false, failedReason: 'quorum' }, { result: 'failed' }),
      });
      expect(screen.getByText('5 von 20 Stimmen')).toBeInTheDocument();
      expect(screen.queryByText(/Quorum: /)).not.toBeInTheDocument();
    });

    it('names only the ballots of a vote without a quorum', async () => {
      await setup({ vote: closed({}, { quorum: null }) });
      expect(screen.getByText('20 von 20 Stimmen')).toBeInTheDocument();
    });

    it('shows no summary while the vote is open', async () => {
      await setup();
      expect(screen.queryByText(/ von 19 Stimmen/)).not.toBeInTheDocument();
    });
  });

  it('shows the warning note instead of a ballot', async () => {
    await setup({ own: null, notice: 'Du bist für diese Abstimmung nicht stimmberechtigt.' });
    expect(screen.getByText('Du bist für diese Abstimmung nicht stimmberechtigt.')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('offers only the represented ballot to a substitute', async () => {
    await setup({ own: null, proxyName: 'Jonas Weber' });
    expect(screen.getByRole('heading', { name: 'Als Vertretung für Jonas Weber' })).toBeInTheDocument();
  });

  it('uses the phone layout of board Telefon-Abstimmen', async () => {
    const { fixture } = await setup({ layout: 'phone' });
    expect(fixture.nativeElement).toHaveClass('vpn--phone');
    expect(screen.getByText('Offen · Einfache Mehrheit')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Soll der Antrag gefördert werden?');
    expect(screen.getByRole('heading', { name: 'Deine Stimme' })).toBeInTheDocument();
    // The turnout comes before the ballot on a phone.
    const progress = fixture.nativeElement.querySelector('app-vote-progress') as HTMLElement;
    const ballot = fixture.nativeElement.querySelector('app-ballot') as HTMLElement;
    expect(progress.compareDocumentPosition(ballot) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('has no a11y violations', async () => {
    const { container } = await setup({ proxyName: 'Jonas Weber' });
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
