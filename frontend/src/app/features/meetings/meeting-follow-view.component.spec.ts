import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Attendance, Meeting, MeetingVote } from '@core/api/models';
import { MeetingFollowViewComponent } from './meeting-follow-view.component';

function vote(over: Partial<MeetingVote> = {}): MeetingVote {
  return {
    id: 'v-1',
    applicationId: null,
    agendaItemId: 't-1',
    title: null,
    question: 'Wird der Antrag angenommen?',
    options: ['yes', 'no', 'abstain'],
    status: 'open',
    result: null,
    counts: { yes: 2, no: 1 },
    leading: 'yes',
    closesAt: null,
    voted: 3,
    present: 4,
    revealed: true,
    failedReason: null,
    ...over,
  };
}

const MEETING: Meeting = {
  id: 'm-1',
  title: 'Sitzung',
  date: '2026-10-15',
  startTime: '18:00',
  endTime: null,
  status: 'live',
  activeApplicationId: null,
  currentAgendaItemId: 't-2',
  gremiumId: 'g-1',
  gremiumName: 'StuPa',
  votes: [vote(), vote({ id: 'v-2', agendaItemId: 't-2', revealed: false, counts: null, leading: null })],
  protocolId: 'p-1',
  createdAt: '2026-10-01T00:00:00Z',
  protokollantId: 'pr-9',
  protokollantName: 'Pia Protokoll',
  isProtokollant: false,
  canControl: false,
  canManage: false,
  canWrite: false,
  canManageVotes: false,
  canVote: true,
};

const AGENDA: AgendaItem[] = [
  { id: 't-1', applicationId: 'app-1', title: 'Antrag Kulturfestival', body: 'Die **Antragstellerin** stellt vor.', position: 0, stateLabel: { de: 'In Abstimmung', en: 'In vote' } },
  { id: 't-2', applicationId: null, title: 'Bericht', body: null, position: 1 },
];

const ATTENDANCE: Attendance[] = [
  { principalId: 'me', displayName: 'Ich', email: null, status: null, source: null, isSelf: true },
  { principalId: 'pr-2', displayName: 'Mika', email: null, status: 'present', source: 'lead', isSelf: false },
];

async function setup(over: { meeting?: Partial<Meeting>; agenda?: AgendaItem[] } = {}) {
  const castVote = jest.fn();
  const attendanceChange = jest.fn();
  const view = await render(MeetingFollowViewComponent, {
    inputs: {
      meeting: { ...MEETING, ...over.meeting },
      agenda: over.agenda ?? AGENDA,
      attendance: ATTENDANCE,
      savingAttendance: false,
      casting: null,
      choices: { 'v-1': 'yes' },
    },
    on: { castVote, attendanceChange },
    providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.match((r) => r.url.includes('/delegations/')).forEach((req) =>
    req.flush({
      meetingId: 'm-1', gremiumId: 'g-1', allowVoteDelegation: false, votingDelegationEnabled: false,
      delegationAllowExternal: false, deadline: null, deadlinePassed: false, meetingStarted: true,
      canDelegate: false, myDelegation: null, incoming: [], recipients: [],
    }),
  );
  return { ...view, castVote, attendanceChange, http };
}

describe('MeetingFollowViewComponent', () => {
  const scrollIntoView = jest.fn();

  beforeAll(() => {
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  beforeEach(() => scrollIntoView.mockClear());

  it('marks the item the room handles now and scrolls to it', async () => {
    const { container } = await setup();
    expect(screen.getAllByText('Jetzt')).toHaveLength(1);
    const now = container.querySelector('#top-t-2');
    expect(now).toHaveClass('mtg__followTop--now');
    expect(container.querySelector('#top-t-1')).not.toHaveClass('mtg__followTop--now');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it('renders the text, the state and the application link of an item', async () => {
    await setup();
    expect(screen.getByText('Antragstellerin')).toBeInTheDocument();
    expect(screen.getByText('In Abstimmung')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Antrag öffnen' })).toBeInTheDocument();
  });

  it('lets a member cast on an open vote and shows the tally or the hidden hint', async () => {
    const { castVote, container } = await setup();
    const first = container.querySelector('#top-t-1') as HTMLElement;
    await userEvent.click(within(first).getByRole('button', { name: /Ja/ }));
    expect(castVote).toHaveBeenCalledWith({ voteId: 'v-1', choice: 'yes' });
    expect(within(first).getByText('3 von 4 Anwesenden haben abgestimmt')).toBeInTheDocument();
    const second = container.querySelector('#top-t-2') as HTMLElement;
    expect(within(second).getByText(/Zwischenstand sichtbar/)).toBeInTheDocument();
  });

  it('lets a member mark the own attendance', async () => {
    const { attendanceChange } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Anwesend' }));
    expect(attendanceChange).toHaveBeenCalledWith(
      expect.objectContaining({ member: expect.objectContaining({ principalId: 'me' }), status: 'present' }),
    );
  });

  it('says when the agenda is empty and does not scroll without a current item', async () => {
    await setup({ agenda: [], meeting: { currentAgendaItemId: null } });
    expect(screen.getByText('Es sind noch keine Tagesordnungspunkte vorhanden.')).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
