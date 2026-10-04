import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { MeetingStatus, MeetingVote } from '@core/api/models';
import { vote } from '../../../../testing/meeting-fixtures';
import { liveOpenedVote } from '../meetings-display.util';
import { VoteCardComponent } from './vote-card.component';

const OUTPUTS = ['close', 'cancel', 'open', 'remove', 'cast', 'insertResult'] as const;

interface Inputs {
  vote: MeetingVote;
  meetingStatus: MeetingStatus;
  canManage: boolean;
  canVote: boolean;
  myChoice: string | null;
  casting: string | null;
  deleting: string | null;
  locked: boolean;
  canInsert: boolean;
}

async function setup(over: Partial<Inputs> = {}) {
  const on = Object.fromEntries(OUTPUTS.map((name) => [name, jest.fn()])) as Record<
    (typeof OUTPUTS)[number],
    jest.Mock
  >;
  const view = await render(VoteCardComponent, {
    inputs: {
      vote: vote(),
      meetingStatus: 'live',
      canManage: true,
      canVote: false,
      myChoice: null,
      casting: null,
      deleting: null,
      locked: false,
      canInsert: false,
      ...over,
    },
    on,
  });
  return { ...view, on };
}

describe('VoteCardComponent', () => {
  describe('an open vote', () => {
    it('shows the question, the rules and the progress, but no tally before all voted', async () => {
      await setup({
        vote: vote({
          majorityRule: 'simple',
          secret: false,
          quorum: { type: 'count', value: 12 },
          openedAt: '2026-10-15T16:48:00Z',
          counts: { yes: 2, no: 1 },
        }),
      });
      expect(screen.getByText('Abstimmung offen')).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Wird der Nachtragshaushalt beschlossen?' })).toBeInTheDocument();
      expect(screen.getByText(/^Einfache Mehrheit · offene Abstimmung · Quorum 12 · seit \d\d:48$/)).toBeInTheDocument();
      expect(screen.getByText('3 von 4 Anwesenden haben abgestimmt')).toBeInTheDocument();
      expect(screen.getByText('75 %')).toBeInTheDocument();
      expect(screen.getByRole('img', { name: '3 von 4 Anwesenden haben abgestimmt' })).toBeInTheDocument();
      // No interim tally for the lead: the fixed text instead of the counts.
      expect(screen.getByText('Zwischenstand sichtbar, sobald alle Anwesenden abgestimmt haben.')).toBeInTheDocument();
      expect(screen.queryByRole('definition')).toBeNull();
    });

    it('shows the counts once the server reveals them', async () => {
      await setup({ vote: vote({ voted: 4, revealed: true, counts: { yes: 3, no: 1 }, leading: 'yes' }) });
      expect(screen.queryByText(/Zwischenstand sichtbar/)).toBeNull();
      expect(screen.getByText('Ja').closest('.vc__count')).toHaveClass('vc__count--lead');
      expect(screen.getByText('3')).toBeInTheDocument();
      expect(screen.getByText('Nein')).toBeInTheDocument();
    });

    it('names the hidden result of a secret vote and a percentage quorum', async () => {
      await setup({ vote: vote({ secret: true, quorum: { type: 'percent', value: 50 } }) });
      expect(screen.getByText(/geheime Abstimmung · Quorum 50 %/)).toBeInTheDocument();
      expect(screen.getByText(/Das Ergebnis zeigt sich nach dem Schließen/)).toBeInTheDocument();
    });

    it('names a secret vote that another manager opened live, before the next read', async () => {
      await setup({
        vote: liveOpenedVote({
          type: 'vote_opened',
          voteId: 'v-live',
          agendaItemId: 't-1',
          question: 'Geheim?',
          options: ['yes', 'no', 'abstain'],
          closesAt: null,
          secret: true,
        }),
      });
      expect(screen.getByText(/^geheime Abstimmung · seit \d\d:\d\d$/)).toBeInTheDocument();
      expect(screen.getByText(/Das Ergebnis zeigt sich nach dem Schließen/)).toBeInTheDocument();
      expect(screen.queryByText(/Zwischenstand sichtbar/)).toBeNull();
    });

    it('shows 0 % without anybody present', async () => {
      await setup({ vote: vote({ voted: 0, present: 0 }) });
      expect(screen.getByText('0 %')).toBeInTheDocument();
    });

    it('closes and cancels; the cancel is the danger action', async () => {
      const { on, container } = await setup();
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung schließen' }));
      expect(on.close).toHaveBeenCalledWith('v-1');
      const cancel = screen.getByRole('button', { name: 'Abstimmung abbrechen' });
      expect(cancel).toHaveClass('btn--danger');
      await userEvent.click(cancel);
      expect(on.cancel).toHaveBeenCalledWith('v-1');
      // An open vote is part of the record: no delete.
      expect(screen.queryByRole('button', { name: 'Beschlussfrage löschen' })).toBeNull();
      expect(container.querySelectorAll('.vc__actions app-button')).toHaveLength(2);
    });

    it('offers no vote control without the vote right', async () => {
      await setup({ canManage: false });
      expect(screen.queryByRole('button', { name: 'Abstimmung schließen' })).toBeNull();
    });

    it('lets a voter cast once; the ballot never changes (O11)', async () => {
      const { on, fixture } = await setup({ canVote: true });
      const options = screen.getAllByRole('button', { name: /^(Ja|Nein|Enthaltung)$/ });
      expect(options).toHaveLength(3);
      await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
      expect(on.cast).toHaveBeenCalledWith({ voteId: 'v-1', choice: 'yes' });
      fixture.componentRef.setInput('myChoice', 'yes');
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Ja' })).toBeNull();
    });

    it('hides the ballot when the server knows the own ballot', async () => {
      await setup({ canVote: true, vote: vote({ myBallot: { cast: true, choice: null } }) });
      expect(screen.queryByRole('button', { name: 'Ja' })).toBeNull();
    });

    it('falls back to the tally keys and keeps an unknown option raw', async () => {
      await setup({ canVote: true, vote: vote({ options: [], counts: { ja: 0, vielleicht: 0 } }) });
      expect(screen.getByRole('button', { name: 'ja' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'vielleicht' })).toBeInTheDocument();
    });
  });

  describe('a closed vote', () => {
    const closed = vote({
      status: 'closed',
      result: 'passed',
      counts: { yes: 3, no: 1, abstain: 0 },
      leading: 'yes',
      revealed: true,
      closedAt: '2026-10-15T17:02:00Z',
    });

    it('shows the result, the counts and the insert into the text', async () => {
      const { on } = await setup({ vote: closed, canInsert: true });
      expect(screen.getByText('Abstimmung geschlossen')).toBeInTheDocument();
      expect(screen.getByText('Angenommen')).toBeInTheDocument();
      expect(screen.getByText(/beendet \d\d:02/)).toBeInTheDocument();
      expect(screen.getByText('Enthaltung')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' }));
      expect(on.insertResult).toHaveBeenCalledWith(closed);
      // A closed vote is part of the record (409 `vote_not_deletable`).
      expect(screen.queryByRole('button', { name: 'Beschlussfrage löschen' })).toBeNull();
    });

    it('names a rejection, also a tie (O18), and a missed quorum', async () => {
      await setup({ vote: vote({ status: 'closed', result: 'tie', counts: { yes: 1, no: 1 } }) });
      expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
    });

    it('names the missed quorum', async () => {
      await setup({ vote: vote({ status: 'closed', result: 'rejected', failedReason: 'quorum' }) });
      expect(screen.getByText('Quorum nicht erreicht')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' })).toBeNull();
    });
  });

  describe('a planned or cancelled vote', () => {
    it('opens and deletes a planned vote while the meeting is live (O24)', async () => {
      const { on } = await setup({ vote: vote({ status: 'draft', majorityRule: 'absolute', secret: true }) });
      expect(screen.getByText('Abstimmung geplant')).toBeInTheDocument();
      expect(screen.getByText('Absolute Mehrheit · geheime Abstimmung')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung öffnen' }));
      expect(on.open).toHaveBeenCalledWith('v-1');
      await userEvent.click(screen.getByRole('button', { name: 'Beschlussfrage löschen' }));
      expect(on.remove).toHaveBeenCalledWith('v-1');
    });

    it('does not open a planned vote before the meeting runs', async () => {
      await setup({ vote: vote({ status: 'draft' }), meetingStatus: 'planned' });
      expect(screen.queryByRole('button', { name: 'Abstimmung öffnen' })).toBeNull();
      expect(screen.getByRole('button', { name: 'Beschlussfrage löschen' })).toBeInTheDocument();
    });

    it('deletes a cancelled vote, with the delete in flight shown', async () => {
      await setup({ vote: vote({ status: 'cancelled', closedAt: null }), deleting: 'v-1' });
      expect(screen.getByText('Abstimmung abgebrochen')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Beschlussfrage löschen' })).toBeDisabled();
    });

    it('keeps the votes of a closed meeting, of a locked protocol and of a reader', async () => {
      const { fixture } = await setup({ vote: vote({ status: 'cancelled' }), meetingStatus: 'closed' });
      expect(screen.queryByRole('button', { name: 'Beschlussfrage löschen' })).toBeNull();
      fixture.componentRef.setInput('meetingStatus', 'live');
      fixture.componentRef.setInput('locked', true);
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage löschen' })).toBeNull();
      fixture.componentRef.setInput('locked', false);
      fixture.componentRef.setInput('canManage', false);
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage löschen' })).toBeNull();
    });

    it('names an untitled question and leaves out an empty rules line', async () => {
      const { container } = await setup({ vote: vote({ status: 'cancelled', question: null }) });
      expect(screen.getByRole('heading', { name: 'Beschlussfrage' })).toBeInTheDocument();
      expect(container.querySelector('.vc__meta')).toBeNull();
    });
  });
});
