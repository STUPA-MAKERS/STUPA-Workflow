import type { Delegation, DelegationRecipient, MeetingDelegationContext } from './delegations.service';
import type { MeetingOutWire } from './models';

/**
 * The participant view of the mock backend (`?mock=1`). Dev and tests only.
 *
 * The demo user is a plain member (no write, no manage right) in two meetings:
 *
 * - `…0003`: the live demo meeting as a member sees it. Max Mustermann keeps the minutes,
 *   and the demo user represents Erika Beispiel with her voting right.
 * - `…0105`: a planned meeting of the Haushaltsausschuss (a row of the mock timeline), with
 *   its agenda and the delegation setup.
 *
 * The delegation context (`GET /delegations/meetings/{id}/context`) and the recipients
 * of every mock meeting come from here as well. The interceptor routes the paths here
 * (`MEMBER_MOCK_PATH`) and passes its mutable state in.
 */

export const MEMBER_LIVE_ID = 'd0000000-0000-0000-0000-000000000003';
export const MEMBER_PLANNED_ID = 'd0000000-0000-0000-0000-000000000105';

const DEMO_SUB = '00000000-0000-0000-0000-000000000001';
const LIVE_MEETING_ID = 'd0000000-0000-0000-0000-000000000001';

/** A local `YYYY-MM-DD` date, `days` away from today. */
function day(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A local ISO time `days` from today at `hh:mm`. */
function at(days: number, hh: number, mm: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(hh, mm, 0, 0);
  return d.toISOString();
}

/** The rights of a plain member who may vote. */
const MEMBER_RIGHTS = {
  isProtokollant: false,
  canControl: false,
  canManage: false,
  canWrite: false,
  canManageVotes: false,
  canFinalize: false,
  canVote: true,
} as const;

function plannedMeeting(): MeetingOutWire {
  return {
    id: MEMBER_PLANNED_ID,
    title: '12. Sitzung des Haushaltsausschusses',
    date: day(3),
    startTime: '17:30:00',
    endTime: '19:00:00',
    status: 'planned',
    activeApplicationId: null,
    currentAgendaItemId: null,
    gremiumId: 'g0000000-0000-0000-0000-000000000002',
    gremiumName: 'Haushaltsausschuss',
    votes: [],
    protocolId: null,
    protokollantId: 'p-2',
    protokollantName: 'Max Mustermann',
    createdAt: `${day(-5)}T08:00:00Z`,
    keeperPeriods: [],
    plannedHandover: null,
    ...MEMBER_RIGHTS,
  };
}

const PLANNED_AGENDA = [
  { id: 'ag-m1', applicationId: null, title: 'Begrüßung und Beschlussfähigkeit', body: '', position: 0 },
  { id: 'ag-m2', applicationId: null, title: 'Protokoll der 11. Sitzung', body: '', position: 1 },
  {
    id: 'ag-m3',
    applicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    title: 'Förderung Ersti-Wochenende',
    body: '',
    position: 2,
    stateLabel: { de: 'Abstimmung', en: 'Vote' },
  },
  { id: 'ag-m4', applicationId: null, title: 'Haushaltsplan 2027', body: '', position: 3 },
  { id: 'ag-m5', applicationId: null, title: 'Verschiedenes', body: '', position: 4 },
];

/** The live demo meeting as a plain member sees it. */
function liveMeeting(live: MeetingOutWire): MeetingOutWire {
  return {
    ...live,
    id: MEMBER_LIVE_ID,
    protokollantId: 'p-2',
    protokollantName: 'Max Mustermann',
    keeperPeriods: [],
    plannedHandover: null,
    ...MEMBER_RIGHTS,
  };
}

/** The members of the mock gremium (without the demo user) and the substitutes. */
const MEMBERS: DelegationRecipient[] = [
  { principalId: 'p-2', displayName: 'Max Mustermann', viaPool: false, isMember: true },
  { principalId: 'p-3', displayName: 'Erika Beispiel', viaPool: false, isMember: true },
  { principalId: 'p-4', displayName: 'Uli Übernahme', viaPool: false, isMember: true },
  { principalId: 'p-5', displayName: 'Rolf Redner', viaPool: false, isMember: true },
  { principalId: 'p-8', displayName: 'Fritz Fehlend', viaPool: false, isMember: true },
];
const SUBSTITUTES: DelegationRecipient[] = [
  { principalId: 'p-7', displayName: 'Sven Stellvertreter', viaPool: true, isMember: false },
  { principalId: 'p-10', displayName: 'Emma Vogel', viaPool: true, isMember: false },
];

/** The delegation context of a meeting for the demo user. */
function context(
  meetingId: string,
  live: MeetingOutWire,
  delegations: readonly Delegation[],
): MeetingDelegationContext {
  const planned = meetingId === MEMBER_PLANNED_ID;
  const started = !planned && meetingId !== 'd0000000-0000-0000-0000-000000000002';
  const mine = delegations.filter((d) => d.meetingId === meetingId);
  const incoming = mine.filter((d) => d.delegateId === 'me' || d.delegateId === DEMO_SUB);
  // In the live meeting the demo user represents Erika Beispiel (see the vote status).
  if (meetingId === LIVE_MEETING_ID || meetingId === MEMBER_LIVE_ID) {
    incoming.push({
      id: 'f0000000-0000-0000-0000-000000000010',
      meetingId,
      meetingTitle: live.title,
      meetingDate: live.date ?? null,
      gremiumId: 'g0000000-0000-0000-0000-000000000001',
      gremiumName: 'Studierendenparlament',
      delegatorId: 'p-3',
      delegatorName: 'Erika Beispiel',
      delegateId: DEMO_SUB,
      delegateName: 'Demo Mitglied',
      delegateVoting: true,
      viaPool: false,
      createdAt: at(-2, 9, 0),
      revocable: false,
      direction: 'incoming',
    });
  }
  return {
    meetingId,
    gremiumId: planned ? 'g0000000-0000-0000-0000-000000000002' : 'g0000000-0000-0000-0000-000000000001',
    allowVoteDelegation: true,
    votingDelegationEnabled: true,
    delegationAllowExternal: false,
    // The gremium wants 60 minutes of lead time before the start (17:30).
    deadline: planned ? at(3, 16, 30) : null,
    deadlinePassed: false,
    meetingStarted: started,
    canDelegate: true,
    myDelegation: mine.find((d) => d.delegatorId === DEMO_SUB) ?? null,
    incoming,
    recipients: [...SUBSTITUTES, ...MEMBERS],
  };
}

/** GET of a path of `MEMBER_MOCK_PATH` (in the interceptor, so this module stays lazy). */
export function memberMeetingGet(
  path: string,
  query: string,
  live: MeetingOutWire,
  delegations: readonly Delegation[],
): unknown {
  const ctx = /\/delegations\/meetings\/([^/]+)\/(context|recipients)$/.exec(path);
  if (ctx) {
    const c = context(ctx[1], live, delegations);
    if (ctx[2] === 'context') return c;
    const needle = query.trim().toLowerCase();
    return c.recipients.filter((r) => (r.displayName ?? '').toLowerCase().includes(needle));
  }
  if (path.endsWith('/agenda')) return [...PLANNED_AGENDA];
  return path.endsWith(MEMBER_PLANNED_ID) ? plannedMeeting() : liveMeeting(live);
}

/** POST /delegations: the demo user hands a meeting over (participant view). */
export function memberDelegationCreate(
  body: unknown,
  seq: number,
  roster: readonly { principalId: string; displayName: string | null }[],
): Delegation {
  const { meetingId = '', delegateId = '', delegateVoting = false } = (body ?? {}) as Partial<{
    meetingId: string;
    delegateId: string;
    delegateVoting: boolean;
  }>;
  const substitute = SUBSTITUTES.find((r) => r.principalId === delegateId);
  return {
    id: `f0000000-0000-0000-0000-0000000002${String(seq).padStart(2, '0')}`,
    meetingId,
    meetingTitle: null,
    meetingDate: null,
    gremiumId: 'g0000000-0000-0000-0000-000000000002',
    gremiumName: null,
    delegatorId: DEMO_SUB,
    delegatorName: 'Demo Mitglied',
    delegateId,
    delegateName:
      substitute?.displayName ?? roster.find((a) => a.principalId === delegateId)?.displayName ?? null,
    delegateVoting,
    viaPool: !!substitute,
    createdAt: new Date().toISOString(),
    revocable: true,
    direction: 'outgoing',
  };
}
