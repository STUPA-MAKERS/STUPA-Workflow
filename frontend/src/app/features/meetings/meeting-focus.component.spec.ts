import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type {
  AgendaItem,
  Attendance,
  Meeting,
  MeetingVote,
  Protocol,
} from '@core/api/models';
import { MeetingFocusComponent } from './meeting-focus.component';

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
    counts: null,
    leading: null,
    closesAt: null,
    voted: 3,
    present: 4,
    revealed: false,
    failedReason: null,
    ...over,
  };
}

function meeting(over: Partial<Meeting> = {}): Meeting {
  return {
    id: 'm-1',
    title: 'Konstituierende Sitzung',
    date: '2026-10-15',
    startTime: '18:00',
    endTime: null,
    status: 'live',
    activeApplicationId: null,
    currentAgendaItemId: 't-1',
    gremiumId: 'g-1',
    gremiumName: 'StuPa',
    votes: [],
    protocolId: 'p-1',
    createdAt: '2026-10-01T00:00:00Z',
    protokollantId: 'pr-1',
    protokollantName: 'Pia Protokoll',
    isProtokollant: true,
    canControl: true,
    canManage: true,
    canWrite: true,
    canManageVotes: true,
    canVote: true,
    canFinalize: true,
    ...over,
  };
}

function item(over: Partial<AgendaItem> = {}): AgendaItem {
  return { id: 't-1', applicationId: null, title: 'Begrüßung', body: 'Eröffnet.', position: 0, ...over };
}

const AGENDA: AgendaItem[] = [
  item(),
  item({ id: 't-2', title: 'Bericht des Finanzreferats', position: 1, body: 'Zwischenstand.' }),
  item({ id: 't-3', title: 'Antrag Kulturfestival', position: 2, applicationId: 'app-1', nonPublic: true }),
];

function protocol(over: Partial<Protocol> = {}): Protocol {
  return {
    id: 'p-1',
    meetingId: 'm-1',
    markdown: '',
    status: 'draft',
    isFinal: false,
    isLocked: false,
    pdfUrl: null,
    publicPdfUrl: null,
    sentAt: null,
    ...over,
  };
}

const ATTENDANCE: Attendance[] = [
  { principalId: 'pr-1', displayName: 'Pia Protokoll', email: null, status: 'present', source: 'self', isSelf: true },
  { principalId: 'pr-2', displayName: 'Mika Mitglied', email: null, status: 'excused', source: 'lead', isSelf: false },
  { principalId: 'pr-3', displayName: 'Alina Admin', email: null, status: null, source: null, isSelf: false },
];

type Inputs = {
  meeting: Meeting;
  protocol: Protocol | null;
  agenda: AgendaItem[];
  top: AgendaItem | null;
  topIndex: number;
  canEdit: boolean;
  saveState: 'idle' | 'saving' | 'saved' | 'error';
  attendance: Attendance[];
  savingAttendance: boolean;
  viewers: string[];
  casting: string | null;
  deletingVote: string | null;
  finalizing: boolean;
  choices: Record<string, string>;
  assignableOptions: { value: string; label: string }[];
  savingAgenda: boolean;
  renamingTopId: string | null;
  agendaPick: string;
  agendaFreetext: string;
  renameDraft: string;
};

function inputs(over: Partial<Inputs> = {}): Inputs {
  return {
    meeting: meeting(),
    protocol: protocol(),
    agenda: AGENDA,
    top: AGENDA[0],
    topIndex: 0,
    canEdit: true,
    saveState: 'saved',
    attendance: ATTENDANCE,
    savingAttendance: false,
    viewers: ['Pia Protokoll', 'Alina Admin'],
    casting: null,
    deletingVote: null,
    finalizing: false,
    choices: {},
    assignableOptions: [{ value: 'app-9', label: 'Antrag Neun' }],
    savingAgenda: false,
    renamingTopId: null,
    agendaPick: '',
    agendaFreetext: '',
    renameDraft: '',
    ...over,
  };
}

const OUTPUTS = [
  'back', 'selectTop', 'bodyChange', 'castVote', 'voteClose', 'voteCancel', 'voteDelete',
  'voteDialog', 'startSession', 'closeSession', 'finalize', 'openSettings',
  'deleteMeeting', 'toggleBeamer', 'attendanceChange', 'addToAgenda', 'addFreetext',
  'removeFromAgenda', 'startRename', 'cancelRename', 'renameTop', 'setNonPublic', 'dragStart',
  'dragOver', 'drop', 'setProtokollant',
] as const;

async function setup(over: Partial<Inputs> = {}) {
  const on = Object.fromEntries(OUTPUTS.map((name) => [name, jest.fn()])) as Record<
    (typeof OUTPUTS)[number],
    jest.Mock
  >;
  const view = await render(MeetingFocusComponent, {
    inputs: inputs(over),
    on,
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  return { ...view, on, http };
}

interface Internals {
  progress(v: MeetingVote): number;
  isDone(i: number): boolean;
  canAddVote(i: AgendaItem): boolean;
  panel(): string;
}

describe('MeetingFocusComponent', () => {
  describe('bar', () => {
    it('shows the session and hands the controls to the parent', async () => {
      const { on } = await setup();
      expect(screen.getByText('Konstituierende Sitzung')).toBeInTheDocument();
      // The minute-taker is marked in the roster, not spelled out in the bar.
      expect(screen.queryByText(/Pia Protokoll/)).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: /Sitzungen/ }));
      expect(on.back).toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: 'Beamer-Ansicht' }));
      expect(on.toggleBeamer).toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: 'Sitzung bearbeiten' }));
      expect(on.openSettings).toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: 'Sitzung löschen' }));
      expect(on.deleteMeeting).toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: 'Sitzung schließen' }));
      expect(on.closeSession).toHaveBeenCalled();
    });

    it('offers the finalize retry once a closed meeting fell back to a draft', async () => {
      const { on } = await setup({ meeting: meeting({ status: 'closed' }) });
      await userEvent.click(screen.getByRole('button', { name: 'Finalisieren & versenden' }));
      expect(on.finalize).toHaveBeenCalled();
      expect(screen.queryByRole('button', { name: 'Sitzung schließen' })).toBeNull();
    });

    it('hides the finalize retry without the finalize right and says why', async () => {
      await setup({ meeting: meeting({ status: 'closed', canFinalize: false }) });
      expect(screen.queryByRole('button', { name: 'Finalisieren & versenden' })).toBeNull();
      expect(screen.getByText(/Gremien-Recht „Protokoll finalisieren“/)).toBeInTheDocument();
    });
  });

  describe('page', () => {
    it('names the open item, counts its words and reports the save state', async () => {
      await setup({ top: AGENDA[1], topIndex: 1 });
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('TOP 2 · Bericht des Finanzreferats');
      expect(screen.getByText('1 Wörter')).toBeInTheDocument();
      expect(screen.getByText(/Gespeichert/)).toBeInTheDocument();
      expect(screen.getByText('Entwurf')).toBeInTheDocument();
    });

    it('shows the application context and the non-public badge once locked', async () => {
      await setup({
        top: AGENDA[2],
        topIndex: 2,
        protocol: protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf', publicPdfUrl: '/pub.pdf' }),
        meeting: meeting({ status: 'closed' }),
      });
      expect(screen.getByRole('link', { name: 'Antrag öffnen' })).toBeInTheDocument();
      expect(screen.getByText('NÖ')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Internes Protokoll' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Öffentliches Protokoll' })).toBeInTheDocument();
      expect(screen.queryByText(/Gespeichert/)).toBeNull();
    });

    it('offers one PDF link when nothing is redacted', async () => {
      await setup({ protocol: protocol({ status: 'final', isFinal: true, isLocked: true, pdfUrl: '/p.pdf' }) });
      expect(screen.getByRole('link', { name: 'PDF öffnen' })).toBeInTheDocument();
    });

    it('names the minute-taker for a reader who may not type', async () => {
      await setup({ canEdit: false });
      expect(screen.getByText(/Pia Protokoll führt das Protokoll/)).toBeInTheDocument();
    });

    it('explains the empty states', async () => {
      await setup({ top: null, topIndex: -1 });
      expect(screen.getByText('Noch kein TOP geöffnet')).toBeInTheDocument();
      expect(screen.getByText('Wähle links einen TOP, um seinen Text zu bearbeiten.')).toBeInTheDocument();
    });

    it('says that the protocol arrives with the start', async () => {
      // A reader without session rights gets no checklist, only the note.
      await setup({
        protocol: null,
        meeting: meeting({ status: 'planned', canControl: false, canManage: false }),
      });
      expect(screen.getByText(/beim Start der Sitzung angelegt/)).toBeInTheDocument();
      expect(screen.getByText('Noch nicht eröffnet')).toBeInTheDocument();
      expect(screen.queryByText('Sitzung vorbereiten')).toBeNull();
    });

    it('says that there is no protocol on a live meeting without one', async () => {
      await setup({ protocol: null });
      expect(screen.getByText('Für diese Sitzung gibt es noch kein Protokoll.')).toBeInTheDocument();
    });
  });

  describe('dock', () => {
    it('steps through the agenda and disables the edges', async () => {
      const { on } = await setup();
      expect(screen.getByRole('button', { name: 'Vorheriger TOP' })).toBeDisabled();
      await userEvent.click(screen.getByRole('button', { name: 'Nächster TOP' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
    });

    it('disables the next step on the last item', async () => {
      await setup({ top: AGENDA[2], topIndex: 2 });
      expect(screen.getByRole('button', { name: 'Nächster TOP' })).toBeDisabled();
    });

    it('opens the agenda popover from the now chip and jumps from a row', async () => {
      const { on, fixture } = await setup();
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const popover = screen.getByRole('dialog', { name: 'Tagesordnung' });
      expect(within(popover).getByText('jetzt')).toBeInTheDocument();
      await userEvent.click(within(popover).getByText('Bericht des Finanzreferats'));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
      expect((fixture.componentInstance as unknown as Internals).panel()).toBe('none');
    });

    it('marks the items before now as handled', async () => {
      const { fixture } = await setup({ meeting: meeting({ currentAgendaItemId: 't-2' }), top: AGENDA[1], topIndex: 1 });
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      expect(screen.getByText('behandelt')).toBeInTheDocument();
      const c = fixture.componentInstance as unknown as Internals;
      expect(c.isDone(0)).toBe(true);
      expect(c.isDone(2)).toBe(false);
    });

    it('closes the popover on the backdrop, on the close button and on escape', async () => {
      const { fixture } = await setup();
      const c = fixture.componentInstance as unknown as Internals;
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
      expect(c.panel()).toBe('none');
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      await userEvent.keyboard('{Escape}');
      expect(c.panel()).toBe('none');
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      // A second click on the chip closes it again.
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      expect(c.panel()).toBe('none');
    });

    it('opens the attendance popover with the room state and the viewers', async () => {
      const { http } = await setup();
      await userEvent.click(screen.getByTitle('Anwesenheit'));
      const popover = screen.getByRole('dialog', { name: 'Anwesenheit' });
      expect(within(popover).getByText('Anwesend 1 von 3')).toBeInTheDocument();
      expect(within(popover).getByText('Mika Mitglied')).toBeInTheDocument();
      expect(within(popover).getByText('Protokollant')).toBeInTheDocument();
      // Once in the roster, once in the viewer list.
      expect(within(popover).getAllByText('Alina Admin')).toHaveLength(2);
      expect(within(popover).getByText('2 live')).toBeInTheDocument();
      http.match((r) => r.url.includes('/delegations/')).forEach((req) => req.flush({
        meetingId: 'm-1', gremiumId: 'g-1', allowVoteDelegation: false, votingDelegationEnabled: false,
        delegationAllowExternal: false, deadline: null, deadlinePassed: false, meetingStarted: true,
        canDelegate: false, myDelegation: null, incoming: [], recipients: [],
      }));
    });

    it('offers the start while the meeting is planned', async () => {
      const { on } = await setup({ meeting: meeting({ status: 'planned' }), protocol: null });
      // The checklist and the dock both carry the start.
      const starts = screen.getAllByRole('button', { name: 'Sitzung eröffnen' });
      expect(starts).toHaveLength(2);
      await userEvent.click(starts[0]);
      await userEvent.click(starts[1]);
      expect(on.startSession).toHaveBeenCalledTimes(2);
    });

    it('asks for a minute-taker before the start', async () => {
      await setup({ meeting: meeting({ status: 'planned', protokollantId: null, protokollantName: null }), protocol: null });
      screen
        .getAllByRole('button', { name: /Sitzung eröffnen/ })
        .forEach((b) => expect(b).toBeDisabled());
      expect(screen.getByText('Protokollant zuweisen, um die Sitzung zu starten.')).toBeInTheDocument();
    });

    it('offers a decision question when the open item has no vote', async () => {
      const { on } = await setup();
      await userEvent.click(screen.getByRole('button', { name: 'Beschlussfrage hinzufügen' }));
      expect(on.voteDialog).toHaveBeenCalledWith(AGENDA[0]);
    });

    it('offers the application vote once per application item', async () => {
      const { fixture } = await setup({ top: AGENDA[2], topIndex: 2, meeting: meeting({ currentAgendaItemId: 't-3' }) });
      expect(screen.getByRole('button', { name: 'Abstimmung öffnen' })).toBeInTheDocument();
      const c = fixture.componentInstance as unknown as Internals;
      expect(c.canAddVote(AGENDA[2])).toBe(true);
      expect(c.canAddVote(AGENDA[0])).toBe(true);
    });

    it('runs an open vote: question row, ballot, close and cancel', async () => {
      const v = vote();
      const { on, fixture } = await setup({ meeting: meeting({ votes: [v] }), choices: { 'v-1': 'no' } });
      expect(screen.getByText('Wird der Nachtragshaushalt beschlossen?')).toBeInTheDocument();
      expect(screen.getByText('3 von 4 Anwesenden haben abgestimmt')).toBeInTheDocument();
      expect(screen.getByText('Deine Stimme')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Ja' }));
      expect(on.castVote).toHaveBeenCalledWith({ voteId: 'v-1', choice: 'yes' });
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung schließen' }));
      expect(on.voteClose).toHaveBeenCalledWith('v-1');
      await userEvent.click(screen.getByRole('button', { name: 'Abstimmung abbrechen' }));
      expect(on.voteCancel).toHaveBeenCalledWith('v-1');
      const c = fixture.componentInstance as unknown as Internals;
      expect(c.progress(v)).toBe(75);
      expect(c.progress(vote({ present: 0 }))).toBe(0);
    });

    it('groups the options and the vote actions, so a phone gets clean rows', async () => {
      const { container } = await setup({ meeting: meeting({ votes: [vote()] }) });
      const options = container.querySelectorAll('.fx__ballot app-button');
      expect(options).toHaveLength(3);
      // Each option fills its share of the row, so the three read as one group.
      options.forEach((btn) => expect(btn).toHaveClass('btn-block'));
      const actions = container.querySelectorAll('.fx__voteAdmin app-button');
      expect(actions).toHaveLength(2);
      actions.forEach((btn) => expect(btn).toHaveClass('btn-block'));
    });

    it('shows the revealed tally of an open vote', async () => {
      await setup({ meeting: meeting({ votes: [vote({ revealed: true, counts: { yes: 3, no: 1 }, leading: 'yes' })] }) });
      expect(screen.getByRole('button', { name: 'Ja' })).toBeInTheDocument();
      expect(screen.getAllByText('3').length).toBeGreaterThan(0);
    });

    it('carries the result until it is in the text, then goes quiet', async () => {
      const closed = vote({ status: 'closed', result: 'passed', counts: { yes: 3, no: 1, abstain: 0 }, leading: 'yes', revealed: true });
      // A trailing hard break from a phone keyboard must not survive as an empty line.
      const { on } = await setup({ meeting: meeting({ votes: [closed] }), top: item({ body: 'Aussprache.\\\n' }) });
      expect(screen.getByText('Angenommen')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' }));
      const payload = on.bodyChange.mock.calls[0][0] as { itemId: string; body: string };
      expect(payload.itemId).toBe('t-1');
      // The same callout the backend writes: marker line with the bold question, one tally line.
      expect(payload.body).toBe(
        'Aussprache.\n\n> [!abstimmung] **Wird der Nachtragshaushalt beschlossen?**\n> yes: 3, no: 1, abstain: 0',
      );
      // A closed vote is part of the record: no delete (409 `vote_not_deletable`).
      expect(screen.queryByRole('button', { name: 'Beschlussfrage löschen' })).toBeNull();
      expect(on.voteDelete).not.toHaveBeenCalled();
    });

    it('names a quorum failure and hides the insert for a reader', async () => {
      const rejected = vote({ status: 'closed', result: 'rejected', failedReason: 'quorum', counts: { yes: 1, no: 0, abstain: 0 } });
      await setup({ meeting: meeting({ votes: [rejected] }), canEdit: false });
      expect(screen.getByText('Quorum nicht erreicht')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' })).toBeNull();
    });

    it('keeps a finished vote reachable once its result is in the text', async () => {
      const closed = vote({ status: 'closed', result: 'passed', counts: { yes: 3 } });
      const cancelled = vote({ id: 'v-2', status: 'cancelled', question: 'Vertagen?' });
      const { on } = await setup({
        meeting: meeting({ votes: [closed, cancelled] }),
        top: item({ body: 'Text\n\n> [!abstimmung] **Wird der Nachtragshaushalt beschlossen?**\n> yes: 3' }),
      });
      expect(screen.getByText('Angenommen')).toBeInTheDocument();
      expect(screen.getByText('Abgebrochen')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Ergebnis ins Protokoll übernehmen' })).toBeNull();
      // Only the cancelled vote offers the delete; the closed one is part of the record.
      const deletes = screen.getAllByRole('button', { name: 'Beschlussfrage löschen' });
      expect(deletes).toHaveLength(1);
      await userEvent.click(deletes[0]);
      expect(on.voteDelete).toHaveBeenCalledWith('v-2');
      expect(screen.getByRole('button', { name: 'Beschlussfrage hinzufügen' })).toBeInTheDocument();
    });

    it('names the concealed tally of a secret vote', async () => {
      await setup({ meeting: meeting({ votes: [vote({ revealed: false })] }) });
      expect(screen.getByText(/Zwischenstand sichtbar/)).toBeInTheDocument();
    });

    it('offers no close on a planned meeting: one that does not take place is deleted', async () => {
      const { on } = await setup({ meeting: meeting({ status: 'planned' }), protocol: null });
      expect(screen.queryByRole('button', { name: 'Sitzung schließen' })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Sitzung löschen' }));
      expect(on.deleteMeeting).toHaveBeenCalled();
    });

    it('keeps the votes of a closed meeting: no vote delete after the close', async () => {
      // A cancelled vote is deletable in a live meeting, but not after the close.
      const cancelled = vote({ status: 'cancelled', question: 'Vertagen?' });
      await setup({ meeting: meeting({ status: 'closed', votes: [cancelled] }) });
      expect(screen.getByText('Abgebrochen')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Beschlussfrage löschen' })).toBeNull();
    });

    it('points back to now when the open item is not the one the room handles', async () => {
      const { on } = await setup({ meeting: meeting({ currentAgendaItemId: 't-2' }) });
      expect(screen.getByText(/Jetzt läuft TOP 2 · Bericht des Finanzreferats/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Jetzt' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-2');
    });

    it('shows the room state chip without the live count for a plain writer', async () => {
      await setup({ meeting: meeting({ canWrite: false, canManageVotes: false, canControl: false }) });
      expect(screen.getByText('Anwesend 1 von 3')).toBeInTheDocument();
      expect(screen.queryByText('2 live')).toBeNull();
    });
  });

  describe('preparation of a planned meeting', () => {
    const planned = (over: Partial<Meeting> = {}) => meeting({ status: 'planned', ...over });

    it('lists what the start needs and opens the matching panel from every row', async () => {
      await setup({ meeting: planned(), protocol: null });
      expect(screen.getByRole('heading', { name: 'Sitzung vorbereiten' })).toBeInTheDocument();
      expect(screen.getAllByText('3 TOPs vorbereitet').length).toBeGreaterThan(0);
      expect(screen.getByText('1 von 3 anwesend')).toBeInTheDocument();
      // No neighbour arrows before the start: there is no protocol to page through.
      expect(screen.queryByRole('button', { name: /Nächster TOP:/ })).toBeNull();

      await userEvent.click(screen.getByRole('button', { name: 'Tagesordnung bearbeiten' }));
      expect(screen.getByRole('dialog', { name: 'Tagesordnung' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Erfassen' }));
      expect(screen.getByRole('dialog', { name: 'Anwesenheit' })).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: 'Ändern' }));
      expect(screen.getByRole('dialog', { name: 'Protokollant wählen' })).toBeInTheDocument();
    });

    it('marks a missing protokollant in the checklist and in the dock', async () => {
      const { container } = await setup({
        meeting: planned({ protokollantId: null, protokollantName: null }),
        protocol: null,
      });
      expect(screen.getByText('Noch nicht zugewiesen – nötig zum Eröffnen')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Zuweisen' })).toBeInTheDocument();
      const chip = screen.getByRole('button', { name: /Protokollant wählen/ });
      expect(chip).toHaveClass('fx__chip--warn');
      expect(chip).toHaveAttribute('aria-expanded', 'false');
      await userEvent.click(chip);
      expect(chip).toHaveAttribute('aria-expanded', 'true');
      expect(container.querySelector('.fx__sheet--mid')).toBeTruthy();
    });

    it('names the protokollant on the dock chip once one is set', async () => {
      await setup({ meeting: planned(), protocol: null });
      const chip = screen.getByRole('button', { name: /Protokoll: Pia Protokoll/ });
      expect(chip).not.toHaveClass('fx__chip--warn');
    });

    it('searches the roster and names the picked member', async () => {
      const { on } = await setup({
        meeting: planned({ protokollantId: null, protokollantName: null }),
        protocol: null,
      });
      await userEvent.click(screen.getByRole('button', { name: /Protokollant wählen/ }));
      const picker = screen.getByRole('dialog', { name: 'Protokollant wählen' });
      // Initials, the attendance state and the open state of an unrecorded row.
      expect(within(picker).getByText('PP')).toBeInTheDocument();
      expect(within(picker).getByText('Anwesend')).toBeInTheDocument();
      expect(within(picker).getByText('Offen')).toBeInTheDocument();

      await userEvent.type(within(picker).getByRole('searchbox', { name: 'Mitglied suchen' }), 'mika');
      expect(within(picker).getAllByRole('button', { name: /Mika Mitglied/ })).toHaveLength(1);
      expect(within(picker).queryByRole('button', { name: /Alina Admin/ })).toBeNull();

      await userEvent.clear(within(picker).getByRole('searchbox', { name: 'Mitglied suchen' }));
      await userEvent.type(within(picker).getByRole('searchbox', { name: 'Mitglied suchen' }), 'zzz');
      expect(within(picker).getByText('Kein Mitglied gefunden.')).toBeInTheDocument();

      await userEvent.clear(within(picker).getByRole('searchbox', { name: 'Mitglied suchen' }));
      await userEvent.click(within(picker).getByRole('button', { name: /Alina Admin/ }));
      expect(on.setProtokollant).toHaveBeenCalledWith('pr-3');
      expect(screen.queryByRole('dialog', { name: 'Protokollant wählen' })).toBeNull();
    });

    it('does not send the protokollant that is already set', async () => {
      const { on } = await setup({ meeting: planned(), protocol: null });
      await userEvent.click(screen.getByRole('button', { name: /Protokoll: Pia Protokoll/ }));
      const current = screen.getByRole('button', { name: /Pia Protokoll/, pressed: true });
      await userEvent.click(current);
      expect(on.setProtokollant).not.toHaveBeenCalled();
    });

    it('falls back to the e-mail and the id for a member without a name', async () => {
      await setup({
        meeting: planned(),
        protocol: null,
        attendance: [
          { principalId: 'pr-7', displayName: null, email: 'kai.klar@x.de', status: 'absent', source: null, isSelf: false },
          { principalId: 'pr-8', displayName: null, email: null, status: null, source: null, isSelf: false },
        ],
      });
      await userEvent.click(screen.getByRole('button', { name: /Protokoll: Pia Protokoll/ }));
      const picker = screen.getByRole('dialog', { name: 'Protokollant wählen' });
      expect(within(picker).getByText('kai.klar@x.de')).toBeInTheDocument();
      expect(within(picker).getByText('KK')).toBeInTheDocument();
      expect(within(picker).getByText('pr-8')).toBeInTheDocument();
      await userEvent.type(within(picker).getByRole('searchbox', { name: 'Mitglied suchen' }), 'kai');
      expect(within(picker).queryByText('pr-8')).toBeNull();
    });

    it('shows a plain warning to a lead who may not name the protokollant', async () => {
      await setup({
        meeting: planned({ protokollantId: null, protokollantName: null, canManage: false }),
        protocol: null,
      });
      expect(screen.getByText('Protokollant fehlt')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Protokollant wählen/ })).toBeNull();
      expect(screen.queryByRole('button', { name: 'Zuweisen' })).toBeNull();
    });

    it('offers the checklist without the start to a manager who may not start', async () => {
      await setup({ meeting: planned({ canControl: false }), protocol: null });
      expect(screen.getByRole('heading', { name: 'Sitzung vorbereiten' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Sitzung eröffnen' })).toBeNull();
    });
  });

  describe('neighbour arrows', () => {
    it('steps to the items beside the open one', async () => {
      const { on } = await setup({ top: AGENDA[1], topIndex: 1 });
      await userEvent.click(screen.getByRole('button', { name: 'Vorheriger TOP: TOP 1 · Begrüßung' }));
      expect(on.selectTop).toHaveBeenCalledWith('t-1');
      await userEvent.click(
        screen.getByRole('button', { name: 'Nächster TOP: TOP 3 · Antrag Kulturfestival' }),
      );
      expect(on.selectTop).toHaveBeenCalledWith('t-3');
    });

    it('drops the arrow at an edge and names an untitled neighbour', async () => {
      await setup({ agenda: [AGENDA[0], item({ id: 't-2', title: '', position: 1 })] });
      expect(screen.queryByRole('button', { name: /Vorheriger TOP:/ })).toBeNull();
      expect(screen.getByRole('button', { name: /Nächster TOP: TOP 2 · / })).toBeInTheDocument();
    });

    it('shows no arrows while no item is open', async () => {
      await setup({ top: null, topIndex: -1 });
      expect(screen.queryByRole('button', { name: /Nächster TOP:/ })).toBeNull();
    });
  });

  describe('agenda popover', () => {
    it('edits the agenda: rename, remove, non-public, add paths and reorder', async () => {
      const { on } = await setup({ agendaPick: 'app-9' });
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const popover = screen.getByRole('dialog', { name: 'Tagesordnung' });
      await userEvent.click(within(popover).getAllByRole('button', { name: 'TOP umbenennen' })[0]);
      expect(on.startRename).toHaveBeenCalledWith(AGENDA[0]);
      await userEvent.click(within(popover).getAllByRole('button', { name: 'Entfernen' })[1]);
      expect(on.removeFromAgenda).toHaveBeenCalledWith('t-2');
      await userEvent.click(within(popover).getAllByRole('checkbox')[0]);
      expect(on.setNonPublic).toHaveBeenCalledWith({ item: AGENDA[0], nonPublic: true });
      await userEvent.type(within(popover).getByPlaceholderText(/Freitext-TOP/), 'Verschiedenes{Enter}');
      expect(on.addFreetext).toHaveBeenCalled();
      await userEvent.click(within(popover).getByRole('button', { name: 'Hinzufügen' }));
      expect(on.addToAgenda).toHaveBeenCalled();
      const rows = within(popover).getAllByRole('listitem');
      rows[0].dispatchEvent(new Event('dragstart'));
      rows[1].dispatchEvent(new Event('dragover'));
      rows[1].dispatchEvent(new Event('drop'));
      expect(on.dragStart).toHaveBeenCalledWith(0);
      expect(on.dragOver).toHaveBeenCalled();
      expect(on.drop).toHaveBeenCalledWith(1);
    });

    it('renames inline and lets escape cancel', async () => {
      const { on } = await setup({ renamingTopId: 't-1', renameDraft: 'Begrüßung neu' });
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const input = screen.getByRole('textbox', { name: 'TOP umbenennen' });
      fireEvent.keyUp(input, { key: 'Enter' });
      expect(on.renameTop).toHaveBeenCalledWith(AGENDA[0]);
      fireEvent.keyUp(input, { key: 'Escape' });
      expect(on.cancelRename).toHaveBeenCalled();
      fireEvent.blur(input);
      expect(on.renameTop).toHaveBeenCalledTimes(2);
    });

    it('hides the editing controls once the protocol is locked', async () => {
      await setup({ protocol: protocol({ isLocked: true, status: 'rendering' }) });
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const popover = screen.getByRole('dialog', { name: 'Tagesordnung' });
      expect(within(popover).queryByPlaceholderText(/Freitext-TOP/)).toBeNull();
      expect(within(popover).queryByRole('button', { name: 'Entfernen' })).toBeNull();
    });

    it('keeps only the non-public flag once the meeting is closed', async () => {
      await setup({ meeting: meeting({ status: 'closed' }) });
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const popover = screen.getByRole('dialog', { name: 'Tagesordnung' });
      expect(within(popover).queryByPlaceholderText(/Freitext-TOP/)).toBeNull();
      expect(within(popover).queryByRole('button', { name: 'Entfernen' })).toBeNull();
      expect(within(popover).queryByRole('button', { name: 'TOP umbenennen' })).toBeNull();
      expect(within(popover).getAllByRole('listitem')[0].getAttribute('draggable')).toBe('false');
      // The protocol is still a draft, so the flag for the public PDF stays open.
      expect(within(popover).getAllByRole('checkbox')).toHaveLength(AGENDA.length);
    });

    it('disables the remove of an item with an open or closed vote and says why', async () => {
      const votes = [
        vote({ agendaItemId: 't-1', status: 'closed', result: 'passed' }),
        vote({ id: 'v-2', agendaItemId: 't-2', status: 'cancelled' }),
        vote({ id: 'v-3', agendaItemId: 't-3', status: 'open' }),
      ];
      await setup({ meeting: meeting({ votes }) });
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const popover = screen.getByRole('dialog', { name: 'Tagesordnung' });
      const removes = within(popover).getAllByRole('button', { name: 'Entfernen' });
      expect(removes[0]).toBeDisabled();
      expect(removes[0].getAttribute('title')).toMatch(/bleibt auf der Tagesordnung/);
      // A cancelled vote goes with its item.
      expect(removes[1]).not.toBeDisabled();
      expect(removes[2]).toBeDisabled();
    });

    it('disables the remove of an item with votes without the vote right', async () => {
      const votes = [vote({ id: 'v-2', agendaItemId: 't-2', status: 'cancelled' })];
      await setup({ meeting: meeting({ votes, canManageVotes: false }) });
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      const popover = screen.getByRole('dialog', { name: 'Tagesordnung' });
      const removes = within(popover).getAllByRole('button', { name: 'Entfernen' });
      // The agenda right alone removes an item without votes.
      expect(removes[0]).not.toBeDisabled();
      expect(removes[1]).toBeDisabled();
      expect(removes[1].getAttribute('title')).toMatch(/Nur wer die Abstimmungen/);
    });

    it('shows the empty agenda hint', async () => {
      await setup({ agenda: [], top: null, topIndex: -1 });
      expect(screen.getByText('0 TOPs vorbereitet')).toBeInTheDocument();
      await userEvent.click(screen.getByTitle('Tagesordnung öffnen'));
      expect(screen.getByText('Noch keine Anträge auf der Tagesordnung.')).toBeInTheDocument();
    });
  });
});
