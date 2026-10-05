import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Delegation, MeetingDelegationContext } from '@core/api/delegations.service';
import type { AgendaItem, Attendance, Meeting, Vote } from '@core/api/models';
import { MEDIA } from '@stupa-makers/ui-kit';
import { AGENDA, DELEGATION_CONTEXT, item, matchMediaQueries, meeting, vote } from '../../../testing/meeting-fixtures';
import { MeetingFollowViewComponent, plainText } from './meeting-follow-view.component';

const CONTEXT_URL = '/api/delegations/meetings/m-1/context';

/** A plain member: no write, no manage right. Mara Keller keeps the minutes. */
function member(over: Partial<Meeting> = {}): Meeting {
  return meeting({
    isProtokollant: false,
    canControl: false,
    canManage: false,
    canWrite: false,
    canManageVotes: false,
    canFinalize: false,
    canVote: true,
    protokollantId: 'pr-9',
    protokollantName: 'Mara Keller',
    startedAt: '2026-10-15T16:04:00Z',
    currentAgendaItemId: 't-2',
    ...over,
  });
}

const ME: Attendance = {
  principalId: 'pr-1',
  displayName: 'Paul Neumann',
  email: null,
  status: null,
  source: null,
  note: null,
  isSelf: true,
};

/** A delegation of the meeting, from Jonas Weber to the member. */
const INCOMING: Delegation = {
  id: 'd-2', meetingId: 'm-1', meetingTitle: null, meetingDate: null, gremiumId: 'g-1', gremiumName: null,
  delegatorId: 'pr-4', delegatorName: 'Jonas Weber', delegateId: 'pr-1', delegateName: 'Paul Neumann',
  delegateVoting: true, viaPool: false, createdAt: '2026-10-01T00:00:00Z', revocable: false, direction: 'incoming',
};

/** Two other members of the roster: the minute-taker and an absent member. */
const OTHERS: Attendance[] = [
  { principalId: 'pr-9', displayName: 'Mara Keller', email: null, status: 'present', source: 'lead', note: null, isSelf: false },
  { principalId: 'pr-3', displayName: 'Tom Brandt', email: null, status: 'absent', source: 'lead', note: null, isSelf: false },
];

function rest(over: Partial<Vote> = {}): Vote {
  return {
    id: 'v-1',
    applicationId: null,
    meetingId: 'm-1',
    agendaItemId: 't-2',
    question: 'Wird der Nachtragshaushalt beschlossen?',
    eligibleGroup: 'g-1',
    config: { options: ['yes', 'no', 'abstain'], majorityRule: 'simple', quorum: { type: 'count', value: 12 } },
    status: 'open',
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    tally: { counts: {}, eligible: 19, voted: 14, present: 19, revealed: false, quorumMet: true, leading: null },
    canCast: true,
    myBallot: { cast: false, choice: null },
    representedCast: false,
    ...over,
  };
}

interface Options {
  meeting?: Meeting;
  agenda?: AgendaItem[];
  attendance?: Attendance[];
  media?: string[];
}

let restore: () => void = () => {};

async function setup(opts: Options = {}) {
  restore = matchMediaQueries(...(opts.media ?? [MEDIA.wide, MEDIA.notPhone]));
  const back = jest.fn();
  const attendanceChange = jest.fn();
  const view = await render(MeetingFollowViewComponent, {
    inputs: {
      meeting: opts.meeting ?? member(),
      agenda: opts.agenda ?? AGENDA,
      attendance: opts.attendance ?? [ME],
      savingAttendance: false,
    },
    on: { back, attendanceChange },
    providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const context = (over: Partial<MeetingDelegationContext> = {}) => {
    http.match(CONTEXT_URL).forEach((r) => r.flush({ ...DELEGATION_CONTEXT, ...over }));
    view.fixture.detectChanges();
  };
  /** Answer the reads of the vote card. */
  const voteReads = (v: Vote, status = { blocked: false, delegatedToName: null, exercising: false, delegatedByName: null }) => {
    http.match(`/api/votes/${v.id}`).forEach((r) => r.flush(v));
    http.match(`/api/delegations/votes/${v.id}/status`).forEach((r) => r.flush(status));
    view.fixture.detectChanges();
  };
  return { ...view, http, back, attendanceChange, context, voteReads };
}

afterEach(() => restore());

describe('MeetingFollowViewComponent', () => {
  describe('planned meeting (board Teilnahme-Vorher)', () => {
    const planned = () => member({ status: 'planned', startedAt: null, currentAgendaItemId: null });

    it('says when the meeting starts and links the calendar', async () => {
      const { context } = await setup({ meeting: planned() });
      context();
      expect(screen.getByRole('heading', { level: 1, name: 'Konstituierende Sitzung' })).toBeInTheDocument();
      expect(screen.getByText('Geplant')).toBeInTheDocument();
      expect(screen.getByText('StuPa · Do., 15.10.2026 · 18:00')).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Die Sitzung beginnt am Do., 15.10.2026 um 18:00' })).toBeInTheDocument();
      expect(screen.getByRole('link', { name: 'Kalender abonnieren' })).toHaveAttribute('href', '/account/calendar');
      // No dock before the start.
      expect(screen.queryByRole('contentinfo')).toBeNull();
    });

    it('says the date alone without a time, and that the date is open without one', async () => {
      const { fixture, context } = await setup({ meeting: { ...planned(), startTime: null } });
      context();
      expect(screen.getByRole('heading', { name: 'Die Sitzung beginnt am Do., 15.10.2026' })).toBeInTheDocument();
      fixture.componentRef.setInput('meeting', { ...planned(), date: null, gremiumName: null });
      fixture.detectChanges();
      expect(screen.getByRole('heading', { name: 'Der Termin der Sitzung steht noch nicht fest.' })).toBeInTheDocument();
    });

    it('reports the own attendance as present or excused only', async () => {
      const { attendanceChange, context } = await setup({ meeting: planned() });
      context();
      const side = screen.getByRole('complementary', { name: 'Teilnahme' });
      await userEvent.click(within(side).getByRole('radio', { name: 'Abwesend' }));
      expect(attendanceChange).toHaveBeenCalledWith({ member: ME, status: 'excused' });
      await userEvent.click(within(side).getByRole('radio', { name: 'Anwesend' }));
      expect(attendanceChange).toHaveBeenLastCalledWith({ member: ME, status: 'present' });
    });

    it('keeps the record of the lead (O15)', async () => {
      const { context } = await setup({
        meeting: planned(),
        attendance: [{ ...ME, status: 'excused', source: 'lead' }],
      });
      context();
      expect(screen.queryByRole('radio', { name: 'Anwesend' })).toBeNull();
      expect(screen.getByText('durch Sitzungsleitung')).toBeInTheDocument();
    });

    it('shows the delegation setup with its deadline and locks "Anwesend" while delegated', async () => {
      const { context, fixture } = await setup({ meeting: planned() });
      context({ allowVoteDelegation: true, canDelegate: true, meetingStarted: false, deadline: '2026-10-15T15:00:00Z' });
      expect(screen.getByText(/^Einrichtbar bis Do\., 15\.10\.2026/)).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: 'Anwesend' })).toBeEnabled();
      // The card reports an own delegation: the member cannot report "Anwesend" (O23).
      const card = fixture.debugElement.query((el) => el.name === 'app-meeting-delegation-card');
      (card.componentInstance as { reload(): void }).reload();
      context({
        allowVoteDelegation: true,
        canDelegate: true,
        meetingStarted: false,
        myDelegation: {
          id: 'd-1', meetingId: 'm-1', meetingTitle: null, meetingDate: null, gremiumId: 'g-1', gremiumName: null,
          delegatorId: 'pr-1', delegatorName: 'Paul Neumann', delegateId: 'pr-7', delegateName: 'Emma Vogel',
          delegateVoting: true, viaPool: true, createdAt: '2026-10-01T00:00:00Z', revocable: true, direction: 'outgoing',
        },
      });
      expect(screen.getByText('Du wirst vertreten von Emma Vogel.')).toBeInTheDocument();
      expect(screen.getByRole('radio', { name: 'Anwesend' })).toBeDisabled();
    });

    it('shows the attendance of all members before the start', async () => {
      const { context } = await setup({ meeting: planned(), attendance: [ME, ...OTHERS] });
      context();
      await userEvent.click(screen.getByRole('button', { name: 'Alle Mitglieder anzeigen' }));
      const sheet = screen.getByRole('dialog', { name: 'Alle Mitglieder' });
      const rows = within(sheet).getAllByRole('listitem');
      expect(rows).toHaveLength(3);
      expect(rows[0]).toHaveTextContent('Paul Neumann (du)');
      expect(rows[0]).toHaveTextContent('Offen');
      expect(rows[1]).toHaveTextContent('Protokollführung');
    });

    it('opens an item from the agenda and closes it again with a second click', async () => {
      const { context } = await setup({ meeting: planned() });
      context();
      await userEvent.click(screen.getByRole('button', { name: /Bericht des Finanzreferats/ }));
      expect(screen.getByRole('heading', { level: 1, name: 'Bericht des Finanzreferats' })).toBeInTheDocument();
      expect(screen.queryByText('Kalender abonnieren')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: /Bericht des Finanzreferats/ }));
      expect(screen.getByText('Kalender abonnieren')).toBeInTheDocument();
    });

    it('goes back to the list', async () => {
      const { back, context } = await setup({ meeting: planned() });
      context();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Sitzungen' }));
      expect(back).toHaveBeenCalled();
    });
  });

  describe('live meeting (board Teilnahme-Live)', () => {
    it('follows the item of the room and names the minute-taker', async () => {
      const { context } = await setup();
      context();
      expect(screen.getByText(/^StuPa · Do\., 15\.10\.2026 · seit \d\d:04$/)).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1, name: 'Bericht des Finanzreferats' })).toBeInTheDocument();
      expect(screen.getByText('Jetzt')).toBeInTheDocument();
      expect(screen.getByText('Mara Keller führt das Protokoll')).toBeInTheDocument();
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText('TOP 2')).toBeInTheDocument();
      expect(within(dock).getByText(/von 3 · Bericht des Finanzreferats/)).toBeInTheDocument();
    });

    it('reads another item and goes back to the room', async () => {
      const { context } = await setup();
      context();
      await userEvent.click(screen.getByRole('button', { name: /Antrag Kulturfestival/ }));
      expect(screen.getByRole('heading', { level: 1, name: 'Antrag Kulturfestival' })).toBeInTheDocument();
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText('Jetzt läuft TOP 2 · Bericht des Finanzreferats')).toBeInTheDocument();
      await userEvent.click(within(dock).getByRole('button', { name: 'Zurück zu Jetzt' }));
      expect(screen.getByRole('heading', { level: 1, name: 'Bericht des Finanzreferats' })).toBeInTheDocument();
      // A click on the item of the room follows the room again.
      await userEvent.click(screen.getByRole('button', { name: /Begrüßung/ }));
      await userEvent.click(screen.getByRole('button', { name: /Bericht des Finanzreferats/ }));
      expect(within(dock).queryByRole('button', { name: 'Zurück zu Jetzt' })).toBeNull();
    });

    it('shows the open vote with the two-step ballot of the own row and the represented row', async () => {
      const open = vote({ id: 'v-1', agendaItemId: 't-2', voted: 14, present: 19 });
      const { context, voteReads, http } = await setup({ meeting: member({ votes: [open] }) });
      context();
      voteReads(rest(), { blocked: false, delegatedToName: null, exercising: true, delegatedByName: 'Jonas Weber' });
      const side = screen.getByRole('complementary', { name: 'Teilnahme' });
      expect(within(side).getByText('Abstimmung offen')).toBeInTheDocument();
      expect(within(side).getByRole('group', { name: 'Deine Stimme' })).toBeInTheDocument();
      expect(within(side).getByRole('group', { name: 'Als Vertretung für Jonas Weber' })).toBeInTheDocument();
      expect(within(side).getByText('14 von 19 Anwesenden haben abgestimmt')).toBeInTheDocument();
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText(/Deine Stimme/)).toBeInTheDocument();
      expect(within(dock).getByText('offen')).toBeInTheDocument();
      expect(within(dock).getByText('Vertretung: noch offen')).toBeInTheDocument();
      // Step 1 picks, step 2 casts the own ballot over REST.
      await userEvent.click(within(within(side).getByRole('group', { name: 'Deine Stimme' })).getByRole('button', { name: 'Ja' }));
      await userEvent.click(within(side).getByRole('button', { name: 'Stimme abgeben: Ja' }));
      const cast = http.expectOne('/api/votes/v-1/ballot');
      expect(cast.request.body).toEqual({ choice: 'yes', asDelegation: false });
      cast.flush({ status: 'cast' });
      voteReads(rest({ myBallot: { cast: true, choice: 'yes' }, representedCast: true }));
      expect(within(dock).getByText('Ja')).toBeInTheDocument();
      expect(within(dock).getByText('Vertretung: abgegeben')).toBeInTheDocument();
    });

    it('names a secret own ballot only as cast', async () => {
      const open = vote({ id: 'v-1', agendaItemId: 't-2' });
      const { context, voteReads } = await setup({ meeting: member({ votes: [open] }) });
      context();
      voteReads(rest({ secret: true, myBallot: { cast: true, choice: null } }));
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText('abgegeben')).toBeInTheDocument();
    });

    it('shows the result of the shown item once its vote closed', async () => {
      const done = vote({ id: 'v-9', agendaItemId: 't-2', status: 'closed', result: 'passed' });
      const { context, voteReads } = await setup({ meeting: member({ votes: [vote({ id: 'v-0', agendaItemId: 't-1', status: 'closed' }), done] }) });
      context();
      voteReads(
        rest({
          id: 'v-9',
          status: 'closed',
          result: 'passed',
          tally: { counts: { yes: 15, no: 3, abstain: 2 }, eligible: 20, voted: 20, present: 0, revealed: true, quorumMet: true, leading: 'yes' },
        }),
      );
      expect(screen.getByText('Abstimmung geschlossen')).toBeInTheDocument();
      expect(screen.getByText('Angenommen')).toBeInTheDocument();
      // No ballot line in the dock after the close.
      expect(screen.queryByText(/Deine Stimme:/)).toBeNull();
    });

    it('shows the new text of the item of the room after a read of the agenda', async () => {
      const { context, fixture, container } = await setup();
      context();
      const text = () => container.querySelector('app-top-sheet .ProseMirror')?.textContent ?? '';
      expect(text()).toContain('Zwischenstand.');
      // The same item with a new text, as the reload after a meeting_state gives it.
      fixture.componentRef.setInput(
        'agenda',
        AGENDA.map((a) => (a.id === 't-2' ? { ...a, body: 'Zwischenstand. Der Haushalt ist ausgeglichen.' } : a)),
      );
      fixture.detectChanges();
      expect(text()).toContain('Der Haushalt ist ausgeglichen.');
    });

    it('lists the earlier results of the shown item and the votes without an item', async () => {
      const first = vote({ id: 'v-7', agendaItemId: 't-2', status: 'closed', result: 'rejected', question: 'Erste Lesung?' });
      const last = vote({ id: 'v-9', agendaItemId: 't-2', status: 'closed', result: 'passed', question: 'Zweite Lesung?' });
      const loose = vote({ id: 'v-5', agendaItemId: null, status: 'closed', result: 'passed', question: 'Antrag zur Geschäftsordnung?' });
      const other = vote({ id: 'v-3', agendaItemId: 't-1', status: 'closed', result: 'passed', question: 'Begrüßung?' });
      const { context, voteReads } = await setup({ meeting: member({ votes: [other, first, loose, last] }) });
      context();
      voteReads(rest({ id: 'v-9', status: 'closed', result: 'passed', question: 'Zweite Lesung?' }));
      // The card shows the newest result; the list holds the earlier one of the item.
      const more = screen.getByRole('region', { name: 'Weitere Ergebnisse zu diesem TOP' });
      expect(within(more).getByRole('heading', { name: 'Erste Lesung?' })).toBeInTheDocument();
      expect(within(more).getByText('Abgelehnt')).toBeInTheDocument();
      expect(within(more).queryByText('Zweite Lesung?')).toBeNull();
      expect(within(more).queryByText('Begrüßung?')).toBeNull();
      const looseBox = screen.getByRole('region', { name: 'Abstimmungen ohne TOP' });
      expect(within(looseBox).getByRole('heading', { name: 'Antrag zur Geschäftsordnung?' })).toBeInTheDocument();
    });

    it('lists the attendance of all members in the attendance sheet', async () => {
      const { context } = await setup({ attendance: [{ ...ME, status: 'present', source: 'self' }, ...OTHERS] });
      context();
      await userEvent.click(screen.getByRole('button', { name: 'Deine Anwesenheit: Anwesend' }));
      const sheet = screen.getByRole('dialog', { name: 'Deine Anwesenheit' });
      const roster = within(sheet).getByRole('region', { name: 'Anwesenheit · 2 von 3 anwesend' });
      const rows = within(roster).getAllByRole('listitem');
      expect(rows[1]).toHaveTextContent('Mara Keller');
      expect(rows[1]).toHaveTextContent('Protokollführung');
      // A member sees an absence as "Abwesend" (Z2), never a reason.
      expect(rows[2]).toHaveTextContent('Abwesend');
    });

    it('opens the attendance from the dock', async () => {
      const { context, attendanceChange } = await setup({ attendance: [{ ...ME, status: 'present', source: 'self' }] });
      context();
      await userEvent.click(screen.getByRole('button', { name: 'Deine Anwesenheit: Anwesend' }));
      const sheet = screen.getByRole('dialog', { name: 'Deine Anwesenheit' });
      await userEvent.click(within(sheet).getByRole('radio', { name: 'Abwesend' }));
      expect(attendanceChange).toHaveBeenCalledWith({ member: expect.objectContaining({ principalId: 'pr-1' }), status: 'excused' });
    });

    it('names the own attendance in the dock', async () => {
      const { context, fixture } = await setup({ attendance: [{ ...ME, status: 'absent', source: 'lead' }] });
      context();
      expect(screen.getByRole('button', { name: 'Deine Anwesenheit: Abwesend' })).toBeInTheDocument();
      fixture.componentRef.setInput('attendance', [ME]);
      fixture.detectChanges();
      expect(screen.getByRole('button', { name: 'Deine Anwesenheit: Offen' })).toBeInTheDocument();
      // An external substitute has no row: no chip.
      fixture.componentRef.setInput('attendance', []);
      fixture.detectChanges();
      expect(screen.queryByRole('button', { name: /Deine Anwesenheit/ })).toBeNull();
    });

    it('says that the meeting runs while the room has no item yet', async () => {
      const { context } = await setup({ meeting: member({ currentAgendaItemId: null }) });
      context();
      expect(screen.getByRole('heading', { level: 2, name: 'Die Sitzung läuft · noch kein TOP aufgerufen' })).toBeInTheDocument();
      expect(screen.getByText(/Bis dahin kannst du die Tagesordnung lesen\.$/)).toBeInTheDocument();
      // Not the start of a planned meeting.
      expect(screen.queryByText(/Die Sitzung beginnt/)).toBeNull();
      expect(screen.queryByText('Kalender abonnieren')).toBeNull();
      expect(screen.queryByText(/von 3 ·/)).toBeNull();
      // The wide layout shows the agenda beside it, so no extra button.
      expect(screen.queryByRole('button', { name: 'Tagesordnung öffnen' })).toBeNull();
    });

    it('says that the agenda is empty while the room has no item and no agenda', async () => {
      const { context } = await setup({ meeting: member({ currentAgendaItemId: null }), agenda: [] });
      context();
      expect(screen.getByRole('heading', { level: 2, name: 'Die Sitzung läuft · noch kein TOP aufgerufen' })).toBeInTheDocument();
      expect(screen.getByText(/Die Tagesordnung hat noch keinen TOP\.$/)).toBeInTheDocument();
      expect(screen.queryByText('Kalender abonnieren')).toBeNull();
    });
  });

  describe('closed meeting', () => {
    it('opens on the last item of the room and closes the dock', async () => {
      const { context } = await setup({
        meeting: member({ status: 'closed', closedAt: '2026-10-15T19:12:00Z', currentAgendaItemId: 't-3' }),
      });
      context();
      expect(screen.getByRole('heading', { level: 1, name: 'Antrag Kulturfestival' })).toBeInTheDocument();
      expect(screen.queryByText('Jetzt')).toBeNull();
      expect(screen.getByText(/^StuPa · Do\., 15\.10\.2026 · \d\d:04–\d\d:12$/)).toBeInTheDocument();
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText(/^Geschlossen um \d\d:12$/)).toBeInTheDocument();
      expect(within(dock).getByText('3 TOPs')).toBeInTheDocument();
    });

    it('opens on the first item without an item of the room, and names one item', async () => {
      const { context } = await setup({
        meeting: member({ status: 'closed', closedAt: null, startedAt: null, currentAgendaItemId: null }),
        agenda: [item()],
      });
      context();
      expect(screen.getByRole('heading', { level: 1, name: 'Begrüßung' })).toBeInTheDocument();
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText('Geschlossen')).toBeInTheDocument();
      expect(within(dock).getByText('1 TOP')).toBeInTheDocument();
    });

    it('says that a closed meeting had no items when its agenda is empty', async () => {
      const { context } = await setup({ meeting: member({ status: 'closed' }), agenda: [] });
      context();
      expect(screen.getByText('0 TOPs')).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 2, name: 'Diese Sitzung hatte keine TOPs.' })).toBeInTheDocument();
      expect(screen.queryByText(/Die Sitzung beginnt/)).toBeNull();
      expect(screen.queryByText('Kalender abonnieren')).toBeNull();
    });
  });

  describe('narrow screen (board Schmal-Teilnahme)', () => {
    it('puts the vote above the sheet and opens the agenda as a sheet', async () => {
      const open = vote({ id: 'v-1', agendaItemId: 't-2' });
      const { context, voteReads } = await setup({ meeting: member({ votes: [open] }), media: [MEDIA.narrow, MEDIA.notPhone, MEDIA.belowWide] });
      context();
      voteReads(rest());
      expect(screen.queryByRole('region', { name: 'Tagesordnung' })).toBeNull();
      expect(screen.getByText('Abstimmung offen · TOP 2')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: /Tagesordnung/ }));
      const sheet = screen.getByRole('dialog', { name: 'Tagesordnung' });
      await userEvent.click(within(sheet).getByRole('button', { name: /Antrag Kulturfestival/ }));
      expect(screen.getByRole('heading', { level: 1, name: 'Antrag Kulturfestival' })).toBeInTheDocument();
    });

    it('keeps the vote strip out of the scroll area and puts the delegation into the dock', async () => {
      const open = vote({ id: 'v-1', agendaItemId: 't-2', voted: 14, present: 19 });
      const { context, voteReads, container } = await setup({
        meeting: member({ votes: [open] }),
        media: [MEDIA.narrow, MEDIA.notPhone, MEDIA.belowWide],
      });
      context({ allowVoteDelegation: true, incoming: [INCOMING] });
      voteReads(rest(), { blocked: false, delegatedToName: null, exercising: true, delegatedByName: 'Jonas Weber' });
      const strip = container.querySelector<HTMLElement>('app-participant-vote.fv__strip');
      expect(strip).not.toBeNull();
      expect(strip!.closest('.fv__body')).toBeNull();
      expect(within(strip!).getByText('Abstimmung offen · TOP 2')).toBeInTheDocument();
      expect(within(strip!).getByLabelText('14 von 19 Anwesenden haben abgestimmt')).toHaveTextContent('14 von 19');
      // The two rows stand side by side.
      expect(strip!.querySelector('app-ballot')).toHaveClass('ballot--columns');
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText('Du vertrittst Jonas Weber in dieser Sitzung.')).toBeInTheDocument();
      // The strip carries the ballots and the sheet the item: the dock repeats neither.
      expect(within(dock).queryByText(/Deine Stimme/)).toBeNull();
      expect(within(dock).queryByText(/von 3 · Bericht des Finanzreferats/)).toBeNull();
      expect(screen.queryByRole('region', { name: 'Vertretung' })).toBeNull();
    });

    it('names the item in the dock of a narrow screen without a delegation', async () => {
      const { context } = await setup({ media: [MEDIA.narrow, MEDIA.notPhone, MEDIA.belowWide] });
      context();
      const dock = screen.getByRole('contentinfo', { name: 'Stand der Sitzung' });
      expect(within(dock).getByText(/von 3 · Bericht des Finanzreferats/)).toBeInTheDocument();
    });
  });

  describe('phone (board Teilnahme-Telefon)', () => {
    const PHONE = [MEDIA.phone, MEDIA.belowWide];
    const long = 'Lea Hoffmann stellt den **Antrag** vor. Die Party findet am 16.10. in der Mensa statt; erwartet werden rund 350 Erstsemester. Es gibt Rückfragen zum Pfand, zur Awareness und zum Posten für DJ und Technik.';

    it('shows the item, the vote, an excerpt of the minutes and the own boxes', async () => {
      const open = vote({ id: 'v-1', agendaItemId: 't-2' });
      const { context, voteReads } = await setup({
        meeting: member({ votes: [open] }),
        agenda: [item(), item({ id: 't-2', title: 'Zuschuss', position: 1, body: long })],
        media: PHONE,
      });
      context({ allowVoteDelegation: true, canDelegate: false, incoming: [] });
      voteReads(rest());
      expect(screen.getByText(/^seit \d\d:04$/)).toBeInTheDocument();
      expect(screen.getByText(/TOP 2 von 2/)).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 2, name: 'Zuschuss' })).toBeInTheDocument();
      expect(screen.getByText('Abstimmung offen')).toBeInTheDocument();
      expect(screen.getByText('Protokoll · Mara Keller schreibt mit')).toBeInTheDocument();
      const excerpt = screen.getByText(/^Lea Hoffmann stellt den Antrag vor\./);
      expect(excerpt.textContent?.endsWith('…')).toBe(true);
      expect(screen.getByRole('region', { name: 'Deine Anwesenheit' })).toBeInTheDocument();
      // No dock on a phone: the app bar is at the bottom.
      expect(screen.queryByRole('contentinfo')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Ganzen TOP lesen' }));
      expect(screen.queryByText(/^Lea Hoffmann stellt den Antrag vor\./)).toBeNull();
      expect(document.querySelector('app-top-sheet')).not.toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Weniger anzeigen' }));
      expect(screen.getByText(/^Lea Hoffmann stellt den Antrag vor\./)).toBeInTheDocument();
    });

    it('says when an item has no text yet and offers no full view of a short text', async () => {
      const { context } = await setup({
        meeting: member({ status: 'closed', currentAgendaItemId: 't-1' }),
        agenda: [item({ body: '' }), item({ id: 't-2', title: 'Kurz', position: 1, body: 'Kurz.' })],
        media: PHONE,
      });
      context();
      expect(screen.getByText('Noch kein Text zu diesem TOP.')).toBeInTheDocument();
      expect(screen.getByText('Protokoll')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Ganzen TOP lesen' })).toBeNull();
      // The agenda opens from the header as a bottom sheet.
      await userEvent.click(screen.getByRole('button', { name: 'Tagesordnung öffnen' }));
      await userEvent.click(within(screen.getByRole('dialog', { name: 'Tagesordnung' })).getByRole('button', { name: /Kurz/ }));
      expect(screen.getByText('Kurz.')).toBeInTheDocument();
    });

    it('offers the way back to the item of the room', async () => {
      const { context } = await setup({ media: PHONE });
      context();
      await userEvent.click(screen.getByRole('button', { name: 'Tagesordnung öffnen' }));
      await userEvent.click(within(screen.getByRole('dialog', { name: 'Tagesordnung' })).getByRole('button', { name: /Begrüßung/ }));
      expect(screen.queryByText('Jetzt')).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Zurück zu Jetzt' }));
      expect(screen.getByText('Jetzt')).toBeInTheDocument();
    });

    it('says that the meeting runs while the room has no item yet, and opens the agenda', async () => {
      const { context } = await setup({ meeting: member({ currentAgendaItemId: null }), media: PHONE });
      context();
      expect(screen.getByRole('heading', { level: 2, name: 'Die Sitzung läuft · noch kein TOP aufgerufen' })).toBeInTheDocument();
      expect(screen.queryByText('Kalender abonnieren')).toBeNull();
      expect(screen.queryByText(/TOP \d von/)).toBeNull();
      const open = screen.getAllByRole('button', { name: 'Tagesordnung öffnen' });
      // The icon button of the header and the button below the line.
      expect(open).toHaveLength(2);
      await userEvent.click(open[1]);
      expect(screen.getByRole('dialog', { name: 'Tagesordnung' })).toBeInTheDocument();
    });

    it('shows the start of a planned meeting', async () => {
      const { context } = await setup({
        meeting: member({ status: 'planned', startedAt: null, currentAgendaItemId: null }),
        media: PHONE,
      });
      context();
      expect(screen.getByText('StuPa · Do., 15.10.2026 · 18:00')).toBeInTheDocument();
      expect(screen.getByText('Kalender abonnieren')).toBeInTheDocument();
    });
  });

  it('turns Markdown into one plain line', () => {
    expect(plainText('# Titel\n\n- **fett** und _kursiv_\n> Zitat [Link](https://x.y)\n:::antrag{#a}\n:::\n1. `code`')).toBe(
      'Titel fett und kursiv Zitat Link code',
    );
  });
});
