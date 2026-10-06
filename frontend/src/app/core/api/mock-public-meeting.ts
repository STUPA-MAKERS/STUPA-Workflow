/**
 * Mock data of the public meeting with QR code (#17), dev and screenshots only. The
 * mock interceptor loads it on first use.
 *
 * Lead side (live meeting `d…0001`): three join requests, seven admitted guests, the
 * join link with a real QR matrix (segno, the server library). Guest side (`/j/:code`):
 * the code picks the state, so every state of the join page has a fixed URL:
 *
 * - `7KQ4MP`: admitted, guests vote, a vote with guests runs on TOP 3.
 * - `MOCKNOVOTE`: admitted, guests vote, no open vote (TOP 4).
 * - `MOCKSECRET`: admitted during a secret vote with guests.
 * - `MOCKMEMBERS`: admitted, a vote for members only runs.
 * - `MOCKWATCH`: admitted, guests only watch, a members-only vote runs.
 * - `MOCKJOIN`: no request of this device yet (the form).
 * - `MOCKWAIT`: pending. `MOCKREJECT`: rejected, 150 s until a new request.
 * - `MOCKOFF`: no longer public. `MOCKCLOSED`: closed. Any other code: unknown.
 */
import type {
  GuestAgendaItem,
  GuestMe,
  GuestVote,
  JoinLink,
  MeetingGuest,
  PublicMeetingHead,
} from './models';

/** A real QR matrix of `https://workflow.reutlingen.university/j/7KQ4MP` (segno, level M). */
export const MOCK_QR_ROWS = [
  '111111101011101111100001001111111', '100000100111000011011010101000001', '101110100001110100001110101011101',
  '101110101001001101101101101011101', '101110101011101001111101101011101', '100000101001100010010010001000001',
  '111111101010101010101010101111111', '000000001011000111000111000000000', '100010111111100011010110111111001',
  '011100001001111110100101010001100', '100010111110000111001101111001010', '010011000010001001101100011000010',
  '111111110011011100111011001011001', '100010001010100011010110010000100', '100011111000111011010001111011110',
  '001011000000111001111100011100000', '110110101101011101000111101011010', '111100011001011101100011000001110',
  '100001100110000110101111001101010', '010111001111011000001110001100001', '011110111010011110010000111111001',
  '100110010001100001111000010100110', '001110101010011100101001110110110', '000101011101001111000100111010011',
  '110000110100110001011100111110000', '000000001110111110100001100010100', '111111101101011101000110101011010',
  '100000100001010101110110100010010', '101110101100011000111000111111010', '101110100010001010010101001110010',
  '101110100010101010110000101110000', '100000100100000001111110111000000', '111111101100000101000110100001001',
];

export const MOCK_JOIN_CODE = '7KQ4MP';

export function mockJoinLink(code = MOCK_JOIN_CODE): JoinLink {
  return {
    joinCode: code,
    joinUrl: `https://workflow.reutlingen.university/j/${code}`,
    qr: { size: MOCK_QR_ROWS.length, rows: [...MOCK_QR_ROWS] },
  };
}

const LEAD = 'Lea Hoffmann';
const DAY = '2026-06-12';

function guest(
  n: number,
  name: string,
  status: MeetingGuest['status'],
  requested: string,
  admitted: string | null = null,
): MeetingGuest {
  return {
    id: `gg000000-0000-0000-0000-0000000000${String(n).padStart(2, '0')}`,
    number: n,
    displayName: name,
    status,
    requestedAt: `${DAY}T${requested}:00Z`,
    decidedAt: admitted ? `${DAY}T${admitted}:00Z` : null,
    decidedByName: admitted ? LEAD : null,
    admittedAt: admitted ? `${DAY}T${admitted}:00Z` : null,
  };
}

/** The requests and guests of the live mock meeting (mutable: the lead decides). */
let GUESTS: MeetingGuest[] = [
  guest(1, 'Malte Krüger', 'admitted', '16:15', '16:16'),
  guest(2, 'Selin Aydın', 'admitted', '16:16', '16:17'),
  guest(3, 'Finn Berger', 'admitted', '16:17', '16:17'),
  guest(4, 'Hannah Vogel', 'admitted', '16:18', '16:19'),
  guest(5, 'Luca Romano', 'admitted', '16:20', '16:21'),
  guest(6, 'Mia Schäfer', 'admitted', '16:23', '16:24'),
  guest(7, 'Ben Okafor', 'admitted', '16:30', '16:31'),
  guest(8, 'Emma Nguyen', 'pending', '16:50'),
  guest(9, 'Jana Roth', 'pending', '16:51'),
  guest(10, 'Tobias Lang', 'pending', new Date(Date.now() - 20_000).toISOString().slice(11, 16)),
];
let LINK = mockJoinLink();

export function mockGuestCounts(): { pending: number; admitted: number } {
  return {
    pending: GUESTS.filter((g) => g.status === 'pending').length,
    admitted: GUESTS.filter((g) => g.status === 'admitted').length,
  };
}

/** A reply of the mock: the body, or a problem with its status. */
export type MockReply =
  | { status: number; body: unknown }
  | { status: number; problem: { code: string; detail?: string; retryAfter?: number } };

const problem = (status: number, code: string): MockReply => ({ status, problem: { code } });

/** The lead routes: `/meetings/{id}/guests…`, `/join-link`, `/join-code/rotate`. */
export function mockLeadGuests(method: string, p: string, body: unknown): MockReply | null {
  if (method === 'GET' && /\/meetings\/[^/]+\/guests$/.test(p)) {
    return { status: 200, body: GUESTS.filter((g) => g.status !== 'rejected') };
  }
  if (method === 'GET' && /\/meetings\/[^/]+\/join-link$/.test(p)) return { status: 200, body: LINK };
  if (method === 'POST' && /\/meetings\/[^/]+\/join-code\/rotate$/.test(p)) {
    LINK = mockJoinLink('9XH2TR');
    GUESTS = GUESTS.filter((g) => g.status !== 'pending');
    return { status: 200, body: LINK };
  }
  if (method === 'POST' && /\/meetings\/[^/]+\/guests\/admit-all$/.test(p)) {
    const now = new Date().toISOString();
    const admitted = GUESTS.filter((g) => g.status === 'pending').map((g) => ({
      ...g,
      status: 'admitted' as const,
      decidedAt: now,
      admittedAt: now,
      decidedByName: LEAD,
    }));
    GUESTS = GUESTS.map((g) => admitted.find((a) => a.id === g.id) ?? g);
    return { status: 200, body: admitted };
  }
  const m = /\/meetings\/[^/]+\/guests\/([^/]+)\/(admit|reject|remove|rename)$/.exec(p);
  if (method === 'POST' && m) {
    const g = GUESTS.find((x) => x.id === m[1]);
    if (!g) return problem(404, 'not_found');
    const now = new Date().toISOString();
    let next: MeetingGuest;
    if (m[2] === 'rename') {
      const name = (body as { displayName?: string } | null)?.displayName?.trim() ?? '';
      next = { ...g, displayName: name || g.displayName };
    } else if (m[2] === 'remove') {
      if (g.status !== 'admitted') return problem(409, 'guest_not_admitted');
      next = { ...g, status: 'removed', decidedAt: now, decidedByName: LEAD };
    } else {
      if (g.status !== 'pending') return problem(409, 'guest_not_pending');
      next =
        m[2] === 'admit'
          ? { ...g, status: 'admitted', decidedAt: now, admittedAt: now, decidedByName: LEAD }
          : { ...g, status: 'rejected', decidedAt: now, decidedByName: LEAD };
    }
    GUESTS = GUESTS.map((x) => (x.id === g.id ? next : x));
    return { status: 200, body: next };
  }
  return null;
}

// --- The guest side ---------------------------------------------------------------

const TITLE = '7. Sitzung der Fachschaft Informatik';
const GREMIUM = 'Fachschaft Informatik';

function head(code: string, over: Partial<PublicMeetingHead> = {}): PublicMeetingHead {
  return {
    code,
    title: TITLE,
    gremiumName: GREMIUM,
    date: '2026-10-06',
    startTime: '18:15:00',
    status: 'live',
    startedAt: '2026-10-06T16:15:00Z',
    guestsMode: 'vote',
    ...over,
  };
}

const AGENDA: GuestAgendaItem[] = [
  { id: 'pa-1', position: 1, title: 'Begrüßung und Beschlussfähigkeit', kind: 'freetext', nonPublic: false, body: 'Die Sitzungsleitung eröffnet die Sitzung um 18:15. 19 von 23 Mitgliedern sind anwesend.' },
  { id: 'pa-2', position: 2, title: 'Protokoll der 6. Sitzung', kind: 'freetext', nonPublic: false, body: 'Das Protokoll der 6. Sitzung wird ohne Änderungen genehmigt.' },
  {
    id: 'pa-3',
    position: 3,
    title: 'Zuschuss Erstsemesterfahrt Informatik',
    kind: 'application',
    nonPublic: false,
    body: 'Malte Krüger (Erstsemester-Tutorium, Gast) stellt den Antrag vor: Fahrt nach Bad Urach vom 30.10. bis 01.11., 48 Teilnehmende, beantragt werden 1.440 €.\n\n**Rückfragen**\n\n- Eigenanteil: 35 € pro Person, Ermäßigung über den Sozialfonds möglich.\n- Die Unterkunft ist barrierefrei; zwei Plätze sind dafür reserviert.\n\nFinn Berger (Gast) fragt nach dem Busunternehmen; es gilt das günstigste von drei Angeboten.',
  },
  { id: 'pa-4', position: 4, title: 'Lerncafé: Snacks und Getränke WS 26/27', kind: 'application', nonPublic: false, body: null },
  { id: 'pa-5', position: 5, title: 'Wahl der Kassenprüfung', kind: 'freetext', nonPublic: false, body: null },
  { id: 'pa-6', position: 6, title: 'Personalangelegenheit Tutorium', kind: 'freetext', nonPublic: true, body: null },
  { id: 'pa-7', position: 7, title: 'Verschiedenes', kind: 'freetext', nonPublic: false, body: null },
];

const Q3 = 'Soll der Antrag „Zuschuss Erstsemesterfahrt Informatik“ wie beschrieben gefördert werden?';

function vote(over: Partial<GuestVote> = {}): GuestVote {
  return {
    id: 'pv-3',
    agendaItemId: 'pa-3',
    question: Q3,
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

const MEMBERS_ONLY = vote({
  id: 'pv-2',
  guestsVote: false,
  quorum: { type: 'percent', value: 50 },
  canCast: false,
  tally: { counts: {}, voted: 11, present: 19, revealed: false, leading: null, presentMembers: 19, presentGuests: 7 },
});

interface GuestMock {
  me: GuestMe | null;
  head: PublicMeetingHead | null;
  problem?: string;
  /** The problem of the head when it differs from the one of `/me`. */
  headProblem?: string;
}

function me(code: string, over: Partial<GuestMe>, view: Partial<NonNullable<GuestMe['view']>> | null): GuestMe {
  return {
    guestId: 'gg000000-0000-0000-0000-000000000009',
    number: 9,
    displayName: 'Jana Roth',
    status: 'admitted',
    retryAfter: null,
    ...over,
    meeting: over.meeting ?? head(code),
    view:
      view === null
        ? null
        : {
            currentAgendaItemId: 'pa-3',
            presentMembers: 19,
            admittedGuests: 7,
            agenda: AGENDA,
            votes: [vote()],
            ...view,
          },
  };
}

const STATES = new Map<string, GuestMock>();

function initial(code: string): GuestMock {
  switch (code) {
    case MOCK_JOIN_CODE:
      return { head: head(code), me: me(code, { displayName: 'Malte Krüger', number: 1 }, {}) };
    case 'MOCKNOVOTE':
      return { head: head(code), me: me(code, {}, { currentAgendaItemId: 'pa-4', votes: [] }) };
    case 'MOCKSECRET':
      return {
        head: head(code),
        me: me(code, { displayName: 'Emma Nguyen', number: 8 }, {
          currentAgendaItemId: 'pa-5',
          votes: [vote({ id: 'pv-5', agendaItemId: 'pa-5', secret: true, question: 'Wer übernimmt die Kassenprüfung im WS 26/27: Sophie Wendt?', tally: { counts: {}, voted: 9, present: 26, revealed: false, leading: null, presentMembers: 19, presentGuests: 7 } })],
        }),
      };
    case 'MOCKMEMBERS':
      return { head: head(code), me: me(code, { displayName: 'Malte Krüger', number: 1 }, { currentAgendaItemId: 'pa-2', votes: [{ ...MEMBERS_ONLY, agendaItemId: 'pa-2', question: 'Wird das Protokoll der 6. Sitzung genehmigt?' }] }) };
    case 'MOCKWATCH':
      return { head: head(code, { guestsMode: 'watch' }), me: me(code, { meeting: head(code, { guestsMode: 'watch' }) }, { votes: [MEMBERS_ONLY] }) };
    case 'MOCKJOIN':
      return { head: head(code), me: null };
    case 'MOCKWAIT':
      return { head: head(code), me: me(code, { status: 'pending' }, null) };
    case 'MOCKREJECT':
      return { head: head(code), me: me(code, { status: 'rejected', displayName: 'Tobias Lang', number: 10, retryAfter: 150 }, null) };
    // The head says "unknown" for a closed meeting and one without public participation
    // (no probing); a device with a request learns the switch-off from `/me`.
    case 'MOCKOFF':
      return { head: null, me: null, problem: 'meeting_not_public', headProblem: 'join_code_unknown' };
    case 'MOCKCLOSED':
      return { head: null, me: null, problem: 'join_code_unknown' };
    default:
      return { head: null, me: null, problem: 'join_code_unknown' };
  }
}

function stateOf(code: string): GuestMock {
  let s = STATES.get(code);
  if (!s) {
    s = initial(code);
    STATES.set(code, s);
  }
  return s;
}

/** The public routes `/public/meetings/…` of a guest. */
export function mockPublicMeeting(method: string, p: string, body: unknown): MockReply | null {
  const join = /\/public\/meetings\/join\/([^/]+)$/.exec(p);
  if (method === 'POST' && join) {
    const s = stateOf(join[1]);
    if (s.problem) return problem(404, s.problem);
    const name = (body as { displayName?: string } | null)?.displayName?.trim() ?? '';
    s.me = me(join[1], { status: 'pending', displayName: name, number: 11, ...(s.head ? { meeting: s.head } : {}) }, null);
    return { status: 201, body: s.me };
  }
  const m = /\/public\/meetings\/([^/]+)(\/me|\/votes\/([^/]+)\/ballot)?$/.exec(p);
  if (!m) return null;
  const code = m[1];
  const s = stateOf(code);
  if (!m[2] && s.headProblem) return problem(404, s.headProblem);
  if (s.problem) return problem(404, s.problem);
  if (!m[2]) return method === 'GET' ? { status: 200, body: s.head } : null;
  if (m[2] === '/me') {
    if (!s.me) return problem(401, 'guest_token_missing');
    if (method === 'GET') return { status: 200, body: s.me };
    if (method === 'PATCH') {
      const name = (body as { displayName?: string } | null)?.displayName?.trim() ?? '';
      s.me = { ...s.me, displayName: name || s.me.displayName };
      return { status: 200, body: s.me };
    }
    if (method === 'DELETE') {
      s.me = null;
      return { status: 204, body: null };
    }
    return null;
  }
  // The ballot of an admitted guest.
  if (method !== 'POST' || !s.me?.view) return problem(403, 'guest_not_admitted');
  const choice = (body as { choice?: string } | null)?.choice ?? '';
  const votes = s.me.view.votes.map((v) =>
    v.id === m[3]
      ? {
          ...v,
          canCast: false,
          myBallot: { cast: true, choice: v.secret ? null : choice },
          tally: { ...v.tally, voted: v.tally.voted + 1 },
        }
      : v,
  );
  s.me = { ...s.me, view: { ...s.me.view, votes } };
  return { status: 200, body: { status: 'cast' } };
}
