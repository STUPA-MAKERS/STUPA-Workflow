/**
 * Test data of the session page specs (meeting page, agenda pane, sheet, dock, vote card).
 * A live meeting of a lead who also keeps the minutes, three agenda items and a roster of
 * three members.
 */
import type {
  AgendaItem,
  Attendance,
  Meeting,
  MeetingVote,
  Protocol,
} from '../app/core/api/models';

export function vote(over: Partial<MeetingVote> = {}): MeetingVote {
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

export function meeting(over: Partial<Meeting> = {}): Meeting {
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
    keeperPeriods: [],
    plannedHandover: null,
    publicJoin: false,
    guestsMode: 'vote',
    joinCode: null,
    admittedGuests: 0,
    pendingGuests: 0,
    ...over,
  };
}

export function item(over: Partial<AgendaItem> = {}): AgendaItem {
  return {
    id: 't-1',
    applicationId: null,
    title: 'Begrüßung',
    body: 'Eröffnet.',
    position: 0,
    ...over,
  };
}

export const AGENDA: AgendaItem[] = [
  item(),
  item({ id: 't-2', title: 'Bericht des Finanzreferats', position: 1, body: 'Zwischenstand.' }),
  item({
    id: 't-3',
    title: 'Antrag Kulturfestival',
    position: 2,
    applicationId: 'app-1',
    nonPublic: true,
    stateLabel: { de: 'Abstimmung', en: 'Vote' },
  }),
];

export function protocol(over: Partial<Protocol> = {}): Protocol {
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

export const ATTENDANCE: Attendance[] = [
  { principalId: 'pr-1', displayName: 'Pia Protokoll', email: null, status: 'present', source: 'self', note: null, isSelf: true, canKeepProtocol: true },
  { principalId: 'pr-2', displayName: 'Mika Mitglied', email: null, status: 'excused', source: 'lead', note: null, isSelf: false, canKeepProtocol: true },
  { principalId: 'pr-3', displayName: 'Alina Admin', email: null, status: null, source: null, note: null, isSelf: false, canKeepProtocol: true },
];

/** O20: a member without `protocol.write` cannot keep the minutes. */
export const WITH_VOTER: Attendance[] = [
  ...ATTENDANCE,
  { principalId: 'pr-4', displayName: 'Vera Votum', email: null, status: 'present', source: 'self', note: null, isSelf: false, canKeepProtocol: false },
];

/** The neutral delegation context of the attendance popover (the feature is off). */
export const DELEGATION_CONTEXT = {
  meetingId: 'm-1',
  gremiumId: 'g-1',
  allowVoteDelegation: false,
  votingDelegationEnabled: false,
  delegationAllowExternal: false,
  deadline: null,
  deadlinePassed: false,
  meetingStarted: true,
  canDelegate: false,
  myDelegation: null,
  incoming: [],
  recipients: [],
};

/** Let `matchMedia` match the given queries, for a spec of a width class. */
export function matchMediaQueries(...queries: string[]): () => void {
  const original = window.matchMedia;
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: queries.includes(query),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
  return () => Object.defineProperty(window, 'matchMedia', { writable: true, value: original });
}
