import type { HttpParams } from '@angular/common/http';
import type {
  ApplicantCandidate,
  ApplicationCapture,
  ApplicationCreatedWire,
  ApplicationListItemWire,
  ApplicationOutWire,
  ApplicationShareLink,
  AttachmentOutWire,
  EffectiveForm,
  MeetingOutWire,
  Page,
  OnBehalfApplication,
  ProblemDetail,
  StateOutWire,
  TimelineEventOutWire,
  TransitionOutWire,
  TransitionResult,
  VersionOutWire,
} from './models';

/**
 * Demo applications of the mock backend (`?mock=1`) for the applications page. Dev and
 * tests only; the interceptor loads this module on first use.
 *
 * Sixteen applications over three months in five states, two types, some with an amount,
 * one archived, so the list shows its month groups, its status texts and its filters. The
 * state changes when a transition fires, and archive and delete act on the rows, so the
 * row menu and the detail header can be tried out.
 *
 * The detail (FE4b) gets a form with three sections (Vorhaben, Kosten, Kontakt), cost
 * positions with offers (one without comparison offers), a history of status changes
 * and versions, and an edit that makes a new version. A position without any offer
 * gives the 422 of the server. Three planned meetings of the Gremium serve the agenda
 * dialog; a fire with `meetingId` checks that the meeting is one of them.
 *
 * "Antrag erfassen" (#11): the row "Flyer für die Hochschulgruppen-Messe" was captured
 * on behalf of the applicant (per PDF). The search knows three accounts, and a capture
 * adds a new row in "Eingereicht" on top.
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
  /** The answers after an edit. Until then `answers(d)` builds them. */
  data?: Record<string, unknown>;
  /** The versions after the first edit of this session. */
  versions?: VersionOutWire[];
  /** Status changes fired in this session. */
  events?: TimelineEventOutWire[];
  /** Captured on behalf of the applicant (#11). */
  capture?: ApplicationCapture;
}

const DEMO: DemoApp[] = [
  { n: 1, title: 'Zuschuss Kennenlernwochenende der Fachschaft Wirtschaft', type: TYPE_FUND, state: 'agenda', amount: 1340, created: '2026-09-29T10:25:00Z' },
  {
    n: 2,
    title: 'Flyer für die Hochschulgruppen-Messe',
    type: TYPE_FUND,
    state: 'submitted',
    amount: 395,
    created: '2026-09-25T15:05:00Z',
    capture: {
      capturedBy: { kind: 'principal', displayName: 'Clara Sachbearbeiterin' },
      capturedAt: '2026-09-25T15:05:00Z',
      receivedOn: '2026-09-23',
      intake: 'per PDF',
    },
  },
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
    data: answers(d),
    version: versionsOf(d).length,
    lang: 'de',
    applicant: { name: 'Erika Beispiel', email: 'erika.beispiel@example.org', anonymized: false },
    canEdit: true,
    isOwner: false,
    hiddenKeys: [],
    capture: d.capture ?? null,
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

const DETAIL_PATH =
  /\/applications\/(a1000000-[^/]+)(?:\/(transitions|attachments|shares|flow-states|form|timeline|versions))?$/;

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
    case 'form':
      return DEMO_FORM;
    case 'timeline':
      return timelineOf(d);
    case 'versions':
      return versionsOf(d);
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
    const data = (body as { data?: Record<string, unknown> } | null)?.data ?? {};
    const errors = positionErrors(data['costs']);
    if (errors.length) return { status: 422, problem: problem422(errors) } satisfies MockFailure;
    const before = answers(d);
    const versions = versionsOf(d);
    d.data = { ...data };
    d.versions = [
      ...versions,
      {
        version: versions.length + 1,
        data: d.data,
        diff: diffOf(before, d.data),
        changedBy: 'Demo Mitglied',
        changedByInfo: { kind: 'principal', displayName: 'Demo Mitglied' },
        at: new Date().toISOString(),
      },
    ];
    const title = data['title'];
    if (typeof title === 'string' && title.trim()) d.title = title.trim();
    return detail(d);
  }
  if (m[2] === 'archive') {
    d.archived = method === 'POST' ? new Date().toISOString() : undefined;
    return detail(d);
  }
  if (method === 'POST' && m[2] === 'transition') {
    const req = (body as { transitionId?: string; meetingId?: string | null; note?: string | null } | null) ?? {};
    const t = FLOW[d.state].find((x) => x.id === req.transitionId);
    if (req.meetingId && !agendaMeetings().some((mt) => mt.id === req.meetingId)) {
      return {
        status: 422,
        problem: {
          ...problem422([{ field: 'meetingId', msg: 'The meeting is not planned.' }]),
          code: 'agenda_meeting_invalid',
        },
      } satisfies MockFailure;
    }
    if (t) {
      const meeting = agendaMeetings().find((mt) => mt.id === req.meetingId);
      d.events = [
        ...(d.events ?? []),
        {
          fromStateId: STATES[d.state].id,
          toStateId: STATES[t.to].id,
          toState: STATES[t.to],
          transitionLabel: { de: t.de, en: t.en },
          actor: 'Demo Mitglied',
          actorInfo: { kind: 'principal', displayName: 'Demo Mitglied' },
          at: new Date().toISOString(),
          note: [meeting?.title, req.note].filter(Boolean).join(' · ') || null,
        },
      ];
      d.state = t.to;
    }
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

/** #11: the accounts that the capture search knows. */
const ACCOUNTS: ApplicantCandidate[] = [
  { id: 'p1000000-0000-0000-0000-000000000001', displayName: 'Anna Antrag', email: 'anna.antrag@example.org' },
  { id: 'p1000000-0000-0000-0000-000000000002', displayName: 'Anton Albers', email: 'anton.albers@example.org' },
  { id: 'p1000000-0000-0000-0000-000000000003', displayName: 'Bea Beispiel', email: 'bea@example.org' },
];

/** `GET /applications/on-behalf/applicants`: the accounts whose name or e-mail holds `q`. */
export function mockApplicantSearch(q: string): ApplicantCandidate[] {
  const needle = q.trim().toLowerCase();
  return ACCOUNTS.filter((a) => `${a.displayName} ${a.email}`.toLowerCase().includes(needle));
}

/** `POST /applications/on-behalf`: a new row on top, captured by the demo member. */
export function mockCapture(body: OnBehalfApplication): ApplicationCreatedWire {
  const n = Math.max(...rows.map((r) => r.n)) + 1;
  const now = new Date().toISOString();
  rows.unshift({
    n,
    title: String(body.data['title']),
    type: body.typeId,
    state: 'submitted',
    amount: null,
    created: now,
    data: { ...body.data },
    capture: {
      capturedBy: { kind: 'principal', displayName: 'Demo Mitglied' },
      capturedAt: now,
      receivedOn: body.receivedOn ?? null,
      intake: body.intake ?? null,
    },
  });
  return { applicationId: idOf(n) };
}

/** Back to the start rows (tests). */
export function resetMockApplications(): void {
  rows = DEMO.map((d) => ({ ...d }));
}

/** A refused write: the interceptor answers with this status and problem. */
export interface MockFailure {
  status: number;
  problem: ProblemDetail;
}

/** True for a refused write of this module. */
export function isMockFailure(body: unknown): body is MockFailure {
  return typeof body === 'object' && body !== null && 'problem' in body && 'status' in body;
}

function problem422(errors: { field: string; msg: string }[]): ProblemDetail {
  return {
    type: 'about:blank',
    title: 'Unprocessable Entity',
    status: 422,
    code: 'validation_error',
    detail: 'Invalid application data.',
    errors,
  };
}

// --------------------------------------------------------------------- the form

const OPTIONS_CATEGORY = [
  { value: 'event', label: { de: 'Veranstaltung', en: 'Event' } },
  { value: 'firstyear', label: { de: 'Erstsemester', en: 'First year' } },
  { value: 'culture', label: { de: 'Kultur', en: 'Culture' } },
];

/** The form of the demo applications: three sections, as on the boards. */
const DEMO_FORM: EffectiveForm = {
  applicationTypeId: TYPE_FUND,
  formVersionId: 'f0000000-0000-0000-0000-0000000000f1',
  hasBudget: true,
  sections: [
    {
      key: 'plan',
      label: { de: 'Vorhaben', en: 'Project' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel', en: 'Title' }, required: true },
        { key: 'description', type: 'textarea', label: { de: 'Beschreibung', en: 'Description' }, required: true },
        { key: 'event_date', type: 'date', label: { de: 'Veranstaltungsdatum', en: 'Event date' } },
        { key: 'participants', type: 'number', label: { de: 'Erwartete Teilnehmende', en: 'Expected participants' } },
        // The room question sits mid-section, so a hidden room shows whether the next
        // field moves up into its cell.
        { key: 'needs_room', type: 'checkbox', label: { de: 'Raum der Hochschule nötig', en: 'Needs a university room' } },
        {
          key: 'room',
          type: 'text',
          label: { de: 'Raum', en: 'Room' },
          visibleIf: { '==': [{ var: 'needs_room' }, true] },
        },
        {
          key: 'gremium',
          type: 'gremium_select',
          label: { de: 'Zuständiges Gremium', en: 'Responsible committee' },
          options: [{ value: GREMIUM, label: { de: 'Studierendenparlament', en: 'Studierendenparlament' } }],
        },
        { key: 'category', type: 'multiselect', label: { de: 'Kategorie', en: 'Category' }, options: OPTIONS_CATEGORY },
      ],
    },
    {
      key: 'costs_section',
      label: { de: 'Kosten', en: 'Costs' },
      fields: [
        { key: 'costs', type: 'positions', label: { de: 'Kostenaufstellung', en: 'Cost breakdown' }, required: true, validation: { minOffers: 2 } },
        { key: 'entry_fee', type: 'currency', label: { de: 'Eintritt je Person', en: 'Entry fee per person' } },
        {
          key: 'income',
          type: 'computed',
          label: { de: 'Einnahmen aus Eintritt', en: 'Income from entry fees' },
          compute: { '*': [{ var: 'entry_fee' }, { var: 'participants' }] },
        },
      ],
    },
    {
      key: 'contact',
      label: { de: 'Kontakt', en: 'Contact' },
      fields: [
        { key: 'payout_note', type: 'markdown', label: { de: 'Hinweis', en: 'Note' }, help: { de: 'Die Auszahlung geht an dieses Konto.', en: 'The payout goes to this account.' } },
        { key: 'iban', type: 'iban', label: { de: 'IBAN für die Auszahlung', en: 'IBAN for the payout' }, isPII: true },
      ],
    },
  ],
};

/** The form of the demo type "Finanzantrag", for the apply wizard of the mock API. */
export function demoForm(): EffectiveForm {
  return DEMO_FORM;
}

/** The cost positions of a demo amount: three positions, the last without offers. */
function positionsFor(amount: number): Record<string, unknown>[] {
  const a = Math.round(amount * 45) / 100;
  const b = Math.round(amount * 35) / 100;
  const c = Math.round((amount - a - b) * 100) / 100;
  return [
    {
      label: 'Raummiete inkl. Reinigung',
      offers: [
        { label: 'Studierendenwerk', value: a, preferred: true },
        { label: 'Stadthalle', value: Math.round(a * 118) / 100, preferred: false },
        { label: 'Gemeindezentrum Nord', value: Math.round(a * 131) / 100, preferred: false },
      ],
    },
    {
      label: 'Verpflegung',
      offers: [
        { label: 'Mensa-Catering', value: b, preferred: true },
        // A supplier named by the URL of its offer: the view links it and wraps it.
        { label: 'https://www.baeckerei-am-campus.example/catering/angebote/sommerfest-2026',
          value: Math.round(b * 109) / 100, preferred: false },
      ],
    },
    {
      label: 'Technik und Ton',
      noOffers: true,
      noOffersReason: 'Rahmenvertrag mit dem Technik-Team der Hochschule; andere Anbieter dürfen die Anlage nicht bedienen.',
      offers: [{ label: 'Technik-Team der Hochschule', value: c, preferred: true }],
    },
  ];
}

/** The answers of a demo application as the server stores them. */
function answers(d: DemoApp): Record<string, unknown> {
  if (d.data) return d.data;
  return {
    title: d.title,
    description:
      'Ein Abend zum Kennenlernen mit **Workshops**, Musik und Verpflegung.\n\nDer Antrag deckt Raum, Verpflegung und Technik.',
    event_date: '2026-10-16',
    participants: 120,
    gremium: GREMIUM,
    category: ['event', 'firstyear'],
    needs_room: false,
    ...(d.amount === null ? {} : { costs: positionsFor(d.amount) }),
    entry_fee: 3,
    iban: 'DE89 3704 0044 0532 0130 00',
  };
}

/** The versions: one, or two when the applicant changed the participants once. */
function versionsOf(d: DemoApp): VersionOutWire[] {
  if (d.versions) return d.versions;
  const first: VersionOutWire = {
    version: 1,
    data: { ...answers(d), participants: 100 },
    diff: null,
    changedBy: 'applicant',
    changedByInfo: { kind: 'applicant' },
    at: d.created,
  };
  if (d.n % 3 === 0) return [first];
  return [
    first,
    {
      version: 2,
      data: answers(d),
      diff: { added: {}, removed: {}, changed: { participants: { old: 100, new: 120 } } },
      // Every other demo: the edit came from an account that no longer exists. The
      // server sends no name and no sub; the UI shows "Ehemaliges Konto".
      ...(d.n % 2
        ? { changedBy: null, changedByInfo: { kind: 'deleted' as const } }
        : { changedBy: 'applicant', changedByInfo: { kind: 'applicant' as const } }),
      at: new Date(new Date(d.created).getTime() + 26 * 3600_000).toISOString(),
    },
  ];
}

/** The way of a state through the demo flow, from the submission on. */
const PATH: Record<StateKey, StateKey[]> = {
  submitted: ['submitted'],
  review: ['submitted', 'review'],
  agenda: ['submitted', 'review', 'agenda'],
  approved: ['submitted', 'review', 'agenda', 'approved'],
  rejected: ['submitted', 'rejected'],
};

/**
 * The actor of the i-th status change of the demo timeline: the applicant submits, a
 * member moves it on, the deadline cron fires the third step (`system:deadlines`).
 */
function actorOf(i: number): Pick<TimelineEventOutWire, 'actor' | 'actorInfo'> {
  if (i === 0) return { actor: 'applicant', actorInfo: { kind: 'applicant' } };
  if (i === 2) return { actor: 'system:deadlines', actorInfo: { kind: 'system', key: 'deadlines' } };
  return { actor: 'Mara Keller', actorInfo: { kind: 'principal', displayName: 'Mara Keller' } };
}

/** The status changes: the submission, the way to the start state, then this session. */
function timelineOf(d: DemoApp): TimelineEventOutWire[] {
  const start = (d.events ?? []).length ? PATH[stateBefore(d)] : PATH[d.state];
  const base = new Date(d.created).getTime();
  const events: TimelineEventOutWire[] = start.map((key, i) => {
    const prev = i ? start[i - 1] : null;
    const t = prev ? FLOW[prev].find((x) => x.to === key) : undefined;
    return {
      fromStateId: prev ? STATES[prev].id : null,
      toStateId: STATES[key].id,
      toState: STATES[key],
      transitionLabel: t ? { de: t.de, en: t.en } : key === 'approved' ? { de: 'Bewilligen', en: 'Approve' } : null,
      ...actorOf(i),
      at: new Date(base + i * 2 * 86_400_000 + 3_600_000).toISOString(),
      note: null,
    };
  });
  return [...events, ...(d.events ?? [])];
}

/** The state before the first transition of this session. */
function stateBefore(d: DemoApp): StateKey {
  const first = d.events?.[0]?.fromStateId;
  return (Object.keys(STATES) as StateKey[]).find((k) => STATES[k].id === first) ?? d.state;
}

/** The changed keys between two answer sets, as the server's diff. */
function diffOf(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): NonNullable<VersionOutWire['diff']> {
  const diff: NonNullable<VersionOutWire['diff']> = { added: {}, removed: {}, changed: {} };
  for (const [k, v] of Object.entries(after)) {
    if (!(k in before)) diff.added[k] = v;
    else if (JSON.stringify(before[k]) !== JSON.stringify(v)) diff.changed[k] = { old: before[k], new: v };
  }
  for (const [k, v] of Object.entries(before)) if (!(k in after)) diff.removed[k] = v;
  return diff;
}

/** The server's rule for a position without comparison offers: still one offer (D12). */
function positionErrors(raw: unknown): { field: string; msg: string }[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((p: { noOffers?: boolean; offers?: unknown[] }, i) =>
    p?.noOffers === true && (!Array.isArray(p.offers) || p.offers.length < 1)
      ? [{ field: `costs[${i}]`, msg: 'needs at least 1 comparison offer(s)' }]
      : [],
  );
}

// --------------------------------------------------------------------- meetings

/** A local `YYYY-MM-DD`, `days` away from today. */
function dayFromToday(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** The planned meetings of the demo Gremium, for the agenda dialog. */
export function agendaMeetings(): MeetingOutWire[] {
  const meeting = (n: number, title: string, days: number, items: number): MeetingOutWire => ({
    id: `d1000000-0000-0000-0000-00000000000${n}`,
    title,
    date: dayFromToday(days),
    startTime: '18:00:00',
    endTime: '21:00:00',
    status: 'planned',
    gremiumId: GREMIUM,
    gremiumName: 'Studierendenparlament',
    agendaItemCount: items,
    votes: [],
    createdAt: '2026-09-01T10:00:00Z',
  });
  return [
    meeting(1, '34. Sitzung des Studierendenparlaments', 6, 7),
    meeting(2, '35. Sitzung des Studierendenparlaments', 20, 6),
    meeting(3, 'Sondersitzung des Studierendenparlaments', 27, 1),
  ];
}
