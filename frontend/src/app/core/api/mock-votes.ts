/**
 * Dev data of the vote list (`GET /votes`, page "Abstimmungen"). Mock mode only; the
 * interceptor loads this file on first use, so it stays out of the initial bundle.
 *
 * The list holds the open vote of the live demo meeting (`vote-demo`), the closed vote of
 * the closed demo meeting (`a0000000-…0101`) and the standalone votes below, whose ids
 * start with `b0000000-` and whose detail (`GET /votes/{id}`) this file also serves.
 */
import type { MyBallot, Page, Vote, VoteListItem, VoteStatus } from './models';

const STUPA = { id: 'g0000000-0000-0000-0000-000000000001', name: 'Studierendenparlament' };
const HHA = { id: 'g0000000-0000-0000-0000-000000000002', name: 'Haushaltsausschuss' };

const OPTIONS = ['yes', 'no', 'abstain'];

/** The ids of the standalone demo votes. */
export const DEMO_VOTE_PATH = /\/votes\/b0000000-[^/]+$/;

const at = (days: number, hour = 18): string => {
  const d = new Date(Date.now() + days * 86_400_000);
  d.setUTCHours(hour, 0, 0, 0);
  return d.toISOString();
};

function vote(over: Partial<Vote> & Pick<Vote, 'id' | 'status'>): Vote {
  return {
    applicationId: 'a1000000-0000-0000-0000-000000000001',
    meetingId: null,
    agendaItemId: null,
    question: null,
    eligibleGroup: STUPA.id,
    config: { options: OPTIONS, majorityRule: 'simple', quorum: null, secret: false },
    opensAt: null,
    closesAt: null,
    result: null,
    secret: false,
    majorityRule: 'simple',
    quorum: null,
    openedAt: null,
    closedAt: null,
    tally: { counts: {}, eligible: 9, voted: 0, present: 0, revealed: true, quorumMet: false, leading: null },
    myBallot: { cast: false, choice: null },
    representedCast: false,
    canManage: true,
    canCast: true,
    ...over,
  };
}

/** The standalone demo votes with their whole detail. */
const DETAILS: Record<string, Vote> = {
  'b0000000-0000-0000-0000-000000000001': vote({
    id: 'b0000000-0000-0000-0000-000000000001',
    status: 'open',
    question: 'Soll der Zuschuss für die Exkursion der Fachschaft Technik bewilligt werden?',
    eligibleGroup: HHA.id,
    opensAt: at(-1, 9),
    openedAt: at(-1, 9),
    closesAt: at(2, 22),
    tally: { counts: { yes: 3, no: 1, abstain: 0 }, eligible: 7, voted: 4, present: 0, revealed: true, quorumMet: false, leading: 'yes' },
    canManage: false,
  }),
  'b0000000-0000-0000-0000-000000000002': vote({
    id: 'b0000000-0000-0000-0000-000000000002',
    status: 'draft',
    question: 'Soll die Anschaffung eines Lastenrads für den AStA gefördert werden?',
    tally: { counts: {}, eligible: 9, voted: 0, present: 0, revealed: true, quorumMet: false, leading: null },
  }),
  'b0000000-0000-0000-0000-000000000003': vote({
    id: 'b0000000-0000-0000-0000-000000000003',
    status: 'closed',
    result: 'rejected',
    question: 'Soll die Rücklage für Veranstaltungstechnik aufgestockt werden?',
    eligibleGroup: HHA.id,
    secret: true,
    config: { options: OPTIONS, majorityRule: 'absolute', quorum: { type: 'count', value: 5 }, secret: true },
    majorityRule: 'absolute',
    quorum: { type: 'count', value: 5 },
    opensAt: at(-12, 9),
    openedAt: at(-12, 9),
    closedAt: at(-10, 12),
    tally: { counts: { yes: 2, no: 1, abstain: 1 }, eligible: 7, voted: 4, present: 0, revealed: true, quorumMet: false, leading: 'yes', result: 'rejected', failedReason: 'quorum' },
    myBallot: { cast: true, choice: null },
    canManage: false,
  }),
  'b0000000-0000-0000-0000-000000000004': vote({
    id: 'b0000000-0000-0000-0000-000000000004',
    status: 'cancelled',
    question: 'Soll der Druckkostenzuschuss für die Campuszeitung erhöht werden?',
    opensAt: at(-30, 9),
    openedAt: at(-30, 9),
    closedAt: at(-29, 10),
    tally: { counts: {}, eligible: 9, voted: 2, present: 0, revealed: true, quorumMet: false, leading: null },
  }),
};

/** The detail of a standalone demo vote, with the own ballot of this mock session. */
export function demoVote(id: string, own: MyBallot | null): Vote | undefined {
  const found = DETAILS[id];
  if (!found) return undefined;
  if (!own?.cast) return found;
  const extra = found.myBallot?.cast ? 0 : 1;
  // A secret vote never ties the choice to the voter.
  const myBallot = found.secret ? { cast: true, choice: null } : own;
  return { ...found, myBallot, tally: { ...found.tally, voted: Number(found.tally.voted) + extra } };
}

/**
 * One row of the list. Every demo vote carries a question and an own ballot;
 * `meeting` names the meeting and the item of a meeting vote. `createdAt` is the sort
 * time: the end of an ended vote, else its start.
 */
function row(
  v: Vote,
  gremium: { id: string; name: string },
  meeting: { title: string; position: number } | null = null,
): VoteListItem {
  const openedAt = v.openedAt ?? null;
  const closedAt = v.closedAt ?? null;
  return {
    id: v.id,
    question: String(v.question),
    status: v.status,
    result: v.result,
    secret: v.secret,
    applicationId: v.applicationId,
    meetingId: meeting ? (v.meetingId as string) : null,
    meetingTitle: meeting ? meeting.title : null,
    agendaItemId: meeting ? (v.agendaItemId as string) : null,
    agendaPosition: meeting ? meeting.position : null,
    gremiumId: gremium.id,
    gremiumName: gremium.name,
    // A draft never opened: it was made two days ago.
    createdAt: closedAt ?? openedAt ?? at(-2),
    openedAt,
    closedAt,
    closesAt: v.closesAt,
    canCast: v.canCast === true,
    myBallot: v.myBallot as MyBallot,
  };
}

const RANK: Record<VoteStatus, number> = { open: 0, draft: 1, closed: 2, cancelled: 2 };

/**
 * `GET /votes`: the demo list with the filters of the server (`status`, `gremiumId`,
 * `q`, `limit`, `offset`), the open votes first, then the newest.
 *
 * `live` is the open vote of the live demo meeting and `closed` the closed vote of the
 * closed demo meeting, both as the interceptor serves them. `own` gives the ballot of
 * this mock session per vote id.
 */
export function mockVoteList(
  params: URLSearchParams,
  live: Vote,
  closed: Vote,
  own: (id: string) => MyBallot | null,
): Page<VoteListItem> {
  const all: VoteListItem[] = [
    row(live, STUPA, { title: 'STUPA-Sitzung 12.06.', position: 3 }),
    row(DETAILS['b0000000-0000-0000-0000-000000000001'], HHA),
    row(DETAILS['b0000000-0000-0000-0000-000000000002'], STUPA),
    row(closed, STUPA, { title: '33. Sitzung des Studierendenparlaments', position: 3 }),
    row(DETAILS['b0000000-0000-0000-0000-000000000003'], HHA),
    row(DETAILS['b0000000-0000-0000-0000-000000000004'], STUPA),
  ].map((r) => {
    const mine = own(r.id);
    return mine?.cast ? { ...r, myBallot: r.secret ? { cast: true, choice: null } : mine } : r;
  });
  const statuses = params.getAll('status');
  const wanted = new Set(statuses.length ? statuses : ['open', 'closed', 'cancelled']);
  const gremium = params.get('gremiumId');
  const q = (params.get('q') ?? '').trim().toLowerCase();
  const hits = all
    .filter((r) => wanted.has(r.status))
    .filter((r) => !gremium || r.gremiumId === gremium)
    .filter(
      (r) =>
        !q ||
        `${r.question} ${r.meetingTitle}`.toLowerCase().includes(q),
    )
    .sort((a, b) => RANK[a.status] - RANK[b.status] || b.createdAt.localeCompare(a.createdAt));
  const limit = Number(params.get('limit') ?? 50);
  const offset = Number(params.get('offset') ?? 0);
  return { items: hits.slice(offset, offset + limit), total: hits.length, limit, offset };
}
