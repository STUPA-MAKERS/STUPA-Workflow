/** Test data of the public meeting specs (#17): a join request, a link, a guest view. */
import type { GuestMe, GuestVote, JoinLink, MeetingGuest } from '../app/core/api/models';

export function guestRow(over: Partial<MeetingGuest> = {}): MeetingGuest {
  return {
    id: 'g-1',
    number: 1,
    displayName: 'Jana Roth',
    status: 'pending',
    requestedAt: '2026-10-06T16:50:00Z',
    decidedAt: null,
    decidedByName: null,
    admittedAt: null,
    ...over,
  };
}

export const LINK: JoinLink = {
  joinCode: '7KQ4MP',
  joinUrl: 'https://x.example/j/7KQ4MP',
  qr: { size: 2, rows: ['10', '01'] },
};

export function guestVote(over: Partial<GuestVote> = {}): GuestVote {
  return {
    id: 'v-1',
    agendaItemId: 'a-3',
    question: 'Wird gefördert?',
    options: ['yes', 'no', 'abstain'],
    status: 'open',
    secret: false,
    majorityRule: 'simple',
    guestsVote: true,
    quorum: null,
    openedAt: '2026-10-06T16:48:00Z',
    closedAt: null,
    result: null,
    failedReason: null,
    tally: { counts: {}, voted: 14, present: 26, revealed: false, leading: null, presentMembers: 19, presentGuests: 7 },
    myBallot: { cast: false, choice: null },
    canCast: true,
    ...over,
  };
}

export function guestMe(over: Partial<GuestMe> = {}): GuestMe {
  return {
    guestId: 'g-1',
    number: 1,
    displayName: 'Jana Roth',
    status: 'admitted',
    retryAfter: null,
    meeting: {
      code: '7KQ4MP',
      title: '7. Sitzung',
      gremiumName: 'Fachschaft Informatik',
      date: '2026-10-06',
      startTime: '18:15:00',
      status: 'live',
      startedAt: '2026-10-06T16:15:00Z',
      guestsMode: 'vote',
    },
    view: {
      currentAgendaItemId: 'a-3',
      presentMembers: 19,
      admittedGuests: 7,
      agenda: [
        { id: 'a-1', position: 1, title: 'Begrüßung', kind: 'freetext', nonPublic: false, body: 'Eröffnet.' },
        { id: 'a-2', position: 2, title: 'Personal', kind: 'freetext', nonPublic: true, body: null },
        { id: 'a-3', position: 3, title: 'Zuschuss', kind: 'application', nonPublic: false, body: '**Vorstellung**' },
        { id: 'a-4', position: 4, title: null, kind: 'freetext', nonPublic: false, body: null },
      ],
      votes: [guestVote()],
    },
    ...over,
  };
}
