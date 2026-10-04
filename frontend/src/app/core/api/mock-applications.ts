import type { HttpParams } from '@angular/common/http';
import type {
  ApplicationListItemWire,
  ApplicationOutWire,
  ApplicationShareLink,
  AttachmentOutWire,
  Page,
  StateOutWire,
  TransitionOutWire,
  TransitionResult,
} from './models';

/**
 * Demo applications of the mock backend (`?mock=1`) for the applications page. Dev and
 * tests only; the interceptor loads this module on first use.
 *
 * Sixteen applications over three months in five states, two types, some with an amount,
 * one archived, so the list shows its month groups, its status texts and its filters. The
 * state changes when a transition fires, and archive and delete act on the rows, so the
 * row menu and the detail header can be tried out.
 */

/** The id prefix of the demo rows. The interceptor sends these paths here. */
export const DEMO_APP_PREFIX = 'a1000000-';

const TYPE_FUND = '11111111-1111-1111-1111-111111111111';
const TYPE_OTHER = '22222222-2222-2222-2222-222222222222';
const GREMIUM = 'g0000000-0000-0000-0000-000000000001';
const BUDGET = 'b1000000-0000-0000-0000-000000000012';
const FISCAL_YEAR = 'f1000000-0000-0000-0000-000000000001';

const STATES = {
  submitted: { id: '66666666-6666-6666-6666-666666666661', key: 'submitted', label: { de: 'Eingereicht', en: 'Submitted' }, color: '#4a90d9', editAllowed: true },
  review: { id: '66666666-6666-6666-6666-666666666662', key: 'review', label: { de: 'In Prüfung', en: 'In review' }, color: '#e8a33d', editAllowed: false },
  agenda: { id: '66666666-6666-6666-6666-666666666665', key: 'agenda', label: { de: 'Auf Tagesordnung', en: 'On the agenda' }, color: '#72a384', editAllowed: false, kind: 'vote' },
  approved: { id: '66666666-6666-6666-6666-666666666666', key: 'approved', label: { de: 'Bewilligt', en: 'Approved' }, color: '#3f8f5a', editAllowed: false },
  rejected: { id: '66666666-6666-6666-6666-666666666664', key: 'rejected', label: { de: 'Abgelehnt', en: 'Rejected' }, color: '#c0392b', editAllowed: false },
} satisfies Record<string, StateOutWire>;

type StateKey = keyof typeof STATES;

/** The manual transitions out of each state, as the flow of the demo defines them. */
const FLOW: Record<StateKey, { id: string; to: StateKey; de: string; en: string; color?: string; agenda?: boolean }[]> = {
  submitted: [
    { id: '77777777-7777-7777-7777-777777777781', to: 'review', de: 'Prüfung beginnen', en: 'Start review' },
    { id: '77777777-7777-7777-7777-777777777782', to: 'rejected', de: 'Ablehnen', en: 'Reject', color: '#c0392b' },
  ],
  review: [
    { id: '77777777-7777-7777-7777-777777777783', to: 'agenda', de: 'Auf Tagesordnung setzen', en: 'Put on the agenda', color: '#72a384', agenda: true },
    { id: '77777777-7777-7777-7777-777777777784', to: 'submitted', de: 'Nachforderung stellen', en: 'Ask for more', color: '#e8a33d' },
    { id: '77777777-7777-7777-7777-777777777785', to: 'rejected', de: 'Ablehnen', en: 'Reject', color: '#c0392b' },
  ],
  agenda: [],
  approved: [],
  rejected: [],
};

interface DemoApp {
  n: number;
  title: string;
  type: string;
  state: StateKey;
  amount: number | null;
  created: string;
  archived?: string;
}

const DEMO: DemoApp[] = [
  { n: 1, title: 'Zuschuss Kennenlernwochenende der Fachschaft Wirtschaft', type: TYPE_FUND, state: 'agenda', amount: 1340, created: '2026-09-29T10:25:00Z' },
  { n: 2, title: 'Flyer für die Hochschulgruppen-Messe', type: TYPE_FUND, state: 'submitted', amount: 395, created: '2026-09-25T15:05:00Z' },
  { n: 3, title: 'Werkzeugkiste für die Fahrradwerkstatt', type: TYPE_OTHER, state: 'agenda', amount: 1765, created: '2026-09-22T08:40:00Z' },
  { n: 4, title: 'Lesung mit einer Autorin im Foyer', type: TYPE_FUND, state: 'review', amount: 1180, created: '2026-09-17T13:15:00Z' },
  { n: 5, title: 'Seminarreihe Nachhaltigkeit im Studium mit Referierenden und Verpflegung an drei Abenden', type: TYPE_FUND, state: 'submitted', amount: 2260, created: '2026-09-14T09:50:00Z' },
  { n: 6, title: 'Saatgut und Erde für den Campusgarten', type: TYPE_FUND, state: 'submitted', amount: 145, created: '2026-09-10T16:30:00Z' },
  { n: 7, title: 'Brandschutzhelfer-Kurs für Hochschulgruppen', type: TYPE_FUND, state: 'agenda', amount: 610, created: '2026-09-07T11:45:00Z' },
  { n: 8, title: 'Kamera für die Foto-AG', type: TYPE_OTHER, state: 'review', amount: 735, created: '2026-09-02T14:20:00Z' },
  { n: 9, title: 'Turnierbälle Hochschulsport Basketball', type: TYPE_FUND, state: 'review', amount: 455, created: '2026-08-28T10:35:00Z' },
  { n: 10, title: 'Banner für den Tag der offenen Tür', type: TYPE_FUND, state: 'approved', amount: 290, created: '2026-08-20T08:55:00Z' },
  { n: 11, title: 'Quizabend im Studierendencafé', type: TYPE_OTHER, state: 'review', amount: 175, created: '2026-08-13T18:10:00Z', archived: '2026-09-03T09:00:00Z' },
  { n: 12, title: 'Anreise zur Bundeskonferenz der Studierendenschaften', type: TYPE_OTHER, state: 'rejected', amount: 428.6, created: '2026-08-06T12:40:00Z' },
  { n: 13, title: 'Drucker für den Fachschaftsraum', type: TYPE_FUND, state: 'approved', amount: 349, created: '2026-07-30T09:20:00Z' },
  { n: 14, title: 'Bahnfahrt zur Gremienschulung', type: TYPE_OTHER, state: 'review', amount: 187.5, created: '2026-07-22T15:30:00Z' },
  { n: 15, title: 'Infoabend zum Auslandssemester', type: TYPE_OTHER, state: 'submitted', amount: null, created: '2026-07-15T10:45:00Z' },
  { n: 16, title: 'Beamer für den Seminarraum', type: TYPE_FUND, state: 'approved', amount: 820, created: '2026-07-03T13:05:00Z' },
];

/** The demo rows as they stand now. Transitions, archive and delete change them. */
let rows: DemoApp[] = DEMO.map((d) => ({ ...d }));

const idOf = (n: number): string => `${DEMO_APP_PREFIX}0000-0000-0000-${String(n).padStart(12, '0')}`;
const byId = (id: string): DemoApp | undefined => rows.find((r) => idOf(r.n) === id);

function listItem(d: DemoApp): ApplicationListItemWire {
  return {
    id: idOf(d.n),
    typeId: d.type,
    title: d.title,
    state: STATES[d.state],
    gremiumId: GREMIUM,
    amount: d.amount === null ? null : d.amount.toFixed(2),
    currency: 'EUR',
    createdAt: d.created,
    updatedAt: d.created,
    archivedAt: d.archived ?? null,
    stateSince: d.created,
  };
}

function detail(d: DemoApp): ApplicationOutWire {
  return {
    ...listItem(d),
    budgetId: BUDGET,
    fiscalYearId: FISCAL_YEAR,
    data: {
      title: d.title,
      description:
        'Ein Wochenende zum Kennenlernen mit Workshops, Wanderung und gemeinsamem Kochen.\n\nDer Antrag deckt die Unterkunft und die Busfahrt.',
      category: 'event',
      amount: d.amount,
    },
    version: d.n % 3 === 0 ? 1 : 2,
    lang: 'de',
    applicant: { name: 'Erika Beispiel', email: 'erika.beispiel@example.org', anonymized: false },
    canEdit: true,
    isOwner: false,
    hiddenKeys: [],
  };
}

function matches(d: DemoApp, params: HttpParams): boolean {
  const states = params.getAll('state') ?? [];
  if (states.length && !states.includes(STATES[d.state].id)) return false;
  const type = params.get('type');
  if (type && d.type !== type) return false;
  const archived = params.get('archived') ?? 'false';
  if (archived === 'false' && d.archived) return false;
  if (archived === 'true' && !d.archived) return false;
  const q = params.get('q')?.trim().toLowerCase();
  if (q && !d.title.toLowerCase().includes(q)) return false;
  const min = params.get('amountMin');
  if (min && (d.amount ?? 0) < Number(min)) return false;
  const max = params.get('amountMax');
  if (max && (d.amount ?? 0) > Number(max)) return false;
  const from = params.get('createdFrom');
  if (from && d.created.slice(0, 10) < from) return false;
  const to = params.get('createdTo');
  if (to && d.created.slice(0, 10) > to) return false;
  return true;
}

function list(params: HttpParams): Page<ApplicationListItemWire> {
  const sort = params.get('sort') === 'amount' ? 'amount' : 'createdAt';
  const dir = params.get('order') === 'asc' ? 1 : -1;
  const hits = rows
    .filter((d) => matches(d, params))
    .sort((a, b) =>
      sort === 'amount'
        ? ((a.amount ?? 0) - (b.amount ?? 0)) * dir
        : a.created.localeCompare(b.created) * dir,
    );
  const limit = Number(params.get('limit') ?? 20);
  const offset = Number(params.get('offset') ?? 0);
  return {
    items: hits.slice(offset, offset + limit).map(listItem),
    total: hits.length,
    limit,
    offset,
  };
}

function transitions(d: DemoApp): TransitionOutWire[] {
  return FLOW[d.state].map((t) => ({
    id: t.id,
    fromStateId: STATES[d.state].id,
    toStateId: STATES[t.to].id,
    label: { de: t.de, en: t.en },
    color: t.color ?? null,
    addsToAgenda: t.agenda === true,
    agendaGremiumId: t.agenda ? GREMIUM : null,
  }));
}

const ATTACHMENTS: AttachmentOutWire[] = [
  { id: 'att10000-0000-0000-0000-000000000001', filename: 'Angebot_Jugendherberge.pdf', mime: 'application/pdf', size: 236_000, scanned: true, is_comparison_offer: true },
  { id: 'att10000-0000-0000-0000-000000000002', filename: 'Angebot_Busunternehmen.pdf', mime: 'application/pdf', size: 171_000, scanned: true, is_comparison_offer: true },
  { id: 'att10000-0000-0000-0000-000000000003', filename: 'Programm_Wochenende.png', mime: 'image/png', size: 127_000, scanned: false, is_comparison_offer: false },
];

const DETAIL_PATH = /\/applications\/(a1000000-[^/]+)(?:\/(transitions|attachments|shares|flow-states))?$/;

/** GET of a demo path. `undefined`: not a path of this module. */
export function mockApplicationsGet(p: string, params: HttpParams): unknown {
  if (p.endsWith('/applications')) return list(params);
  const m = DETAIL_PATH.exec(p);
  const d = m ? byId(m[1]) : undefined;
  if (!m || !d) return undefined;
  switch (m[2]) {
    case 'transitions':
      return transitions(d);
    case 'attachments':
      return d.n % 2 === 1 ? ATTACHMENTS : [];
    case 'shares':
      return [] satisfies ApplicationShareLink[];
    case 'flow-states':
      return Object.values(STATES);
    default:
      return detail(d);
  }
}

const MUTATION_PATH = /\/applications\/(a1000000-[^/]+)(?:\/(transition|archive|force-status))?$/;

/** A write to a demo row. `undefined`: not a path of this module. */
export function mockApplicationsWrite(method: string, p: string, body: unknown): unknown {
  const m = MUTATION_PATH.exec(p);
  const d = m ? byId(m[1]) : undefined;
  if (!m || !d) return undefined;
  if (method === 'DELETE' && !m[2]) {
    rows = rows.filter((r) => r !== d);
    return null;
  }
  if (method === 'PATCH' && !m[2]) {
    const title = (body as { data?: { title?: unknown } } | null)?.data?.title;
    if (typeof title === 'string' && title.trim()) d.title = title.trim();
    return detail(d);
  }
  if (m[2] === 'archive') {
    d.archived = method === 'POST' ? new Date().toISOString() : undefined;
    return detail(d);
  }
  if (method === 'POST' && m[2] === 'transition') {
    const id = (body as { transitionId?: string } | null)?.transitionId;
    const t = FLOW[d.state].find((x) => x.id === id);
    if (t) d.state = t.to;
    const result: TransitionResult = {
      newStateId: STATES[d.state].id,
      statusEventId: 'e1000000-0000-0000-0000-000000000001',
      dispatchedActions: [],
    };
    return result;
  }
  if (method === 'POST' && m[2] === 'force-status') {
    const stateId = (body as { stateId?: string } | null)?.stateId;
    const key = (Object.keys(STATES) as StateKey[]).find((k) => STATES[k].id === stateId);
    if (key) d.state = key;
    return { newStateId: STATES[d.state].id, statusEventId: 'e1000000-0000-0000-0000-000000000002', dispatchedActions: [] };
  }
  return undefined;
}

/** Back to the start rows (tests). */
export function resetMockApplications(): void {
  rows = DEMO.map((d) => ({ ...d }));
}
