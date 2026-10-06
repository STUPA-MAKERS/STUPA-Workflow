import type { MeetingOutWire, ProtocolOutWire } from './models';

/**
 * Two closed demo meetings for the mock backend (`?mock=1`). Dev and tests only.
 *
 * `…0101` has a draft protocol: the protocol bar offers "Finalisieren & versenden", the
 * text of TOP 3 holds the result of its vote, and two people kept the minutes; the demo
 * user kept them last, so the text stays editable while the protocol is a draft (O22).
 * `…0102` has a final protocol with an internal and a public PDF. The ids are the ids of
 * the first two past rows of the mock timeline, so a click in the list opens them. The
 * interceptor routes the paths of these ids here (`closedMockId`).
 */

export const CLOSED_DRAFT_ID = 'd0000000-0000-0000-0000-000000000101';
export const CLOSED_FINAL_ID = 'd0000000-0000-0000-0000-000000000102';

const DEMO_SUB = '00000000-0000-0000-0000-000000000001';

/** A local ISO time `days` from today at `hh:mm`. */
function at(days: number, hh: number, mm: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  d.setHours(hh, mm, 0, 0);
  return d.toISOString();
}

function day(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

interface ClosedMeeting {
  meeting: MeetingOutWire;
  agenda: {
    id: string;
    applicationId: string | null;
    title: string | null;
    body: string;
    position: number;
    nonPublic?: boolean;
  }[];
  protocol: ProtocolOutWire;
}

const QUESTION = 'Soll der Antrag „Beispielantrag Sommerfest“ wie beschrieben gefördert werden?';

function closedMeeting(
  id: string,
  days: number,
  title: string,
  final: boolean,
  gremium: { id: string; name: string },
): ClosedMeeting {
  const prefix = id.slice(-2);
  const top = (n: number) => `ag-c${prefix}-${n}`;
  const voteBody =
    'Die Antragstellerin stellt den Antrag vor. Rolf Redner regt an, einen Posten zu kürzen; die Antragstellerin hält am Antrag fest.\n\n' +
    'Die Sitzungsleitung stellt die Beschlussfrage zur Abstimmung.\n\n' +
    `> [!abstimmung] **${QUESTION}**\n> yes: 15, no: 3, abstain: 2`;
  const agenda = [
    { id: top(1), applicationId: null, title: 'Begrüßung und Beschlussfähigkeit', body: 'Die Sitzungsleitung eröffnet die Sitzung. Das Gremium ist beschlussfähig.', position: 0 },
    { id: top(2), applicationId: null, title: 'Protokoll der letzten Sitzung', body: 'Das Protokoll wird ohne Änderungen genehmigt.', position: 1 },
    { id: top(3), applicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', title: 'Beispielantrag Sommerfest', body: voteBody, position: 2 },
    { id: top(4), applicationId: null, title: 'Personalangelegenheit', body: '', position: 3, nonPublic: true },
    { id: top(5), applicationId: null, title: 'Verschiedenes', body: 'Keine Wortmeldungen.', position: 4 },
  ];
  const meeting: MeetingOutWire = {
    id,
    title,
    date: day(days),
    startTime: '18:00:00',
    endTime: null,
    status: 'closed',
    activeApplicationId: null,
    currentAgendaItemId: top(5),
    currentAgendaItem: { position: 5, title: 'Verschiedenes' },
    agendaItemCount: agenda.length,
    startedAt: at(days, 18, 4),
    closedAt: at(days, 21, 12),
    gremiumId: gremium.id,
    gremiumName: gremium.name,
    protocolId: `e0000000-0000-0000-0000-0000000001${prefix}`,
    protokollantId: DEMO_SUB,
    protokollantName: 'Demo Mitglied',
    isProtokollant: true,
    canControl: true,
    canManage: true,
    canWrite: true,
    canManageVotes: true,
    canVote: true,
    canFinalize: true,
    keeperPeriods: [
      {
        principalId: 'p-4',
        name: 'Uli Übernahme',
        fromAt: at(days, 18, 4),
        toAt: at(days, 18, 55),
        fromAgendaItemId: top(1),
        toAgendaItemId: top(3),
        fromPosition: 1,
        toPosition: 3,
      },
      {
        principalId: DEMO_SUB,
        name: 'Demo Mitglied',
        fromAt: at(days, 18, 55),
        toAt: at(days, 21, 12),
        fromAgendaItemId: top(3),
        toAgendaItemId: top(5),
        fromPosition: 3,
        toPosition: 5,
      },
    ],
    plannedHandover: null,
    votes: [
      {
        id: `a0000000-0000-0000-0000-0000000001${prefix}`,
        applicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        agendaItemId: top(3),
        title: 'Beispielantrag Sommerfest',
        question: QUESTION,
        options: ['yes', 'no', 'abstain'],
        status: 'closed',
        result: 'passed',
        counts: { yes: 15, no: 3, abstain: 2 },
        leading: 'yes',
        closesAt: null,
        voted: 20,
        present: 20,
        revealed: true,
        majorityRule: 'simple',
        secret: false,
        quorum: { type: 'count', value: 12 },
        openedAt: at(days, 18, 48),
        closedAt: at(days, 18, 52),
      },
    ],
    createdAt: at(days - 14, 9, 0),
  };
  const protocol: ProtocolOutWire = {
    id: meeting.protocolId as string,
    meetingId: id,
    markdown: '',
    status: final ? 'final' : 'draft',
    pdfUrl: final ? 'https://files.example/s/protokoll-intern.pdf' : null,
    publicPdfUrl: final ? 'https://files.example/s/protokoll-oeffentlich.pdf' : null,
    sentAt: final ? at(days + 1, 9, 30) : null,
  };
  return { meeting, agenda, protocol };
}

const STUPA = { id: 'g0000000-0000-0000-0000-000000000001', name: 'Studierendenparlament' };
const HHA = { id: 'g0000000-0000-0000-0000-000000000002', name: 'Haushaltsausschuss' };

const CLOSED: Record<string, ClosedMeeting> = {
  [CLOSED_DRAFT_ID]: closedMeeting(CLOSED_DRAFT_ID, -9, '33. Sitzung des Studierendenparlaments', false, STUPA),
  [CLOSED_FINAL_ID]: closedMeeting(CLOSED_FINAL_ID, -16, '11. Sitzung des Haushaltsausschusses', true, HHA),
};

/** GET of a closed demo meeting: the meeting, its agenda or its protocol. */
export function closedMeetingGet(id: string, path: string): unknown {
  const c = CLOSED[id];
  if (path.endsWith('/agenda')) return c.agenda.map((a) => ({ ...a }));
  if (path.endsWith('/protocol')) return { ...c.protocol };
  return { ...c.meeting };
}

/**
 * A write to a closed demo meeting: the text of an item (O22, while the protocol is a
 * draft), the protocol PATCH and the finalize. Anything else gives `undefined`.
 */
export function closedMeetingWrite(id: string, method: string, path: string, body: unknown): unknown {
  const c = CLOSED[id];
  const item = /\/agenda\/([^/]+)$/.exec(path);
  if (method === 'PATCH' && item) {
    const patch = (body as { body?: string; nonPublic?: boolean } | null) ?? {};
    c.agenda = c.agenda.map((a) => (a.id === item[1] ? { ...a, ...patch } : a));
    return c.agenda.map((a) => ({ ...a }));
  }
  if (method === 'PATCH' && /\/protocols\/[^/]+$/.test(path)) {
    c.protocol = { ...c.protocol, markdown: (body as { markdown?: string } | null)?.markdown ?? '' };
    return { ...c.protocol };
  }
  if (method === 'POST' && path.endsWith('/finalize')) {
    c.protocol = {
      ...c.protocol,
      status: 'final',
      pdfUrl: 'https://files.example/s/protokoll-intern.pdf',
      publicPdfUrl: c.agenda.some((a) => a.nonPublic)
        ? 'https://files.example/s/protokoll-oeffentlich.pdf'
        : null,
      sentAt: new Date().toISOString(),
    };
    return { ...c.protocol };
  }
  return undefined;
}
