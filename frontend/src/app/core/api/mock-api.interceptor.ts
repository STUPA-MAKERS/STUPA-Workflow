import {
  type HttpEvent,
  HttpErrorResponse,
  type HttpInterceptorFn,
  type HttpRequest,
  HttpResponse,
} from '@angular/common/http';
import { inject, isDevMode } from '@angular/core';
import { type Observable, from, of, throwError } from 'rxjs';
import { delay, mergeMap } from 'rxjs/operators';
import { USE_MOCK_API } from './api.config';
import type { Delegation } from './delegations.service';
import type {
  OnBehalfApplication,
  ApplicationCreatedWire,
  ApplicationListItemWire,
  ApplicationOutWire,
  ApplicationTypeListItemWire,
  AttachmentOutWire,
  DraftAttachmentOutWire,
  BallotResult,
  CommentOutWire,
  EffectiveForm,
  KeeperPeriod,
  MagicLinkVerifyResult,
  MeetingOutWire,
  MeetingPageWire,
  MyBallot,
  Page,
  PublicSiteConfig,
  Principal,
  ProtocolOutWire,
  SearchHit,
  SearchResults,
  SignedUrlOutWire,
  StateOutWire,
  TimelineEventOutWire,
  TransitionOutWire,
  TransitionResult,
  VersionOutWire,
  Vote,
} from './models';

/**
 * In-memory mock backend for FE and skeleton operation.
 *
 * It runs only when `USE_MOCK_API` is true. It answers only `/api/*`.
 *
 * Responses use the backend wire form (`*Wire`, camelCase via `_CamelModel`).
 * The `ApiClient` maps them like a real backend response. This keeps the mock
 * true to the contract and exercises the mapper layer.
 */
const MOCK_PRINCIPAL: Principal = {
  sub: '00000000-0000-0000-0000-000000000001',
  display_name: 'Demo Mitglied',
  email: 'demo@stupa.example',
  roles: ['member'],
  // The mock grants every permission a gated view needs, so the dev, harness
  // and demo builds show those views. `application.manage` drives the RBAC
  // actions on the detail page. The gremium permissions below (`session.manage`,
  // `vote.manage`, `vote.cast`, `protocol.write`, `protocol.finalize`) drive the
  // vote views, the beamer, the meeting management and the protocol editor.
  // `admin.site`, `admin.gremien`, `admin.types`, `form.configure`,
  // `flow.configure`, `admin.group_mappings` and `webhook.manage` drive the admin UIs.
  permissions: [
    'application.read',
    'application.manage',
    // The row menu and the header of the applications page: transitions, export, share
    // links, archive, delete and force status.
    'application.transition',
    'application.export',
    'application.share',
    'application.archive',
    'application.delete',
    'application.force_status',
    // #11: "Antrag erfassen" on the applications page.
    'application.create_on_behalf',
    'admin.site',
    'admin.gremien',
    'admin.types',
    'admin.notifications',
    'admin.roles',
    'admin.group_mappings',
    'form.configure',
    'flow.configure',
    'webhook.manage',
    // The other admin pages of the admin frame: people and rights, gremien, the
    // security and data pages.
    'admin.users',
    'admin.users.merge',
    'admin.gremium_roles',
    'admin.cd_variants',
    'admin.delegations',
    'admin.deadlines',
    'audit.read',
    'audit.verify',
    'audit.revert',
    'privacy.manage',
    'backup.manage',
    // `budget.view`, `budget.structure`, `budget.book` and `budget.export` drive the
    // budget page and its export.
    'budget.view',
    'budget.structure',
    'budget.book',
    'budget.export',
    // "API-Zugang" in the account menu and the account navigation, and the MCP setup.
    'mcp.use',
  ],
  groups: [],
  gremien: [
    { id: 'g0000000-0000-0000-0000-000000000001', name: 'Studierendenparlament', slug: 'stupa' },
    { id: 'g0000000-0000-0000-0000-000000000002', name: 'Haushaltsausschuss', slug: 'haushalt' },
  ],
  session_manage_gremien: ['g0000000-0000-0000-0000-000000000001'],
  gremium_permissions: {
    'g0000000-0000-0000-0000-000000000001': [
      'session.manage',
      'vote.manage',
      'vote.cast',
      'protocol.write',
      'protocol.finalize',
    ],
    'g0000000-0000-0000-0000-000000000002': ['vote.cast'],
  },
};

/** Running demo vote (GET /votes/{id}): item 3 of the live demo meeting. */
const MOCK_VOTE: Vote = {
  id: 'vote-demo',
  applicationId: 'app-demo',
  meetingId: 'd0000000-0000-0000-0000-000000000001',
  agendaItemId: 'ag-s3',
  question: 'Soll der Antrag „Förderung Ersti-Wochenende“ wie beschrieben gefördert werden?',
  // A vote names the gremium that votes by its id.
  eligibleGroup: 'g0000000-0000-0000-0000-000000000001',
  config: {
    options: ['yes', 'no', 'abstain'],
    majorityRule: 'two_thirds',
    quorum: { type: 'percent', value: 50 },
    abstainCountsQuorum: true,
    secret: false,
  },
  status: 'open',
  opensAt: '2026-06-06T09:00:00Z',
  closesAt: null,
  result: null,
  secret: false,
  majorityRule: 'two_thirds',
  quorum: { type: 'percent', value: 50 },
  openedAt: '2026-06-06T09:00:00Z',
  closedAt: null,
  // Not every present member voted yet, so the server hides the counts.
  tally: { counts: {}, eligible: 12, voted: 8, present: 12, revealed: false, quorumMet: true, leading: null },
  myBallot: { cast: false, choice: null },
  representedCast: false,
  canManage: true,
  canCast: true,
};

/** The ballots of the demo user in this mock session, by vote id. */
const MOCK_BALLOTS = new Map<string, { own?: string; proxy?: string }>();

/** The closed votes of the closed demo meetings (`mock-meetings-closed.ts`). */
const CLOSED_VOTE_ID = /^a0000000-0000-0000-0000-0000000001(\d\d)$/;

/** GET /votes/{id}: the demo vote under the asked id, with the own ballots of the mock. */
function mockVote(id: string): Vote {
  const closed = CLOSED_VOTE_ID.exec(id);
  if (closed) {
    return {
      ...MOCK_VOTE,
      id,
      meetingId: `d0000000-0000-0000-0000-0000000001${closed[1]}`,
      agendaItemId: `ag-c${closed[1]}-3`,
      question: 'Soll der Antrag „Beispielantrag Sommerfest“ wie beschrieben gefördert werden?',
      status: 'closed',
      result: 'passed',
      majorityRule: 'simple',
      quorum: { type: 'count', value: 12 },
      closedAt: '2026-06-12T16:52:00Z',
      tally: { counts: { yes: 15, no: 3, abstain: 2 }, eligible: 20, voted: 20, present: 0, revealed: true, quorumMet: true, leading: 'yes', result: 'passed' },
      myBallot: { cast: true, choice: 'yes' },
    };
  }
  const ballots = MOCK_BALLOTS.get(id) ?? {};
  const extra = (ballots.own ? 1 : 0) + (ballots.proxy ? 1 : 0);
  return {
    ...MOCK_VOTE,
    id,
    // The demo vote is not secret, so the own ballot keeps its choice.
    myBallot: { cast: Boolean(ballots.own), choice: ballots.own ?? null },
    representedCast: Boolean(ballots.proxy),
    tally: { ...MOCK_VOTE.tally, voted: (MOCK_VOTE.tally.voted ?? 0) + extra },
  };
}

/** The own ballot of this mock session in one vote, for the vote list. */
function mockOwnBallot(id: string): MyBallot | null {
  const own = MOCK_BALLOTS.get(id)?.own;
  return own ? { cast: true, choice: own } : null;
}

/** The standalone demo votes of `mock-votes.ts` (id prefix `b0000000-`). */
const DEMO_VOTE_PATH = /\/votes\/b0000000-[^/]+$/;

/** POST /votes/{id}/ballot: a ballot never changes, so a second one is a 409. */
function mockBallot(id: string, body: unknown, url: string): Observable<never> | BallotResult {
  const { choice, asDelegation } = (body ?? {}) as { choice?: string; asDelegation?: boolean };
  const ballots = MOCK_BALLOTS.get(id) ?? {};
  const row = asDelegation ? 'proxy' : 'own';
  if (ballots[row]) return mockProblem(409, 'already_voted', url);
  MOCK_BALLOTS.set(id, { ...ballots, [row]: choice ?? 'yes' });
  return { status: 'cast' };
}

const MOCK_TYPES: Page<ApplicationTypeListItemWire> = {
  items: [
    {
      id: '11111111-1111-1111-1111-111111111111',
      name: 'Finanzantrag',
      hasBudget: true,
      active: true,
      activeFormVersionId: '44444444-4444-4444-4444-444444444444',
    },
    {
      id: '22222222-2222-2222-2222-222222222222',
      name: 'Sonstiger Antrag',
      hasBudget: false,
      active: true,
      activeFormVersionId: '44444444-4444-4444-4444-444444444445',
    },
    {
      id: '22222222-2222-2222-2222-222222222223',
      name: 'Projektantrag: QSM',
      hasBudget: false,
      active: true,
      activeFormVersionId: '44444444-4444-4444-4444-444444444446',
    },
  ],
  total: 3,
  limit: 20,
  offset: 0,
};

const MOCK_APP_ID = '33333333-3333-3333-3333-333333333333';

const MOCK_EFFECTIVE_FORM: EffectiveForm = {
  applicationTypeId: MOCK_TYPES.items[0].id,
  formVersionId: '44444444-4444-4444-4444-444444444444',
  hasBudget: false,
  sections: [
    {
      key: 'main',
      label: { de: 'Antrag', en: 'Application' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel', en: 'Title' }, required: true },
        {
          key: 'description',
          type: 'textarea',
          label: { de: 'Beschreibung', en: 'Description' },
          help: { de: 'Worum geht es?', en: 'What is it about?' },
        },
        {
          key: 'category',
          type: 'select',
          label: { de: 'Kategorie', en: 'Category' },
          required: true,
          options: [
            { value: 'event', label: { de: 'Veranstaltung', en: 'Event' } },
            { value: 'material', label: { de: 'Material', en: 'Material' } },
          ],
        },
        {
          key: 'needs_detail',
          type: 'checkbox',
          label: { de: 'Zusatzangaben nötig', en: 'Needs details' },
        },
        {
          key: 'detail',
          type: 'textarea',
          label: { de: 'Details', en: 'Details' },
          required: true,
          visibleIf: { '==': [{ var: 'needs_detail' }, true] },
        },
        {
          key: 'amount',
          type: 'currency',
          label: { de: 'Betrag (€)', en: 'Amount (€)' },
          required: true,
          validation: { min: 0 },
          isPromoted: true,
          promoteTarget: 'amount',
        },
      ],
    },
    {
      key: 'budget',
      label: { de: 'Budget-spezifische Felder', en: 'Budget-specific fields' },
      fields: [
        {
          key: 'cofunding',
          type: 'currency',
          label: { de: 'Eigenanteil (€)', en: 'Co-funding (€)' },
          validation: { min: 0 },
        },
        {
          key: 'total',
          type: 'computed',
          label: { de: 'Gesamtsumme (€)', en: 'Total (€)' },
          compute: { '+': [{ var: 'amount' }, { var: 'cofunding' }] },
        },
      ],
    },
    {
      // One field of each remaining type, so the wizard of "Sonstiger Antrag" shows
      // every field look of the forms engine.
      key: 'more',
      label: { de: 'Eckdaten', en: 'Key facts' },
      fields: [
        {
          key: 'more_info',
          type: 'markdown',
          label: { de: 'Ein Info-Text ohne eigene Hilfe.', en: 'An info text without help.' },
        },
        {
          key: 'more_name',
          type: 'text',
          label: { de: 'Name der Veranstaltung', en: 'Event name' },
          help: { de: 'z. B. Sommerfest 2026', en: 'e.g. summer party 2026' },
        },
        {
          key: 'more_count',
          type: 'number',
          label: { de: 'Anzahl Teilnehmende', en: 'Participants' },
          required: true,
          validation: { min: 1 },
        },
        { key: 'more_date', type: 'date', label: { de: 'Stichtag', en: 'Reference date' } },
        {
          key: 'more_range',
          type: 'daterange',
          label: { de: 'Zeitraum der Veranstaltung', en: 'Event period' },
          required: true,
        },
        {
          key: 'more_kinds',
          type: 'multiselect',
          label: { de: 'Zielgruppen', en: 'Audiences' },
          options: [
            { value: 'first', label: { de: 'Erstsemester', en: 'First year' } },
            { value: 'all', label: { de: 'Alle Studierenden', en: 'All students' } },
          ],
        },
        { key: 'more_file', type: 'file', label: { de: 'Programm', en: 'Programme' } },
        {
          key: 'more_confirm',
          type: 'checkbox',
          label: { de: 'Die Angaben sind vollständig.', en: 'The details are complete.' },
          required: true,
        },
      ],
    },
  ],
};

/** A select option with the same German and English text. */
function opt(value: string, de: string, en = de): { value: string; label: { de: string; en: string } } {
  return { value, label: { de, en } };
}

/**
 * The form of "Projektantrag: QSM", cut down to the questions that depend on other
 * answers. With "Person", the two institution questions are hidden, so the wizard shows
 * whether the next questions move up into their cells.
 */
const MOCK_QSM_FORM: EffectiveForm = {
  applicationTypeId: MOCK_TYPES.items[2].id,
  formVersionId: '44444444-4444-4444-4444-444444444446',
  hasBudget: false,
  sections: [
    {
      key: 'section_1',
      label: { de: 'Projekttitel', en: 'Project title' },
      fields: [
        { key: 'title', type: 'text', label: { de: 'Titel', en: 'Title' }, required: true },
        {
          key: 'info_text',
          type: 'markdown',
          label: {
            de: 'Bspw. Erstsemesterwochenende der Fakultät XYZ im WiSe XX/XX',
            en: 'e.g. Freshman Weekend of the faculty XYZ in the Winter Term XX/XX',
          },
        },
      ],
    },
    {
      key: 'section_2',
      label: { de: 'Antragsteller', en: 'Applicant' },
      fields: [
        {
          key: 'antragsteller_art',
          type: 'select',
          label: { de: 'Art des Antragstellers', en: 'Type of applicant' },
          required: true,
          options: [opt('person', 'Person'), opt('institution', 'Institution')],
        },
        {
          key: 'institution_art',
          type: 'select',
          label: { de: 'Art der Institution', en: 'Type of institution' },
          options: [opt('fachschaft', 'Fachschaft', 'Student council'), opt('verein', 'Verein', 'Association')],
          visibleIf: { '==': [{ var: 'antragsteller_art' }, 'institution'] },
        },
        {
          key: 'institution_name',
          type: 'text',
          label: { de: 'Name der Institution', en: 'Name of institution' },
          visibleIf: { '==': [{ var: 'antragsteller_art' }, 'institution'] },
        },
        {
          key: 'fakultaet',
          type: 'select',
          label: { de: 'Fakultät', en: 'Faculty' },
          required: true,
          options: [opt('inf', 'Informatik (INF)', 'Informatics (INF)'), opt('esb', 'ESB Business School (ESB)')],
        },
        {
          key: 'rolle',
          type: 'select',
          label: { de: 'Rolle', en: 'Role' },
          options: [opt('studierende_r', 'Studierende:r', 'Student'), opt('sonstige', 'Sonstige', 'Other')],
        },
        { key: 'telefon', type: 'text', label: { de: 'Telefonnummer', en: 'Phone number' } },
      ],
    },
    {
      key: 'section_7',
      label: { de: 'Checkliste: QS-Mittel', en: 'Checklist: QS funds' },
      fields: [
        {
          key: 'ist_exkursion',
          type: 'checkbox',
          label: { de: 'Das Projekt ist eine Exkursion', en: 'The project is a field trip' },
        },
        {
          key: 'cl_exkursion_genehmigt',
          type: 'checkbox',
          label: { de: 'Die Exkursion wurde von der Fakultät genehmigt', en: 'The faculty approved the field trip' },
          required: true,
          visibleIf: { '==': [{ var: 'ist_exkursion' }, true] },
        },
        {
          key: 'cl_zugute',
          type: 'checkbox',
          label: { de: 'Die Maßnahme kommt den Studierenden zugute', en: 'The measure benefits the students' },
          required: true,
        },
      ],
    },
  ],
};

const SUBMITTED_STATE: StateOutWire = {
  id: '66666666-6666-6666-6666-666666666661',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};

const REVIEW_STATE: StateOutWire = {
  id: '66666666-6666-6666-6666-666666666662',
  key: 'review',
  label: { de: 'In Prüfung', en: 'In review' },
  color: '#e8a33d',
  editAllowed: false,
};

/**
 * The answers of the demo application of the applicant status page, in the keys of the
 * demo form (`mock-applications.ts`), which the status page loads for the type.
 */
const MOCK_APP_DATA: Record<string, unknown> = {
  title: 'Förderung Ersti-Wochenende 2026',
  description: 'Zwei Tage Programm für die neuen Studierenden.',
  event_date: '2026-10-17',
  participants: 80,
  category: ['event', 'firstyear'],
};

/** The attachments of the demo application (`GET …/attachments`). */
const MOCK_APP_ATTACHMENTS: AttachmentOutWire[] = [
  {
    id: 'att00000-0000-0000-0000-000000000011',
    filename: 'Kostenaufstellung.pdf',
    mime: 'application/pdf',
    size: 182_340,
    scanned: true,
    is_comparison_offer: false,
  },
  {
    id: 'att00000-0000-0000-0000-000000000012',
    filename: 'Angebot-Bus.pdf',
    mime: 'application/pdf',
    size: 96_512,
    scanned: true,
    is_comparison_offer: true,
  },
];

function mockApplication(data: Record<string, unknown> = MOCK_APP_DATA): ApplicationOutWire {
  return {
    id: MOCK_APP_ID,
    typeId: MOCK_TYPES.items[0].id,
    state: SUBMITTED_STATE,
    // The last event of MOCK_TIMELINE: the application went back to the applicant.
    stateSince: '2026-06-05T13:00:00Z',
    gremiumId: null,
    amount: null,
    currency: 'EUR',
    data,
    version: 1,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-05T10:00:00Z',
  };
}

/**
 * The applications of the global search (`GET /search`). The list page has its own demo
 * rows in `mock-applications.ts`.
 */
const MOCK_APPLICATIONS: Page<ApplicationOutWire> = {
  items: [
    {
      id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      typeId: '11111111-1111-1111-1111-111111111111',
      state: { ...SUBMITTED_STATE, editAllowed: false },
      gremiumId: null,
      amount: '250.00',
      currency: 'EUR',
      data: { title: 'Förderung Ersti-Wochenende' },
      version: 1,
      lang: 'de',
      createdAt: '2026-05-30T09:00:00Z',
      updatedAt: '2026-05-30T09:00:00Z',
      stateSince: '2026-05-30T09:00:00Z',
    },
    {
      id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      typeId: '22222222-2222-2222-2222-222222222222',
      state: {
        id: '66666666-6666-6666-6666-666666666663',
        key: 'draft',
        label: { de: 'Entwurf', en: 'Draft' },
        color: null,
        editAllowed: true,
      },
      gremiumId: null,
      amount: null,
      currency: 'EUR',
      data: { title: 'Anschaffung Beamer' },
      version: 1,
      lang: 'de',
      createdAt: '2026-06-02T14:30:00Z',
      updatedAt: '2026-06-02T14:30:00Z',
      stateSince: '2026-06-02T14:30:00Z',
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

/**
 * Open decisions for the current role: GET /applications/tasks.
 *
 * The list holds only applications in vote states the principal may act on. An
 * approval row carries an inline accept and reject. A vote row opens the detail
 * page.
 */
const MOCK_TASKS: ApplicationListItemWire[] = [
  {
    id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
    typeId: '11111111-1111-1111-1111-111111111111',
    state: {
      id: '66666666-6666-6666-6666-666666666671',
      key: 'finance_approval',
      label: { de: 'Finanz-Freigabe', en: 'Finance approval' },
      color: '#9b59b6',
      editAllowed: false,
      kind: 'vote',
    },
    gremiumId: null,
    amount: '480.00',
    currency: 'EUR',
    title: 'Hardware für Fachschaftsraum',
    createdAt: '2026-06-06T08:15:00Z',
    updatedAt: '2026-06-07T16:00:00Z',
    // The time of the last status change (A9): "Wartet seit" counts from here.
    stateSince: '2026-06-07T16:00:00Z',
  },
  {
    id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
    typeId: '22222222-2222-2222-2222-222222222222',
    state: {
      id: '66666666-6666-6666-6666-666666666672',
      key: 'plenum_vote',
      label: { de: 'Abstimmung Plenum', en: 'Plenum vote' },
      color: '#9b59b6',
      editAllowed: false,
      kind: 'vote',
    },
    gremiumId: null,
    amount: '1200.00',
    currency: 'EUR',
    title: 'Förderung Sommerfest',
    createdAt: '2026-06-04T11:00:00Z',
    // No stateSince, as from a server before A9: the page falls back to updatedAt.
    updatedAt: '2026-06-08T09:30:00Z',
  },
];

/**
 * The status history of the demo application. The server names the applicant
 * `applicant` (the status page shows "Du") and a member by the Gremium (A12).
 */
const MOCK_TIMELINE: TimelineEventOutWire[] = [
  {
    fromStateId: null,
    toStateId: SUBMITTED_STATE.id,
    toState: SUBMITTED_STATE,
    transitionLabel: null,
    actor: 'applicant',
    actorInfo: { kind: 'applicant' },
    at: '2026-06-05T10:00:00Z',
    note: null,
  },
  {
    fromStateId: SUBMITTED_STATE.id,
    toStateId: REVIEW_STATE.id,
    toState: REVIEW_STATE,
    transitionLabel: { de: 'In Prüfung nehmen', en: 'Move to review' },
    actor: 'Finanzreferat',
    actorInfo: { kind: 'gremium', displayName: 'Finanzreferat' },
    at: '2026-06-05T12:30:00Z',
    note: 'Eingang bestätigt.',
  },
  {
    fromStateId: REVIEW_STATE.id,
    toStateId: SUBMITTED_STATE.id,
    toState: SUBMITTED_STATE,
    transitionLabel: { de: 'Zur Überarbeitung zurückgeben', en: 'Return for changes' },
    actor: 'Finanzreferat',
    actorInfo: { kind: 'gremium', displayName: 'Finanzreferat' },
    at: '2026-06-05T13:00:00Z',
    note: 'Bitte ergänze die Kostenaufstellung.',
  },
];

const MOCK_COMMENTS: CommentOutWire[] = [
  {
    id: 'c0000000-0000-0000-0000-000000000001',
    author: 'Finanzreferat',
    authorKind: 'principal',
    authorInfo: { kind: 'gremium', displayName: 'Finanzreferat' },
    body: 'Bitte ergänze die Kostenaufstellung.',
    visibility: 'public',
    at: '2026-06-05T13:00:00Z',
  },
  {
    id: 'c0000000-0000-0000-0000-000000000002',
    author: 'Haushaltsausschuss',
    authorKind: 'principal',
    authorInfo: { kind: 'gremium', displayName: 'Haushaltsausschuss' },
    body: 'Das zweite Angebot fehlt noch. Vor der Sitzung nachfragen.',
    visibility: 'internal',
    at: '2026-06-05T13:30:00Z',
  },
];

const MOCK_VERSIONS: VersionOutWire[] = [
  {
    version: 1,
    data: { title: 'Förderung Ersti-Wochenende', amount: '200.00' },
    diff: null,
    changedBy: 'applicant',
    changedByInfo: { kind: 'applicant' },
    at: '2026-06-05T10:00:00Z',
  },
  {
    version: 2,
    data: { title: 'Förderung Ersti-Wochenende 2026', amount: '250.00', note: 'Nachgereicht' },
    diff: {
      added: { note: 'Nachgereicht' },
      removed: {},
      changed: {
        title: { old: 'Förderung Ersti-Wochenende', new: 'Förderung Ersti-Wochenende 2026' },
        amount: { old: '200.00', new: '250.00' },
      },
    },
    changedBy: 'applicant',
    changedByInfo: { kind: 'applicant' },
    at: '2026-06-05T11:15:00Z',
  },
];

const MOCK_TRANSITIONS: TransitionOutWire[] = [
  {
    id: '77777777-7777-7777-7777-777777777771',
    fromStateId: SUBMITTED_STATE.id,
    toStateId: REVIEW_STATE.id,
    label: { de: 'In Prüfung nehmen', en: 'Move to review' },
  },
  {
    id: '77777777-7777-7777-7777-777777777772',
    fromStateId: SUBMITTED_STATE.id,
    toStateId: '66666666-6666-6666-6666-666666666664',
    label: { de: 'Ablehnen', en: 'Reject' },
  },
];

const LOGOUT_OUT = { logout_url: null };

// Meetings and protocol: mutable in-memory state.
const MOCK_MEETING_ID = 'd0000000-0000-0000-0000-000000000001';
const MOCK_PROTOCOL_ID = 'e0000000-0000-0000-0000-000000000099';

let MOCK_MEETING: MeetingOutWire = {
  id: MOCK_MEETING_ID,
  title: 'STUPA-Sitzung 12.06.',
  date: '2026-06-12',
  startTime: '18:00:00',
  status: 'live',
  activeApplicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  // The room handles the third item of the seeded agenda below.
  currentAgendaItemId: 'ag-s3',
  // The start page reads these (P5a): "seit 18:04", "Jetzt: TOP 3 · …", "3 / 6".
  startedAt: '2026-06-12T16:04:00Z',
  currentAgendaItem: { position: 3, title: 'Förderung Ersti-Wochenende' },
  agendaItemCount: 6,
  gremiumId: null,
  gremiumName: 'Studierendenparlament',
  protocolId: MOCK_PROTOCOL_ID,
  // The demo user keeps the minutes: an id of the roster below, so that the settings
  // dialog preselects the same person that the list row shows.
  protokollantId: MOCK_PRINCIPAL.sub,
  protokollantName: MOCK_PRINCIPAL.display_name,
  isProtokollant: true,
  canControl: true,
  // The demo user leads the meeting: the dialogs of the meeting page show.
  canManage: true,
  canWrite: true,
  canManageVotes: true,
  canFinalize: true,
  // The demo user holds `vote.cast` in the gremium of the meeting.
  canVote: true,
  // The demo user keeps the minutes since the start (Z3); a handover adds a period.
  keeperPeriods: [
    {
      principalId: MOCK_PRINCIPAL.sub,
      name: MOCK_PRINCIPAL.display_name ?? null,
      fromAt: '2026-06-12T16:04:00Z',
      toAt: null,
      fromAgendaItemId: 'ag-s1',
      toAgendaItemId: null,
      fromPosition: 1,
      toPosition: null,
    },
  ],
  plannedHandover: null,
  votes: [
    {
      id: 'a0000000-0000-0000-0000-0000000000a1',
      applicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      agendaItemId: 'ag-s3',
      title: 'Förderung Ersti-Wochenende',
      question: 'Soll der Antrag „Förderung Ersti-Wochenende“ wie beschrieben gefördert werden?',
      options: ['yes', 'no', 'abstain'],
      status: 'open',
      result: null,
      counts: { ja: 12, nein: 3, enthaltung: 1 },
      leading: 'ja',
      closesAt: null,
      // Not every present member voted yet, so the tally stays hidden.
      voted: 9,
      present: 12,
      revealed: false,
      majorityRule: 'simple',
      secret: false,
      quorum: { type: 'count', value: 8 },
      openedAt: '2026-06-12T16:48:00Z',
    },
    {
      id: 'a0000000-0000-0000-0000-0000000000a2',
      applicationId: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      agendaItemId: 'ag-s4',
      title: 'Anschaffung Beamer',
      question: 'Wird die Anschaffung des Beamers beschlossen?',
      majorityRule: 'absolute',
      secret: true,
      status: 'draft',
      result: null,
      counts: null,
      leading: null,
      closesAt: null,
    },
  ],
  createdAt: '2026-06-12T17:00:00Z',
};

/** A planned meeting beside the live one, for the start page and the meetings list. */
const MOCK_PLANNED_MEETING: MeetingOutWire = {
  id: 'd0000000-0000-0000-0000-000000000002',
  title: 'Haushaltsausschuss 19.06.',
  date: '2026-06-19',
  startTime: '17:30:00',
  status: 'planned',
  gremiumId: null,
  gremiumName: 'Haushaltsausschuss',
  votes: [],
  createdAt: '2026-06-01T10:00:00Z',
  // The demo user leads it and nobody keeps the minutes yet: the preparation shows.
  protocolId: null,
  protokollantId: null,
  protokollantName: null,
  canControl: true,
  canManage: true,
  canWrite: true,
  canManageVotes: true,
};

/** The agenda of the planned meeting. GET only: the mock changes the live agenda. */
const MOCK_PLANNED_AGENDA = [
  { id: 'ag-p1', applicationId: null, title: 'Begrüßung', body: '', position: 0 },
  { id: 'ag-p2', applicationId: null, title: 'Haushaltsplan 2027', body: '', position: 1 },
  { id: 'ag-p3', applicationId: null, title: 'Verschiedenes', body: '', position: 2 },
];

/**
 * GET /delegations: the user represents a member in the planned meeting, and in the live
 * meeting Vera Vertretung is represented by Sven Stellvertreter (the lead sees it and can revoke it).
 */
let MOCK_DELEGATIONS: Delegation[] = [
  {
    id: 'f0000000-0000-0000-0000-000000000001',
    meetingId: MOCK_PLANNED_MEETING.id,
    meetingTitle: MOCK_PLANNED_MEETING.title,
    meetingDate: MOCK_PLANNED_MEETING.date ?? null,
    gremiumId: 'g0000000-0000-0000-0000-000000000002',
    gremiumName: 'Haushaltsausschuss',
    delegatorId: 'p-3',
    delegatorName: 'Erika Beispiel',
    delegateId: 'me',
    delegateName: 'Demo-Nutzer:in',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-02T09:00:00Z',
    revocable: false,
    direction: 'incoming',
  },
  {
    id: 'f0000000-0000-0000-0000-000000000002',
    meetingId: MOCK_MEETING_ID,
    meetingTitle: 'STUPA-Sitzung 12.06.',
    meetingDate: '2026-06-12',
    gremiumId: 'g0000000-0000-0000-0000-000000000001',
    gremiumName: 'Studierendenparlament',
    delegatorId: 'p-6',
    delegatorName: 'Vera Vertretung',
    delegateId: 'p-7',
    delegateName: 'Sven Stellvertreter',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-06-10T09:00:00Z',
    revocable: true,
    direction: null,
  },
  // Two delegations of upcoming meetings for the admin overview: one with the vote, one
  // to a pool substitute.
  {
    id: 'f0000000-0000-0000-0000-000000000003',
    meetingId: 'd0000000-0000-0000-0000-000000000106',
    meetingTitle: '35. Sitzung des Studierendenparlaments',
    meetingDate: mockDay(14),
    gremiumId: 'g0000000-0000-0000-0000-000000000001',
    gremiumName: 'Studierendenparlament',
    delegatorId: 'p-8',
    delegatorName: 'Mika Muster',
    delegateId: 'p-9',
    delegateName: 'Charlie Probe',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-09-28T09:00:00Z',
    revocable: true,
    direction: null,
  },
  {
    id: 'f0000000-0000-0000-0000-000000000004',
    meetingId: 'd0000000-0000-0000-0000-000000000106',
    meetingTitle: '35. Sitzung des Studierendenparlaments',
    meetingDate: mockDay(14),
    gremiumId: 'g0000000-0000-0000-0000-000000000001',
    gremiumName: 'Studierendenparlament',
    delegatorId: 'p-10',
    delegatorName: 'Dana Demo',
    delegateId: 'p-12',
    delegateName: 'Fabi Fachschaft',
    delegateVoting: true,
    viaPool: true,
    createdAt: '2026-09-29T09:00:00Z',
    revocable: true,
    direction: null,
  },
];

/** GET /delegations/substitutes: the substitute pool of each Gremium. */
let MOCK_SUBSTITUTES = [
  {
    id: 'f1000000-0000-0000-0000-000000000001',
    gremiumId: 'g0000000-0000-0000-0000-000000000001',
    memberId: null as string | null,
    memberName: null as string | null,
    substituteId: 'p-12',
    substituteName: 'Fabi Fachschaft',
  },
  {
    id: 'f1000000-0000-0000-0000-000000000002',
    gremiumId: 'g0000000-0000-0000-0000-000000000001',
    memberId: 'p-8' as string | null,
    memberName: 'Mika Muster' as string | null,
    substituteId: 'p-3',
    substituteName: 'Sam Neu',
  },
];

/** The calendar subscription of the demo user: no link until "Abo-Link erzeugen". */
let MOCK_CALENDAR_URL: string | null = null;
let MOCK_CALENDAR_SEQ = 0;

/** The answer to `/delegations/substitutes` (GET, POST, DELETE), or null for another path. */
function mockSubstitutes(req: HttpRequest<unknown>, p: string): Observable<HttpEvent<unknown>> | null {
  const reply = <T>(body: T, status = 200) => of(new HttpResponse({ status, body })).pipe(delay(120));
  // GET /calendar/me and POST /calendar/me/rotate: the iCal feed of the demo user.
  if (req.method === 'GET' && p.endsWith('/calendar/me')) return reply({ url: MOCK_CALENDAR_URL });
  if (req.method === 'POST' && p.endsWith('/calendar/me/rotate')) {
    MOCK_CALENDAR_SEQ += 1;
    MOCK_CALENDAR_URL = `https://stupa.example/api/calendar/demo-feed-token-${MOCK_CALENDAR_SEQ}-7f3c9a2e5b8d41f0a6c2.ics`;
    return reply({ url: MOCK_CALENDAR_URL });
  }
  if (req.method === 'GET' && p.endsWith('/delegations/substitutes')) {
    const gremiumId = req.params.get('gremiumId');
    return reply(MOCK_SUBSTITUTES.filter((s) => s.gremiumId === gremiumId));
  }
  if (req.method === 'POST' && p.endsWith('/delegations/substitutes')) {
    const body = req.body as { gremiumId: string; memberId?: string | null; substituteId: string };
    const memberId = body.memberId ?? null;
    if (MOCK_SUBSTITUTES.some((s) => s.gremiumId === body.gremiumId && s.substituteId === body.substituteId && s.memberId === memberId)) {
      return mockProblem(409, 'substitute_exists', req.url);
    }
    const row = {
      id: `f1000000-0000-0000-0000-${String(MOCK_SUBSTITUTES.length + 100).padStart(12, '0')}`,
      gremiumId: body.gremiumId,
      memberId,
      memberName: memberId,
      substituteId: body.substituteId,
      substituteName: body.substituteId,
    };
    MOCK_SUBSTITUTES = [...MOCK_SUBSTITUTES, row];
    return reply(row, 201);
  }
  const del = /\/delegations\/substitutes\/([^/]+)$/.exec(p);
  if (req.method === 'DELETE' && del) {
    MOCK_SUBSTITUTES = MOCK_SUBSTITUTES.filter((s) => s.id !== del[1]);
    return reply(null, 204);
  }
  return null;
}

/** A local `YYYY-MM-DD` date, `days` away from today. */
function mockDay(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A meeting of the timeline, with the flags of a Gremium lead. */
function mockTimelineMeeting(
  n: number,
  days: number,
  title: string,
  status: MeetingOutWire['status'],
  extra: Partial<MeetingOutWire> = {},
): MeetingOutWire {
  const date = mockDay(days);
  return {
    id: `d0000000-0000-0000-0000-0000000001${String(n).padStart(2, '0')}`,
    title,
    status,
    date,
    startTime: '18:00:00',
    endTime: null,
    activeApplicationId: null,
    currentAgendaItemId: null,
    gremiumId: 'g0000000-0000-0000-0000-000000000001',
    gremiumName: 'Studierendenparlament',
    protocolId: status === 'planned' ? null : `e0000000-0000-0000-0000-0000000001${String(n).padStart(2, '0')}`,
    protokollantId: status === 'planned' ? null : MOCK_PRINCIPAL.sub,
    protokollantName: status === 'planned' ? null : MOCK_PRINCIPAL.display_name,
    canManage: true,
    canControl: true,
    canWrite: true,
    votes: [],
    createdAt: `${date}T08:00:00Z`,
    ...extra,
  };
}

/**
 * The meeting timeline of the mock: past meetings newest first, then the coming ones
 * in date order. The live demo meeting leads the coming ones.
 */
function mockTimeline(): { past: MeetingOutWire[]; upcoming: MeetingOutWire[] } {
  const past = [
    mockTimelineMeeting(1, -9, '33. Sitzung des Studierendenparlaments', 'closed', {
      startedAt: `${mockDay(-9)}T16:04:00Z`,
      closedAt: `${mockDay(-9)}T19:40:00Z`,
      agendaItemCount: 9,
    }),
    mockTimelineMeeting(2, -16, '11. Sitzung des Haushaltsausschusses', 'closed', {
      gremiumName: 'Haushaltsausschuss',
      gremiumId: 'g0000000-0000-0000-0000-000000000002',
      startedAt: `${mockDay(-16)}T15:32:00Z`,
      closedAt: `${mockDay(-16)}T17:05:00Z`,
      agendaItemCount: 5,
    }),
    mockTimelineMeeting(3, -30, '32. Sitzung des Studierendenparlaments', 'closed', {
      agendaItemCount: 7,
    }),
    mockTimelineMeeting(4, -44, '31. Sitzung des Studierendenparlaments', 'closed', {
      agendaItemCount: 6,
    }),
  ];
  // The live meeting runs today, so the overview and its calendar show it as "Jetzt".
  const live: MeetingOutWire = {
    ...MOCK_MEETING,
    date: mockDay(0),
    startTime: MOCK_MEETING.startTime ?? '18:00:00',
    startedAt: MOCK_MEETING.status === 'live' ? `${mockDay(0)}T16:04:00Z` : null,
    protokollantId: MOCK_MEETING.protokollantId ?? null,
    protokollantName: MOCK_MEETING.protokollantName ?? null,
    canManage: true,
  };
  const upcoming = [
    live,
    mockTimelineMeeting(5, 3, '12. Sitzung des Haushaltsausschusses', 'planned', {
      gremiumName: 'Haushaltsausschuss',
      gremiumId: 'g0000000-0000-0000-0000-000000000002',
      startTime: '17:30:00',
      endTime: '19:00:00',
      protokollantId: MOCK_PRINCIPAL.sub,
      protokollantName: MOCK_PRINCIPAL.display_name,
      canManage: false,
      canControl: false,
      canWrite: false,
      agendaItemCount: 4,
    }),
    mockTimelineMeeting(6, 14, '35. Sitzung des Studierendenparlaments', 'planned', {
      agendaItemCount: 6,
    }),
    mockTimelineMeeting(
      7,
      22,
      'Sondersitzung des Studierendenparlaments zur Haushaltsplanung mit allen Referatsleitungen',
      'planned',
      { startTime: '16:00:00', agendaItemCount: 1 },
    ),
    mockTimelineMeeting(8, 28, '36. Sitzung des Studierendenparlaments', 'planned'),
  ];
  return { past, upcoming };
}

interface MockAttendance {
  principalId: string;
  displayName: string | null;
  email: string | null;
  status: 'present' | 'excused' | 'absent' | null;
  source: 'self' | 'lead' | null;
  note: string | null;
  isSelf: boolean;
  /** O20: the member holds `protocol.write` and can keep the minutes. */
  canKeepProtocol: boolean;
  /** O6: the member has an own vote (`vote.cast`) and can be substituted. */
  canVote: boolean;
}

/** The roster of the mock Gremium. The demo user is in it with the id of the principal. */
let MOCK_ATTENDANCE: MockAttendance[] = [
  { principalId: MOCK_PRINCIPAL.sub, displayName: MOCK_PRINCIPAL.display_name ?? null, email: MOCK_PRINCIPAL.email ?? null, status: null, source: null, note: null, isSelf: true, canKeepProtocol: true, canVote: true },
  { principalId: 'p-2', displayName: 'Max Mustermann', email: 'max@example.com', status: 'present', source: 'lead', note: null, isSelf: false, canKeepProtocol: true, canVote: true },
  { principalId: 'p-3', displayName: 'Erika Beispiel', email: 'erika@example.com', status: 'excused', source: 'self', note: 'Prüfung', isSelf: false, canKeepProtocol: false, canVote: true },
  { principalId: 'p-4', displayName: 'Uli Übernahme', email: 'uli@example.com', status: 'present', source: 'self', note: null, isSelf: false, canKeepProtocol: true, canVote: true },
  { principalId: 'p-5', displayName: 'Rolf Redner', email: 'rolf@example.com', status: 'present', source: 'lead', note: null, isSelf: false, canKeepProtocol: true, canVote: true },
  // O23: Vera Vertretung has a delegation for the live meeting, so "present" gives 409.
  { principalId: 'p-6', displayName: 'Vera Vertretung', email: 'vera@example.com', status: 'excused', source: 'self', note: null, isSelf: false, canKeepProtocol: true, canVote: true },
  { principalId: 'p-7', displayName: 'Sven Stellvertreter', email: 'sven@example.com', status: 'present', source: 'self', note: null, isSelf: false, canKeepProtocol: false, canVote: true },
  { principalId: 'p-8', displayName: 'Fritz Fehlend', email: 'fritz@example.com', status: 'absent', source: 'lead', note: null, isSelf: false, canKeepProtocol: false, canVote: true },
  // Olga Offen is a member without a vote: the lead cannot enter a substitute for her.
  { principalId: 'p-9', displayName: 'Olga Offen', email: 'olga@example.com', status: null, source: null, note: null, isSelf: false, canKeepProtocol: false, canVote: false },
];

interface MockAgendaItem {
  id: string;
  applicationId: string | null;
  title: string | null;
  body?: string | null;
  position: number;
  nonPublic?: boolean;
  stateLabel?: Record<string, string> | null;
}

/** The agenda of the live meeting: freetext items, two applications and a non-public item. */
let MOCK_AGENDA: MockAgendaItem[] = [
  {
    id: 'ag-s1',
    applicationId: null,
    title: 'Begrüßung und Beschlussfähigkeit',
    body: 'Die Sitzungsleitung eröffnet die Sitzung. 12 von 15 Mitgliedern sind anwesend; das Gremium ist beschlussfähig.',
    position: 0,
  },
  {
    id: 'ag-s2',
    applicationId: null,
    title: 'Genehmigung der Tagesordnung',
    body: 'Die Tagesordnung wird ohne Änderungen genehmigt.',
    position: 1,
  },
  {
    id: 'ag-s3',
    applicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    title: 'Förderung Ersti-Wochenende',
    body: 'Die Antragstellerin stellt den Antrag vor.\n\n## Rückfragen\n\n- Unterkunft: Jugendherberge, Preis pro Person liegt vor.\n- Anreise: Bus, ein Angebot liegt bei.\n\nDie Sitzungsleitung stellt die Beschlussfrage zur Abstimmung.',
    position: 2,
    stateLabel: { de: 'Abstimmung', en: 'Vote' },
  },
  {
    id: 'ag-s4',
    applicationId: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    title: 'Anschaffung Beamer',
    body: '',
    position: 3,
    stateLabel: { de: 'Abstimmung', en: 'Vote' },
  },
  { id: 'ag-s5', applicationId: null, title: 'Personalangelegenheit', body: '', position: 4, nonPublic: true },
  { id: 'ag-s6', applicationId: null, title: 'Verschiedenes', body: '', position: 5 },
];
let MOCK_AGENDA_SEQ = 0;
const MOCK_ASSIGNABLE: { applicationId: string; title: string; stateLabel: Record<string, string> }[] = [
  { applicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', title: 'Förderung Ersti-Wochenende', stateLabel: { de: 'Abstimmung', en: 'Vote' } },
  { applicationId: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', title: 'Anschaffung Beamer', stateLabel: { de: 'Abstimmung', en: 'Vote' } },
];

let MOCK_PROTOCOL: ProtocolOutWire = {
  id: MOCK_PROTOCOL_ID,
  meetingId: MOCK_MEETING_ID,
  markdown:
    '# Protokoll der STUPA-Sitzung\n\n## TOP 1 — Begrüßung\n\nDie Sitzungsleitung eröffnet die Sitzung.\n\n- Anwesend: 16 Mitglieder\n- Beschlussfähig: **ja**\n',
  status: 'draft',
  pdfUrl: null,
  sentAt: null,
};

/** Set the status of a vote in the mock meeting. A close also emits a result. */
function setVoteStatus(voteId: string, status: 'open' | 'closed'): void {
  MOCK_MEETING = {
    ...MOCK_MEETING,
    votes: MOCK_MEETING.votes.map((v) =>
      v.id === voteId
        ? { ...v, status, result: status === 'closed' ? (v.leading ?? 'accepted') : v.result }
        : v,
    ),
  };
}

/**
 * GET /search: the mock applications, tasks and the meeting whose title holds the
 * query, in the shape of the real search (one flat hit per record, grouped by kind).
 */
function mockSearch(q: string): SearchResults {
  const needle = q.trim().toLowerCase();
  const hits: SearchHit[] = [];
  const apps = [
    ...MOCK_APPLICATIONS.items.map((a) => ({
      id: a.id,
      title: String(a.data['title'] ?? ''),
      state: a.state?.label['de'] ?? '',
    })),
    ...MOCK_TASKS.map((t) => ({ id: t.id, title: t.title ?? '', state: t.state?.label['de'] ?? '' })),
  ];
  for (const a of apps) {
    if (a.title.toLowerCase().includes(needle)) {
      hits.push({ kind: 'application', id: a.id, title: a.title, subtitle: a.state, url: `/applications/${a.id}` });
    }
  }
  if (MOCK_MEETING.title.toLowerCase().includes(needle)) {
    hits.push({
      kind: 'meeting',
      id: MOCK_MEETING.id,
      title: MOCK_MEETING.title,
      subtitle: MOCK_MEETING.gremiumName ?? null,
      url: `/meetings/${MOCK_MEETING.id}`,
    });
  }
  if ('demo mitglied'.includes(needle)) {
    hits.push({ kind: 'principal', id: MOCK_PRINCIPAL.sub, title: 'Demo Mitglied', subtitle: MOCK_PRINCIPAL.email ?? null, url: '/admin/users' });
  }
  return { hits, truncated: false, failed: [] };
}

/**
 * The closed demo meetings of `mock-meetings-closed.ts` (draft and final protocol), by
 * meeting id and by protocol id. The data itself loads on first use.
 */
/** The paths of `mock-meetings-member.ts`: the two meetings of the participant view, the
 *  agenda of the planned one, and the delegation context and recipients of any meeting. */
const MEMBER_MOCK_PATH =
  /\/meetings\/d0000000-0000-0000-0000-000000000(003|105)$|\/meetings\/d0000000-0000-0000-0000-000000000105\/agenda$|\/delegations\/meetings\/[^/]+\/(context|recipients)$/;
const CLOSED_MOCK_MEETING = /\/meetings\/(d0000000-0000-0000-0000-00000000010[12])(\/|$)/;
const CLOSED_MOCK_PROTOCOL = /\/protocols\/e0000000-0000-0000-0000-0000000001(0[12])(\/|$)/;

/** The id of the closed demo meeting a path belongs to, or `null`. */
function closedMockId(p: string): string | null {
  const meeting = CLOSED_MOCK_MEETING.exec(p);
  if (meeting) return meeting[1];
  const protocol = CLOSED_MOCK_PROTOCOL.exec(p);
  return protocol ? `d0000000-0000-0000-0000-0000000001${protocol[1]}` : null;
}

/** The 1-based number of an agenda item of the live mock meeting, or `null`. */
function mockPosition(itemId: string | null | undefined): number | null {
  const index = MOCK_AGENDA.findIndex((a) => a.id === itemId);
  return index >= 0 ? index + 1 : null;
}

/** A problem+json error of the mock with a stable `code`. */
function mockProblem(status: number, code: string, url: string): Observable<never> {
  return throwError(
    () => new HttpErrorResponse({ status, url, error: { status, code, detail: code } }),
  );
}

/**
 * POST /meetings/{id}/protokollant-handover of the live mock meeting (Z3, O1, O20): `now`
 * ends the running period and starts one for the new keeper; `next_item` plans it.
 */
function mockHandover(body: { principalId?: string; mode?: string } | null, url: string): Observable<HttpEvent<unknown>> | MeetingOutWire {
  const target = MOCK_ATTENDANCE.find((a) => a.principalId === body?.principalId);
  if (!target?.canKeepProtocol) return mockProblem(422, 'protokollant_needs_protocol_write', url);
  if (target.principalId === MOCK_MEETING.protokollantId) {
    return mockProblem(409, 'already_protokollant', url);
  }
  const current = MOCK_MEETING.currentAgendaItemId ?? null;
  const pos = mockPosition(current);
  const next: KeeperPeriod = {
    principalId: target.principalId,
    name: target.displayName,
    fromAt: null,
    toAt: null,
    fromAgendaItemId: null,
    toAgendaItemId: null,
    fromPosition: null,
    toPosition: null,
  };
  if (body?.mode === 'next_item') {
    if (pos === null || pos >= MOCK_AGENDA.length) return mockProblem(409, 'no_next_item', url);
    const nextItem = MOCK_AGENDA[pos];
    MOCK_MEETING = {
      ...MOCK_MEETING,
      plannedHandover: { ...next, fromAgendaItemId: nextItem.id, fromPosition: pos + 1 },
    };
    return MOCK_MEETING;
  }
  const now = new Date().toISOString();
  MOCK_MEETING = {
    ...MOCK_MEETING,
    keeperPeriods: [
      ...(MOCK_MEETING.keeperPeriods ?? []).map((p) =>
        p.toAt === null ? { ...p, toAt: now, toAgendaItemId: current, toPosition: pos } : p,
      ),
      { ...next, fromAt: now, fromAgendaItemId: current, fromPosition: pos },
    ],
    plannedHandover: null,
    protokollantId: target.principalId,
    protokollantName: target.displayName,
    isProtokollant: target.principalId === MOCK_PRINCIPAL.sub,
  };
  return MOCK_MEETING;
}

/** A forward move of the current item starts the planned handover (A13). */
function mockStartPlannedHandover(fromItem: string | null | undefined, toItem: string | null | undefined): void {
  const plan = MOCK_MEETING.plannedHandover;
  const from = mockPosition(fromItem) ?? 0;
  const to = mockPosition(toItem);
  if (!plan || to === null || to <= from) return;
  const now = new Date().toISOString();
  MOCK_MEETING = {
    ...MOCK_MEETING,
    keeperPeriods: [
      ...(MOCK_MEETING.keeperPeriods ?? []).map((p) =>
        p.toAt === null ? { ...p, toAt: now, toAgendaItemId: fromItem ?? null, toPosition: from || null } : p,
      ),
      { ...plan, fromAt: now, fromAgendaItemId: toItem ?? null, fromPosition: to },
    ],
    plannedHandover: null,
    protokollantId: plan.principalId,
    protokollantName: plan.name,
    isProtokollant: plan.principalId === MOCK_PRINCIPAL.sub,
  };
}

/** The paths of the demo applications in `mock-applications.ts` (id prefix `a1000000-`). */
const DEMO_APPLICATION_PATH =
  /\/applications\/a1000000-[^/]+(\/(transitions|attachments|shares|flow-states|form|timeline|versions|transition|archive|force-status))?$/;

/** The Gremium of the demo applications; its planned meetings serve the agenda dialog. */
const DEMO_GREMIUM = 'g0000000-0000-0000-0000-000000000001';

/** The budget routes the demo data in `mock-budget.ts` answers. */
const BUDGET_MOCK_PATH = /\/budgets(\/[^/]+\/(fiscal-years|applications))?$/;

/**
 * The answer to a GET on the bookings, transfers or invoices routes, or null for any other
 * route. The demo data in `mock-bookings.ts` loads on first use.
 */
function mockBookingsGet(p: string, params: URLSearchParams): Observable<unknown> | null {
  type Demo = typeof import('./mock-bookings');
  const load = (pick: (m: Demo) => unknown): Observable<unknown> =>
    from(import('./mock-bookings')).pipe(mergeMap((m) => of(pick(m))));
  if (p.endsWith('/expenses')) return load((m) => m.mockExpenses(params));
  const sub = /\/budget-expenses\/([^/]+)\/sub-bookings$/.exec(p);
  if (sub) return load((m) => m.mockSubBookings(sub[1]));
  if (p.endsWith('/budget-transfers')) return load((m) => m.mockTransfers(params));
  if (p.endsWith('/invoices')) return load((m) => m.mockInvoices(params));
  const one = /\/invoices\/([^/]+)$/.exec(p);
  if (one) return load((m) => m.mockInvoice(one[1]));
  return null;
}

/** The mock plays a visitor without a session (`localStorage['mockAnonymous'] = '1'`). */
function mockAnonymous(): boolean {
  try {
    return localStorage.getItem('mockAnonymous') === '1';
  } catch {
    return false;
  }
}

/**
 * The mock plays a person who just signed in for the first time
 * (`localStorage['mockNewUser'] = '1'`): no gremium, no task, no own application, no
 * vote, no meeting. For the empty states of the start page.
 */
function mockNewUser(): boolean {
  try {
    return localStorage.getItem('mockNewUser') === '1';
  } catch {
    return false;
  }
}

/** The session of the new person: the global role "Mitglied" and nothing else. */
const MOCK_NEW_USER: Principal = {
  sub: '00000000-0000-0000-0000-000000000099',
  display_name: 'Jana Roth',
  email: 'jana.roth@stupa.example',
  roles: ['member'],
  permissions: ['application.read'],
  groups: [],
  gremien: [],
};

/** The answers of the start page for the new person, or undefined for other requests. */
export function mockNewUserGet(p: string): unknown {
  if (p.endsWith('/auth/me')) return MOCK_NEW_USER;
  if (p.endsWith('/applications/tasks') || p.endsWith('/delegations')) return [];
  if (/(^|\/)api\/(applications|votes)$/.test(p)) return { items: [], total: 0, limit: 25, offset: 0 };
  if (p.endsWith('/meetings/timeline')) return { items: [], nextCursor: null };
  return undefined;
}

let MOCK_DRAFT_SEQ = 0;

/** The answer to a draft upload: a new id, the name and size of the sent file. */
function mockDraftUpload(body: unknown): DraftAttachmentOutWire {
  const form = body instanceof FormData ? body : null;
  const file = form?.get('file');
  const n = ++MOCK_DRAFT_SEQ;
  return {
    id: `d0000000-0000-0000-0000-${String(n).padStart(12, '0')}`,
    filename: file instanceof File ? file.name : `datei-${n}.pdf`,
    mime: file instanceof File && file.type ? file.type : 'application/pdf',
    size: file instanceof File ? file.size : 1024,
    scanned: false,
    is_comparison_offer: form?.get('is_comparison_offer') === 'true',
    draftToken: 'mock-draft-token',
    draftExpiresAt: new Date(Date.now() + 7 * 86_400_000).toISOString(),
  };
}

/** The paths of the account pages and the consent page (`mock-account.ts`). */
const MOCK_ACCOUNT_PATH =
  /(^|\/)api\/(notifications\/preferences|oauth\/grants(\/[^/]+)?|oauth\/consent(-request)?|mcp\/(config|package))$/;

function path(url: string): string {
  return url.split('?')[0];
}

export const mockApiInterceptor: HttpInterceptorFn = (req, next) => {
  // Security: defense in depth. The mock may take effect only in the dev or
  // demo build. In prod `isDevMode()` returns false. Even if the interceptor
  // reaches the chain there, no attacker-controlled input (?mock=1,
  // localStorage, __USE_MOCK_API__) can activate it.
  if (!isDevMode()) return next(req);
  if (!inject(USE_MOCK_API)) return next(req);
  if (!req.url.includes('/api/')) return next(req);

  const p = path(req.url);
  const ok = <T>(body: T, status = 200): Observable<HttpEvent<unknown>> =>
    of(new HttpResponse({ status, body })).pipe(delay(120));

  if (req.method === 'GET' && mockNewUser()) {
    const body = mockNewUserGet(p);
    if (body !== undefined) return ok(body);
  }

  const substitutes = mockSubstitutes(req, p);
  if (substitutes) return substitutes;

  // The account pages and the consent page. The data loads on first use.
  if (MOCK_ACCOUNT_PATH.test(p)) {
    return from(import('./mock-account')).pipe(
      mergeMap((m) => {
        const reply = m.mockAccount(req.method, p, req.body);
        if (!reply) return throwError(() => new HttpErrorResponse({ status: 404, url: req.url }));
        return ok(reply.body, reply.status);
      }),
    );
  }

  // #11: the applicant search and the capture of "Antrag erfassen".
  if (req.method === 'GET' && p.endsWith('/applications/on-behalf/applicants')) {
    return from(import('./mock-applications')).pipe(
      mergeMap((m) => ok(m.mockApplicantSearch(req.params.get('q') ?? ''))),
    );
  }
  if (req.method === 'POST' && p.endsWith('/applications/on-behalf')) {
    return from(import('./mock-applications')).pipe(
      mergeMap((m) => ok(m.mockCapture(req.body as OnBehalfApplication), 201)),
    );
  }

  // The demo applications of the list page and their detail paths. The demo data loads
  // on first use, so it stays out of the initial bundle.
  if (
    (req.method === 'GET' && /(^|\/)api\/applications$/.test(p)) ||
    DEMO_APPLICATION_PATH.test(p)
  ) {
    return from(import('./mock-applications')).pipe(
      mergeMap((m) => {
        const body =
          req.method === 'GET'
            ? m.mockApplicationsGet(p, req.params)
            : m.mockApplicationsWrite(req.method, p, req.body);
        if (body === undefined) {
          return throwError(() => new HttpErrorResponse({ status: 404, url: req.url }));
        }
        if (m.isMockFailure(body)) {
          return throwError(
            () => new HttpErrorResponse({ status: body.status, error: body.problem, url: req.url }),
          );
        }
        return ok(body, req.method === 'DELETE' ? 204 : 200);
      }),
    );
  }
  // The agenda dialog of a demo application asks for the meetings of its Gremium.
  if (
    req.method === 'GET' &&
    p.endsWith('/meetings') &&
    req.params.get('gremiumId') === DEMO_GREMIUM
  ) {
    return from(import('./mock-applications')).pipe(mergeMap((m) => ok(m.agendaMeetings())));
  }

  // The participant view: two meetings where the demo user is a plain member, and the
  // delegation context of every meeting. The data loads on first use.
  if (req.method === 'GET' && MEMBER_MOCK_PATH.test(p)) {
    return from(import('./mock-meetings-member')).pipe(
      mergeMap((m) =>
        ok(
          m.memberMeetingGet(
            p,
            req.params.get('q') ?? '',
            MOCK_MEETING,
            MOCK_DELEGATIONS,
            req.params.get('delegatorId'),
          ),
        ),
      ),
    );
  }

  // The closed demo meetings (draft and final protocol). The data loads on first use.
  const closedId = closedMockId(p);
  if (closedId && !/\/(attendance|delegations)/.test(p)) {
    return from(import('./mock-meetings-closed')).pipe(
      mergeMap((m) => {
        const body =
          req.method === 'GET'
            ? m.closedMeetingGet(closedId, p)
            : m.closedMeetingWrite(closedId, req.method, p, req.body);
        if (body === undefined) return mockProblem(409, 'meeting_closed', req.url);
        return ok(body);
      }),
    );
  }

  // The vote list and the standalone demo votes. The data loads on first use.
  if (req.method === 'GET' && (/(^|\/)api\/votes$/.test(p) || DEMO_VOTE_PATH.test(p))) {
    return from(import('./mock-votes')).pipe(
      mergeMap((m) => {
        if (DEMO_VOTE_PATH.test(p)) {
          const id = p.split('/').pop() ?? '';
          const found = m.demoVote(id, mockOwnBallot(id));
          if (!found) return throwError(() => new HttpErrorResponse({ status: 404, url: req.url }));
          return ok(found);
        }
        const params = new URLSearchParams(req.params.toString());
        return ok(
          m.mockVoteList(params, mockVote(MOCK_VOTE.id), mockVote('a0000000-0000-0000-0000-000000000101'), mockOwnBallot),
        );
      }),
    );
  }

  if (req.method === 'GET') {
    // The public site config: the platform defaults (links without an end, the default
    // limits), so the pages show what they show after a real load.
    if (/(^|\/)api\/site-config$/.test(p)) {
      const config: PublicSiteConfig = {
        version: 1,
        confirmTtlHours: 12,
        linkTtlDays: null,
        attachmentLimits: null,
        branding: null,
      };
      return ok(config);
    }
    // `localStorage['mockAnonymous'] = '1'` plays a visitor without a session: the
    // public frame, the wizard with the contact step and the ALTCHA.
    if (p.endsWith('/auth/me')) {
      return mockAnonymous()
        ? throwError(() => new HttpErrorResponse({ status: 401, url: req.url }))
        : ok(MOCK_PRINCIPAL);
    }
    // The wizard of the demo type gets the form of the demo applications.
    if (p.endsWith(`/application-types/${MOCK_TYPES.items[0].id}/form`)) {
      return from(import('./mock-applications')).pipe(mergeMap((m) => ok(m.demoForm())));
    }
    // ALTCHA is off in mock mode → 404. The widget then reports "unavailable".
    if (p.endsWith('/altcha/challenge')) {
      return throwError(() => new HttpErrorResponse({ status: 404, url: req.url }));
    }
    if (p.endsWith(`/application-types/${MOCK_TYPES.items[2].id}/form`)) return ok(MOCK_QSM_FORM);
    if (/\/application-types\/[^/]+\/form$/.test(p)) return ok(MOCK_EFFECTIVE_FORM);
    if (p.endsWith('/application-types')) return ok(MOCK_TYPES);
    // Match the meeting timeline BEFORE the generic `/timeline` rule. The
    // generic rule otherwise captures `/meetings/timeline` and returns
    // application status events instead of a MeetingPage.
    if (p.endsWith('/meetings/timeline')) {
      // Keyset paging as an offset in the cursor; `q` collapses both directions into
      // one list of hits.
      const { past, upcoming } = mockTimeline();
      const q = (req.params.get('q') ?? '').trim().toLowerCase();
      const gremiumId = req.params.get('gremiumId');
      const direction = req.params.get('direction') ?? 'upcoming';
      let rows = q
        ? [...upcoming, ...past].filter((m) => m.title.toLowerCase().includes(q))
        : direction === 'upcoming'
          ? upcoming
          : past;
      if (gremiumId) rows = rows.filter((m) => m.gremiumId === gremiumId);
      const offset = Number(req.params.get('cursor') ?? '0') || 0;
      const limit = Number(req.params.get('limit') ?? '15') || 15;
      const page: MeetingPageWire = {
        items: rows.slice(offset, offset + limit),
        nextCursor: offset + limit < rows.length ? String(offset + limit) : null,
      };
      return ok(page);
    }
    if (p.endsWith('/meetings/gremien')) {
      return ok([
        { id: 'g0000000-0000-0000-0000-000000000001', name: 'Studierendenparlament' },
        { id: 'g0000000-0000-0000-0000-000000000002', name: 'Haushaltsausschuss' },
      ]);
    }
    if (/\/gremien\/[^/]+\/meeting-members$/.test(p)) {
      return ok(
        MOCK_ATTENDANCE.map((a) => ({
          principalId: a.principalId,
          displayName: a.displayName,
          email: a.email,
          canKeepProtocol: a.canKeepProtocol,
        })),
      );
    }
    if (p.endsWith(`/applications/${MOCK_APP_ID}/attachments`)) return ok([...MOCK_APP_ATTACHMENTS]);
    if (p.endsWith('/timeline')) return ok(MOCK_TIMELINE);
    if (p.endsWith('/versions')) return ok([...MOCK_VERSIONS]);
    if (p.endsWith('/comments')) return ok([...MOCK_COMMENTS]);
    if (p.endsWith('/transitions')) return ok([...MOCK_TRANSITIONS]);
    if (/\/attachments\/[^/]+$/.test(p)) {
      const signed: SignedUrlOutWire = {
        url: 'https://minio.example/mock-attachment?sig=demo',
        expiresIn: 120,
      };
      return ok(signed);
    }
    // The budget tree, its fiscal years and the applications per cost centre. Before the
    // generic `/applications` rule, which would otherwise answer `/budgets/{id}/applications`.
    // The demo data loads on first use, so it stays out of the initial bundle.
    if (BUDGET_MOCK_PATH.test(p)) {
      const fiscalYear = req.params.get('fiscalYear');
      return from(import('./mock-budget')).pipe(
        mergeMap((m) => ok(m.mockBudgetGet(p, fiscalYear))),
      );
    }
    // Bookings, transfers and invoices. The demo data loads on first use, like the
    // budget tree.
    const bookings = mockBookingsGet(p, new URLSearchParams(req.params.toString()));
    if (bookings) return bookings.pipe(mergeMap((body) => ok(body)));
    if (p.endsWith('/search')) return ok(mockSearch(req.params.get('q') ?? ''));
    if (p.endsWith('/applications/tasks')) return ok([...MOCK_TASKS]);
    // The demo user represents a member in the demo vote: the ballot shows both rows.
    if (/\/delegations\/votes\/[^/]+\/status$/.test(p)) {
      return ok({ blocked: false, delegatedToName: null, exercising: true, delegatedByName: 'Erika Beispiel' });
    }
    if (/\/votes\/[^/]+$/.test(p)) return ok(mockVote(p.split('/').pop() ?? MOCK_VOTE.id));
    // The calendar view asks for the meetings of the days of its month grid.
    const dateFrom = req.params.get('dateFrom');
    const dateTo = req.params.get('dateTo');
    if (p.endsWith('/meetings') && dateFrom && dateTo) {
      const { past, upcoming } = mockTimeline();
      const gremiumId = req.params.get('gremiumId');
      return ok(
        [...past, ...upcoming].filter(
          (m) =>
            !!m.date &&
            m.date >= dateFrom &&
            m.date <= dateTo &&
            (!gremiumId || m.gremiumId === gremiumId),
        ),
      );
    }
    if (p.endsWith('/meetings')) return ok([MOCK_MEETING, MOCK_PLANNED_MEETING]);
    if (p.endsWith('/delegations')) {
      const meetingId = req.params.get('meetingId');
      return ok(MOCK_DELEGATIONS.filter((d) => !meetingId || d.meetingId === meetingId));
    }
    if (/\/meetings\/[^/]+\/attendance$/.test(p)) return ok([...MOCK_ATTENDANCE]);
    if (/\/meetings\/[^/]+\/agenda\/assignable$/.test(p)) {
      const taken = new Set(MOCK_AGENDA.map((a) => a.applicationId));
      return ok(MOCK_ASSIGNABLE.filter((a) => !taken.has(a.applicationId)));
    }
    if (p.endsWith(`/meetings/${MOCK_PLANNED_MEETING.id}/agenda`)) return ok([...MOCK_PLANNED_AGENDA]);
    if (/\/meetings\/[^/]+\/agenda$/.test(p)) return ok([...MOCK_AGENDA]);
    if (/\/meetings\/[^/]+\/protocol$/.test(p)) return ok(MOCK_PROTOCOL);
    if (p.endsWith(`/meetings/${MOCK_PLANNED_MEETING.id}`)) return ok(MOCK_PLANNED_MEETING);
    if (/\/meetings\/[^/]+$/.test(p)) return ok(MOCK_MEETING);
    if (/\/applications\/[^/]+\/form$/.test(p)) return ok(MOCK_EFFECTIVE_FORM);
    if (/\/applications\/[^/]+$/.test(p)) return ok(mockApplication());
  }

  if (req.method === 'PUT') {
    if (/\/meetings\/[^/]+\/agenda\/order$/.test(p)) {
      const ids = (req.body as { itemIds?: string[] } | null)?.itemIds ?? [];
      const byId = new Map(MOCK_AGENDA.map((a) => [a.id, a]));
      MOCK_AGENDA = ids.map((id, i) => ({ ...(byId.get(id) as MockAgendaItem), position: i }));
      return ok([...MOCK_AGENDA]);
    }
    const att = /\/meetings\/[^/]+\/attendance\/([^/]+)$/.exec(p);
    if (att) {
      const body = (req.body as { status?: string; note?: string | null } | null) ?? {};
      const status = (body.status ?? 'present') as MockAttendance['status'];
      const target = att[1];
      // O23: a member with a delegation of this meeting cannot be present.
      const meetingId = /\/meetings\/([^/]+)\//.exec(p)?.[1];
      const delegator = target === 'me' ? MOCK_PRINCIPAL.sub : target;
      const delegated = MOCK_DELEGATIONS.some(
        (d) => d.meetingId === meetingId && d.delegatorId === delegator,
      );
      if (status === 'present' && delegated) return mockProblem(409, 'delegation_active', req.url);
      // Like the server: only an excuse keeps a reason; an omitted note keeps the stored one.
      const noteFor = (a: MockAttendance): string | null =>
        status !== 'excused' ? null : body.note !== undefined ? body.note : a.note;
      MOCK_ATTENDANCE = MOCK_ATTENDANCE.map((a) =>
        a.isSelf && target === 'me'
          ? { ...a, status, source: 'self', note: noteFor(a) }
          : a.principalId === target
            ? { ...a, status, source: 'lead', note: noteFor(a) }
            : a,
      );
      return ok([...MOCK_ATTENDANCE]);
    }
  }

  if (req.method === 'POST') {
    if (p.endsWith('/delegations')) {
      return from(import('./mock-meetings-member')).pipe(
        mergeMap((m) => {
          const made = m.memberDelegationCreate(req.body, MOCK_DELEGATIONS.length, MOCK_ATTENDANCE);
          MOCK_DELEGATIONS = [...MOCK_DELEGATIONS, made];
          return ok(made, 201);
        }),
      );
    }
    if (p.endsWith('/auth/logout')) return ok(LOGOUT_OUT);
    // A draft upload of the wizard (Z4): the file stays in the scan, the token stays.
    if (p.endsWith('/apply/attachments')) return ok(mockDraftUpload(req.body), 201);
    if (p.endsWith('/invoices/parse')) {
      const file = req.body instanceof FormData ? req.body.get('file') : null;
      const name = file instanceof File ? file.name : 'rechnung.pdf';
      return from(import('./mock-bookings')).pipe(mergeMap((m) => ok(m.mockParseInvoice(name))));
    }
    if (/\/meetings\/[^/]+\/protokollant-handover$/.test(p)) {
      const out = mockHandover(req.body as { principalId?: string; mode?: string } | null, req.url);
      return 'id' in out ? ok(out) : out;
    }
    if (/\/meetings\/[^/]+\/votes$/.test(p)) {
      const body = req.body as { applicationId?: string; question?: string | null } | null;
      MOCK_MEETING = {
        ...MOCK_MEETING,
        votes: [
          ...MOCK_MEETING.votes,
          {
            id: `v-mock-${MOCK_MEETING.votes.length + 1}`,
            applicationId: body?.applicationId ?? '',
            title: null,
            question: body?.question ?? null,
            status: 'open',
            result: null,
            counts: null,
            leading: null,
            closesAt: null,
          },
        ],
      };
      return ok(MOCK_MEETING);
    }
    if (/\/meetings\/[^/]+\/agenda$/.test(p)) {
      const body = req.body as { applicationId?: string; title?: string; nonPublic?: boolean } | null;
      const appId = body?.applicationId;
      const freetext = body?.title;
      const nonPublic = body?.nonPublic === true;
      if (freetext) {
        MOCK_AGENDA = [
          ...MOCK_AGENDA,
          { id: `ag-${++MOCK_AGENDA_SEQ}`, applicationId: null, title: freetext, position: MOCK_AGENDA.length, nonPublic },
        ];
      } else if (appId && !MOCK_AGENDA.some((a) => a.applicationId === appId)) {
        const src = MOCK_ASSIGNABLE.find((a) => a.applicationId === appId);
        MOCK_AGENDA = [
          ...MOCK_AGENDA,
          { id: `ag-${++MOCK_AGENDA_SEQ}`, applicationId: appId, title: src?.title ?? null, position: MOCK_AGENDA.length, stateLabel: src?.stateLabel ?? null, nonPublic },
        ];
      }
      return ok([...MOCK_AGENDA]);
    }
    if (p.endsWith('/auth/magic-link/verify')) {
      // Cookie model: the real server sets an HttpOnly applicant cookie. The
      // mock returns only the scope and the application id, no session token.
      const res: MagicLinkVerifyResult = { application_id: MOCK_APP_ID, scope: 'edit' };
      return ok(res);
    }
    if (p.endsWith('/comments')) {
      const body = (req.body as { body?: string } | null)?.body ?? '';
      const visibility = (req.body as { visibility?: 'internal' | 'public' } | null)?.visibility;
      const created: CommentOutWire = {
        id: `c0000000-0000-0000-0000-0000000000${MOCK_COMMENTS.length + 1}`,
        author: null,
        authorKind: 'applicant',
        body,
        visibility: visibility ?? 'public',
        at: '2026-06-05T14:00:00Z',
        isOwn: true, // the mock viewer created it
      };
      MOCK_COMMENTS.push(created);
      return ok(created, 201);
    }
    if (p.endsWith('/attachments')) {
      // Multipart upload: the real server scans asynchronously → `scanned=false`.
      const created: AttachmentOutWire = {
        id: 'att00000-0000-0000-0000-000000000001',
        filename: 'mock-upload.pdf',
        mime: 'application/pdf',
        size: 12345,
        scanned: false,
        is_comparison_offer: false,
      };
      return ok(created, 201);
    }
    if (p.endsWith('/transition')) {
      const transitionId =
        (req.body as { transitionId?: string } | null)?.transitionId ?? MOCK_TRANSITIONS[0].id;
      const target = MOCK_TRANSITIONS.find((t) => t.id === transitionId) ?? MOCK_TRANSITIONS[0];
      const result: TransitionResult = {
        newStateId: target.toStateId,
        statusEventId: 'e0000000-0000-0000-0000-000000000001',
        dispatchedActions: [],
      };
      return ok(result);
    }
    if (p.endsWith('/applications')) {
      const created: ApplicationCreatedWire = { applicationId: MOCK_APP_ID };
      return ok(created, 201);
    }
    if (/\/votes\/[^/]+\/ballot$/.test(p)) {
      const res = mockBallot(p.split('/').slice(-2)[0], req.body, req.url);
      return 'status' in res ? ok(res, 201) : res;
    }
    if (p.endsWith('/finalize')) {
      MOCK_PROTOCOL = {
        ...MOCK_PROTOCOL,
        status: 'final',
        pdfUrl: 'https://files.example/s/protokoll-12-06.pdf',
        sentAt: '2026-06-12T19:30:00Z',
      };
      return ok(MOCK_PROTOCOL);
    }
    if (/\/protocols\/[^/]+\/votes$/.test(p)) return ok(MOCK_PROTOCOL);
    if (/\/votes\/[^/]+\/open$/.test(p)) {
      setVoteStatus(p.split('/').slice(-2)[0], 'open');
      return ok(null, 204);
    }
    if (/\/votes\/[^/]+\/close$/.test(p)) {
      setVoteStatus(p.split('/').slice(-2)[0], 'closed');
      return ok(null, 204);
    }
    if (/\/meetings\/[^/]+\/protocol$/.test(p)) return ok(MOCK_PROTOCOL);
    if (p.endsWith('/meetings')) {
      const body = (req.body as { title?: string; date?: string | null; startTime?: string | null } | null) ?? {};
      const title = body.title?.trim();
      // The backend creates a new meeting with status `planned`.
      MOCK_MEETING = {
        ...MOCK_MEETING,
        title: title || MOCK_MEETING.title,
        date: body.date ?? null,
        startTime: body.startTime ?? null,
        status: 'planned',
      };
      return ok(MOCK_MEETING, 201);
    }
  }

  if (req.method === 'PATCH' && /\/applications\/[^/]+$/.test(p)) {
    const data = (req.body as { data?: Record<string, unknown> } | null)?.data ?? {};
    return ok(mockApplication(data));
  }

  if (req.method === 'PATCH' && /\/meetings\/[^/]+$/.test(p)) {
    const body = (req.body as { status?: MeetingOutWire['status']; activeApplicationId?: string; currentAgendaItemId?: string | null; date?: string | null; startTime?: string | null; endTime?: string | null; protokollantId?: string | null } | null) ?? {};
    if (body.currentAgendaItemId !== undefined) {
      mockStartPlannedHandover(MOCK_MEETING.currentAgendaItemId, body.currentAgendaItemId);
    }
    MOCK_MEETING = {
      ...MOCK_MEETING,
      status: body.status ?? MOCK_MEETING.status,
      activeApplicationId:
        body.activeApplicationId !== undefined
          ? body.activeApplicationId
          : MOCK_MEETING.activeApplicationId,
      currentAgendaItemId:
        body.currentAgendaItemId !== undefined
          ? body.currentAgendaItemId
          : MOCK_MEETING.currentAgendaItemId,
      date: body.date !== undefined ? body.date : MOCK_MEETING.date,
      startTime: body.startTime !== undefined ? body.startTime : MOCK_MEETING.startTime,
      endTime: body.endTime !== undefined ? body.endTime : MOCK_MEETING.endTime,
      protokollantId:
        body.protokollantId !== undefined ? body.protokollantId : MOCK_MEETING.protokollantId,
      protokollantName:
        body.protokollantId !== undefined
          ? (MOCK_ATTENDANCE.find((a) => a.principalId === body.protokollantId)?.displayName ?? null)
          : MOCK_MEETING.protokollantName,
      isProtokollant:
        body.protokollantId !== undefined
          ? body.protokollantId === MOCK_PRINCIPAL.sub
          : MOCK_MEETING.isProtokollant,
      closedAt: body.status === 'closed' ? new Date().toISOString() : MOCK_MEETING.closedAt,
    };
    return ok(MOCK_MEETING);
  }

  if (req.method === 'PATCH') {
    const item = /\/meetings\/[^/]+\/agenda\/([^/]+)$/.exec(p);
    if (item) {
      // Like the server: only the sent fields change (text, title of a freetext item, NÖ).
      const patch = (req.body as { body?: string; title?: string; nonPublic?: boolean } | null) ?? {};
      MOCK_AGENDA = MOCK_AGENDA.map((a) => (a.id === item[1] ? { ...a, ...patch } : a));
      return ok([...MOCK_AGENDA]);
    }
  }

  if (req.method === 'PATCH' && /\/protocols\/[^/]+$/.test(p)) {
    const markdown = (req.body as { markdown?: string } | null)?.markdown ?? MOCK_PROTOCOL.markdown;
    MOCK_PROTOCOL = { ...MOCK_PROTOCOL, markdown };
    return ok(MOCK_PROTOCOL);
  }

  if (req.method === 'DELETE') {
    if (/\/apply\/attachments\/[^/]+$/.test(p)) return ok(null, 204);
    if (/\/meetings\/[^/]+\/protokollant-handover$/.test(p)) {
      if (!MOCK_MEETING.plannedHandover) return mockProblem(404, 'no_planned_handover', req.url);
      MOCK_MEETING = { ...MOCK_MEETING, plannedHandover: null };
      return ok(MOCK_MEETING);
    }
    const delegation = /\/delegations\/([^/]+)$/.exec(p);
    if (delegation) {
      MOCK_DELEGATIONS = MOCK_DELEGATIONS.filter((d) => d.id !== delegation[1]);
      return ok(null, 204);
    }
    const agenda = /\/meetings\/[^/]+\/agenda\/([^/]+)$/.exec(p);
    if (agenda) {
      MOCK_AGENDA = MOCK_AGENDA.filter((a) => a.id !== agenda[1]);
      return ok([...MOCK_AGENDA]);
    }
    const att = /\/meetings\/[^/]+\/attendance\/([^/]+)$/.exec(p);
    if (att) {
      MOCK_ATTENDANCE = MOCK_ATTENDANCE.map((a) =>
        a.principalId === att[1] ? { ...a, status: null, source: null, note: null } : a,
      );
      return ok([...MOCK_ATTENDANCE]);
    }
  }

  return next(req);
};
