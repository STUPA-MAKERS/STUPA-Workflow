import {
  type HttpEvent,
  HttpErrorResponse,
  type HttpInterceptorFn,
  HttpResponse,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { type Observable, of, throwError } from 'rxjs';
import { delay } from 'rxjs/operators';
import { USE_MOCK_API } from './api.config';
import type {
  ApplicationCreatedWire,
  ApplicationListItemWire,
  ApplicationOutWire,
  ApplicationTypeListItemWire,
  AttachmentOutWire,
  BallotResult,
  BudgetPotOutWire,
  BudgetStatsOutWire,
  CommentOutWire,
  EffectiveForm,
  MagicLinkVerifyResult,
  MeetingOutWire,
  Page,
  Principal,
  ProtocolOutWire,
  SignedUrlOutWire,
  StateOutWire,
  TimelineEventOutWire,
  TransitionOutWire,
  TransitionResult,
  VersionOutWire,
  Vote,
} from './models';

/**
 * In-Memory-Mock-Backend für den Skelett-/FE-Betrieb (Mock erlaubt, T-03/T-30).
 * Aktiv nur wenn `USE_MOCK_API` true ist; greift ausschließlich für `/api/*`.
 *
 * Die Antworten sind in der **Backend-Wire-Form** (`*Wire`, camelCase via T-12
 * `_CamelModel`) — der `ApiClient` mappt sie wie beim echten Backend. So bleibt
 * der Mock contract-treu und die Mapper-Schicht wird mitgetestet (Issue #17).
 */
const MOCK_PRINCIPAL: Principal = {
  sub: '00000000-0000-0000-0000-000000000001',
  display_name: 'Demo Mitglied',
  email: 'demo@stupa.example',
  roles: ['member'],
  // application.manage (T-31) für RBAC-Aktionen auf der Detail-Seite;
  // vote.manage/meeting.manage (T-32) für Beamer-/Manage-Ansichten;
  // protocol.write (T-33) für den Protokoll-Editor;
  // admin.config/form.configure/flow.configure/webhook.manage/notification.manage
  // (T-34) für die Verwaltungs-UIs — alle im Mock gesetzt, damit der FE-Dev/
  // Harness-/Demo-Betrieb die gegateten Ansichten zeigt.
  permissions: [
    'application.read',
    'application.manage',
    'vote.cast',
    'vote.manage',
    'meeting.manage',
    'protocol.write',
    'admin.config',
    'admin.roles',
    'form.configure',
    'flow.configure',
    'webhook.manage',
    'notification.manage',
    // budget.view/budget.manage (T-17/T-35) für das Budget-Statistik-Dashboard.
    'budget.view',
    'budget.manage',
  ],
  groups: [],
  gremien: [
    { id: 'g0000000-0000-0000-0000-000000000001', name: 'Studierendenparlament', slug: 'stupa' },
    { id: 'g0000000-0000-0000-0000-000000000002', name: 'Haushaltsausschuss', slug: 'haushalt' },
  ],
};

// --- Budget (T-17/T-35) — Töpfe + Rollup-Statistik -------------------------- //
const MOCK_GREMIUM_ID = 'b0000000-0000-0000-0000-00000000c001';

const MOCK_BUDGET_POTS: BudgetPotOutWire[] = [
  {
    id: 'b0000000-0000-0000-0000-0000000000a1',
    gremiumId: MOCK_GREMIUM_ID,
    name: 'Veranstaltungen',
    total: '10000.00',
    currency: 'EUR',
    period: '2026',
    active: true,
  },
  {
    id: 'b0000000-0000-0000-0000-0000000000a2',
    gremiumId: MOCK_GREMIUM_ID,
    name: 'Anschaffungen',
    total: '5000.00',
    currency: 'EUR',
    period: '2026',
    active: true,
  },
  {
    id: 'b0000000-0000-0000-0000-0000000000a3',
    gremiumId: MOCK_GREMIUM_ID,
    name: 'Härtefonds',
    total: null,
    currency: 'EUR',
    period: '2026',
    active: true,
  },
];

const MOCK_BUDGET_STATS: BudgetStatsOutWire = {
  pots: [
    {
      budgetPotId: MOCK_BUDGET_POTS[0].id,
      period: '2026',
      total: '10000.00',
      currency: 'EUR',
      requested: '4200.00',
      reserved: '1500.00',
      approved: '3000.00',
      paid: '2000.00',
      committed: '6500.00',
      available: '3500.00',
    },
    {
      budgetPotId: MOCK_BUDGET_POTS[1].id,
      period: '2026',
      total: '5000.00',
      currency: 'EUR',
      requested: '900.00',
      reserved: '500.00',
      approved: '750.00',
      paid: '250.00',
      committed: '1500.00',
      available: '3500.00',
    },
    {
      budgetPotId: MOCK_BUDGET_POTS[2].id,
      period: '2026',
      total: null,
      currency: 'EUR',
      requested: '600.00',
      reserved: '0.00',
      approved: '300.00',
      paid: '300.00',
      committed: '600.00',
      available: null,
    },
  ],
  statusDistribution: [
    { gremiumId: MOCK_GREMIUM_ID, stateId: '51110000-0000-0000-0000-000000000001', count: 7 },
    { gremiumId: MOCK_GREMIUM_ID, stateId: '52220000-0000-0000-0000-000000000002', count: 4 },
    { gremiumId: MOCK_GREMIUM_ID, stateId: '53330000-0000-0000-0000-000000000004', count: 2 },
  ],
};

/** Laufende Demo-Abstimmung (api.md »voting«, GET /votes/{id}). */
const MOCK_VOTE: Vote = {
  id: 'vote-demo',
  applicationId: 'app-demo',
  eligibleGroup: 'stupa',
  config: {
    options: ['yes', 'no', 'abstain'],
    majorityRule: 'two_thirds',
    quorum: { type: 'percent', value: 50 },
    abstainCountsQuorum: true,
    secret: false,
    allowChange: true,
    tieBreak: 'rejected',
  },
  status: 'open',
  opensAt: '2026-06-06T09:00:00Z',
  closesAt: null,
  result: null,
  secret: false,
  tally: { counts: { yes: 5, no: 2, abstain: 1 }, eligible: 12, quorumMet: true, leading: 'yes' },
};

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
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

const MOCK_APP_ID = '33333333-3333-3333-3333-333333333333';

const MOCK_EFFECTIVE_FORM: EffectiveForm = {
  applicationTypeId: MOCK_TYPES.items[0].id,
  formVersionId: '44444444-4444-4444-4444-444444444444',
  budgetPotId: '55555555-5555-5555-5555-555555555555',
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
  ],
};

const SUBMITTED_STATE: StateOutWire = {
  id: '66666666-6666-6666-6666-666666666661',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  category: 'open',
  editAllowed: true,
};

const REVIEW_STATE: StateOutWire = {
  id: '66666666-6666-6666-6666-666666666662',
  key: 'review',
  label: { de: 'In Prüfung', en: 'In review' },
  category: 'open',
  editAllowed: false,
};

function mockApplication(data: Record<string, unknown> = {}): ApplicationOutWire {
  return {
    id: MOCK_APP_ID,
    typeId: MOCK_TYPES.items[0].id,
    state: SUBMITTED_STATE,
    gremiumId: null,
    budgetPotId: MOCK_EFFECTIVE_FORM.budgetPotId ?? null,
    amount: null,
    currency: 'EUR',
    data,
    version: 1,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-05T10:00:00Z',
  };
}

const MOCK_APPLICATIONS: Page<ApplicationOutWire> = {
  items: [
    {
      id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      typeId: '11111111-1111-1111-1111-111111111111',
      state: { ...SUBMITTED_STATE, editAllowed: false },
      gremiumId: null,
      budgetPotId: null,
      amount: '250.00',
      currency: 'EUR',
      data: { title: 'Förderung Ersti-Wochenende' },
      version: 1,
      lang: 'de',
      createdAt: '2026-05-30T09:00:00Z',
      updatedAt: '2026-05-30T09:00:00Z',
    },
    {
      id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      typeId: '22222222-2222-2222-2222-222222222222',
      state: {
        id: '66666666-6666-6666-6666-666666666663',
        key: 'draft',
        label: { de: 'Entwurf', en: 'Draft' },
        category: 'open',
        editAllowed: true,
      },
      gremiumId: null,
      budgetPotId: null,
      amount: null,
      currency: 'EUR',
      data: { title: 'Anschaffung Beamer' },
      version: 1,
      lang: 'de',
      createdAt: '2026-06-02T14:30:00Z',
      updatedAt: '2026-06-02T14:30:00Z',
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

/**
 * Offene Entscheidungen für die eigene Rolle (#64): GET /applications/tasks.
 * Nur Anträge in vote/approval-States, in denen der Principal handeln darf.
 * Approval-Zeilen tragen Inline-Annehmen/Ablehnen, vote-Zeilen öffnen das Detail.
 */
const MOCK_TASKS: ApplicationListItemWire[] = [
  {
    id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
    typeId: '11111111-1111-1111-1111-111111111111',
    state: {
      id: '66666666-6666-6666-6666-666666666671',
      key: 'finance_approval',
      label: { de: 'Finanz-Freigabe', en: 'Finance approval' },
      category: 'pending',
      editAllowed: false,
      kind: 'vote',
    },
    gremiumId: null,
    budgetPotId: null,
    amount: '480.00',
    currency: 'EUR',
    title: 'Hardware für Fachschaftsraum',
    createdAt: '2026-06-06T08:15:00Z',
    updatedAt: '2026-06-07T16:00:00Z',
  },
  {
    id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
    typeId: '22222222-2222-2222-2222-222222222222',
    state: {
      id: '66666666-6666-6666-6666-666666666672',
      key: 'plenum_vote',
      label: { de: 'Abstimmung Plenum', en: 'Plenum vote' },
      category: 'pending',
      editAllowed: false,
      kind: 'vote',
    },
    gremiumId: null,
    budgetPotId: null,
    amount: '1200.00',
    currency: 'EUR',
    title: 'Förderung Sommerfest',
    createdAt: '2026-06-04T11:00:00Z',
    updatedAt: '2026-06-08T09:30:00Z',
  },
];

const MOCK_TIMELINE: TimelineEventOutWire[] = [
  {
    fromStateId: null,
    toStateId: SUBMITTED_STATE.id,
    toState: SUBMITTED_STATE,
    actor: null,
    at: '2026-06-05T10:00:00Z',
    note: null,
  },
  {
    fromStateId: SUBMITTED_STATE.id,
    toStateId: REVIEW_STATE.id,
    toState: REVIEW_STATE,
    actor: 'Finanzreferat',
    at: '2026-06-05T12:30:00Z',
    note: 'Eingang bestätigt.',
  },
];

const MOCK_COMMENTS: CommentOutWire[] = [
  {
    id: 'c0000000-0000-0000-0000-000000000001',
    author: 'Finanzreferat',
    authorKind: 'principal',
    body: 'Bitte ergänze die Kostenaufstellung.',
    visibility: 'public',
    at: '2026-06-05T13:00:00Z',
  },
];

const MOCK_VERSIONS: VersionOutWire[] = [
  {
    version: 1,
    data: { title: 'Förderung Ersti-Wochenende', amount: '200.00' },
    diff: null,
    changedBy: 'Antragsteller:in',
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
    changedBy: 'Antragsteller:in',
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

// --- meetings + Protokoll (T-33) — mutabler In-Memory-State ----------------- //
const MOCK_MEETING_ID = 'd0000000-0000-0000-0000-000000000001';
const MOCK_PROTOCOL_ID = 'e0000000-0000-0000-0000-000000000099';

let MOCK_MEETING: MeetingOutWire = {
  id: MOCK_MEETING_ID,
  title: 'STUPA-Sitzung 12.06.',
  status: 'live',
  activeApplicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  gremiumId: null,
  protocolId: MOCK_PROTOCOL_ID,
  canControl: true,
  votes: [
    {
      id: 'a0000000-0000-0000-0000-0000000000a1',
      applicationId: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      title: 'Förderung Ersti-Wochenende',
      status: 'open',
      result: null,
      counts: { ja: 12, nein: 3, enthaltung: 1 },
      leading: 'ja',
      closesAt: null,
    },
    {
      id: 'a0000000-0000-0000-0000-0000000000a2',
      applicationId: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      title: 'Anschaffung Beamer',
      status: 'pending',
      result: null,
      counts: null,
      leading: null,
      closesAt: null,
    },
  ],
  createdAt: '2026-06-12T17:00:00Z',
};

interface MockAttendance {
  principalId: string;
  displayName: string | null;
  email: string | null;
  status: 'present' | 'excused' | 'absent' | null;
  source: 'self' | 'lead' | null;
  isSelf: boolean;
}

let MOCK_ATTENDANCE: MockAttendance[] = [
  { principalId: 'me', displayName: 'Demo-Nutzer:in', email: null, status: null, source: null, isSelf: true },
  { principalId: 'p-2', displayName: 'Max Mustermann', email: 'max@example.com', status: 'present', source: 'lead', isSelf: false },
  { principalId: 'p-3', displayName: 'Erika Beispiel', email: 'erika@example.com', status: 'excused', source: 'self', isSelf: false },
];

interface MockAgendaItem {
  id: string;
  applicationId: string | null;
  title: string | null;
  body?: string | null;
  position: number;
  stateLabel?: Record<string, string> | null;
}

let MOCK_AGENDA: MockAgendaItem[] = [];
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

/** Vote-Status im Mock-Meeting setzen (gibt beim Schließen ein Ergebnis aus). */
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

function path(url: string): string {
  return url.split('?')[0];
}

export const mockApiInterceptor: HttpInterceptorFn = (req, next) => {
  if (!inject(USE_MOCK_API)) return next(req);
  if (!req.url.includes('/api/')) return next(req);

  const p = path(req.url);
  const ok = <T>(body: T, status = 200): Observable<HttpEvent<unknown>> =>
    of(new HttpResponse({ status, body })).pipe(delay(120));

  if (req.method === 'GET') {
    if (p.endsWith('/auth/me')) return ok(MOCK_PRINCIPAL);
    // Altcha im Mock-Betrieb aus → 404 (Widget meldet „unavailable", kein Captcha).
    if (p.endsWith('/altcha/challenge')) {
      return throwError(() => new HttpErrorResponse({ status: 404, url: req.url }));
    }
    if (/\/application-types\/[^/]+\/form$/.test(p)) return ok(MOCK_EFFECTIVE_FORM);
    if (p.endsWith('/application-types')) return ok(MOCK_TYPES);
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
    if (p.endsWith('/budget/stats')) return ok(MOCK_BUDGET_STATS);
    if (p.endsWith('/budget-pots')) return ok([...MOCK_BUDGET_POTS]);
    if (p.endsWith('/applications/tasks')) return ok([...MOCK_TASKS]);
    if (p.endsWith('/applications')) return ok(MOCK_APPLICATIONS);
    if (/\/votes\/[^/]+$/.test(p)) return ok(MOCK_VOTE);
    if (p.endsWith('/meetings')) return ok([MOCK_MEETING]);
    if (/\/meetings\/[^/]+\/attendance$/.test(p)) return ok([...MOCK_ATTENDANCE]);
    if (/\/meetings\/[^/]+\/agenda\/assignable$/.test(p)) {
      const taken = new Set(MOCK_AGENDA.map((a) => a.applicationId));
      return ok(MOCK_ASSIGNABLE.filter((a) => !taken.has(a.applicationId)));
    }
    if (/\/meetings\/[^/]+\/agenda$/.test(p)) return ok([...MOCK_AGENDA]);
    if (/\/meetings\/[^/]+$/.test(p)) return ok(MOCK_MEETING);
    if (/\/applications\/[^/]+$/.test(p)) return ok(mockApplication());
  }

  if (req.method === 'PUT') {
    // TOPs umsortieren (…/agenda/order).
    if (/\/meetings\/[^/]+\/agenda\/order$/.test(p)) {
      const ids = (req.body as { itemIds?: string[] } | null)?.itemIds ?? [];
      const byId = new Map(MOCK_AGENDA.map((a) => [a.id, a]));
      MOCK_AGENDA = ids.map((id, i) => ({ ...(byId.get(id) as MockAgendaItem), position: i }));
      return ok([...MOCK_AGENDA]);
    }
    // Anwesenheit setzen (…/attendance/me oder …/attendance/{principalId}).
    const att = /\/meetings\/[^/]+\/attendance\/([^/]+)$/.exec(p);
    if (att) {
      const status = (req.body as { status?: string } | null)?.status ?? 'present';
      const target = att[1];
      MOCK_ATTENDANCE = MOCK_ATTENDANCE.map((a) =>
        a.isSelf && target === 'me'
          ? { ...a, status: status as MockAttendance['status'], source: 'self' }
          : a.principalId === target
            ? { ...a, status: status as MockAttendance['status'], source: 'lead' }
            : a,
      );
      return ok([...MOCK_ATTENDANCE]);
    }
  }

  if (req.method === 'POST') {
    if (p.endsWith('/auth/logout')) return ok(LOGOUT_OUT);
    // Live-Abstimmung für einen Antrag öffnen (Beschlussfrage).
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
    // Antrag auf die Tagesordnung setzen.
    if (/\/meetings\/[^/]+\/agenda$/.test(p)) {
      const body = req.body as { applicationId?: string; title?: string } | null;
      const appId = body?.applicationId;
      const freetext = body?.title;
      if (freetext) {
        MOCK_AGENDA = [
          ...MOCK_AGENDA,
          { id: `ag-${++MOCK_AGENDA_SEQ}`, applicationId: null, title: freetext, position: MOCK_AGENDA.length },
        ];
      } else if (appId && !MOCK_AGENDA.some((a) => a.applicationId === appId)) {
        const src = MOCK_ASSIGNABLE.find((a) => a.applicationId === appId);
        MOCK_AGENDA = [
          ...MOCK_AGENDA,
          { id: `ag-${++MOCK_AGENDA_SEQ}`, applicationId: appId, title: src?.title ?? null, position: MOCK_AGENDA.length, stateLabel: src?.stateLabel ?? null },
        ];
      }
      return ok([...MOCK_AGENDA]);
    }
    if (p.endsWith('/auth/magic-link/verify')) {
      // Cookie-Modell: der echte Server setzt eine HttpOnly-Applicant-Cookie;
      // der Mock liefert nur Scope + App-ID, keinen Session-Token.
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
      };
      MOCK_COMMENTS.push(created);
      return ok(created, 201);
    }
    if (p.endsWith('/attachments')) {
      // Multipart-Upload: der echte Server scannt async → `scanned=false`.
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
    if (/\/applications\/[^/]+\/approval$/.test(p)) {
      // Approval entscheiden (#28): Branch feuert → Antrag verlässt den
      // approval-State, Aufgabe verschwindet beim Reload.
      const appId = p.split('/').slice(-2)[0];
      const idx = MOCK_TASKS.findIndex((t) => t.id === appId);
      if (idx >= 0) MOCK_TASKS.splice(idx, 1);
      const result: TransitionResult = {
        newStateId: REVIEW_STATE.id,
        statusEventId: 'e0000000-0000-0000-0000-000000000002',
        dispatchedActions: [],
      };
      return ok(result);
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
      const res: BallotResult = { status: 'cast' };
      return ok(res, 201);
    }
    // --- meetings + Protokoll (T-33) ---
    if (p.endsWith('/finalize')) {
      MOCK_PROTOCOL = {
        ...MOCK_PROTOCOL,
        status: 'final',
        pdfUrl: 'https://nextcloud.example/s/protokoll-12-06.pdf',
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
      // BE legt neue Sitzungen mit Status `planned` an (#104 — keine Drift mehr).
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
    const body = (req.body as { status?: MeetingOutWire['status']; activeApplicationId?: string; date?: string | null; startTime?: string | null } | null) ?? {};
    MOCK_MEETING = {
      ...MOCK_MEETING,
      status: body.status ?? MOCK_MEETING.status,
      activeApplicationId:
        body.activeApplicationId !== undefined
          ? body.activeApplicationId
          : MOCK_MEETING.activeApplicationId,
      date: body.date !== undefined ? body.date : MOCK_MEETING.date,
      startTime: body.startTime !== undefined ? body.startTime : MOCK_MEETING.startTime,
    };
    return ok(MOCK_MEETING);
  }

  if (req.method === 'PATCH') {
    // Markdown-Text eines TOP setzen (…/agenda/{itemId}).
    const body = /\/meetings\/[^/]+\/agenda\/([^/]+)$/.exec(p);
    if (body) {
      const text = (req.body as { body?: string } | null)?.body ?? '';
      MOCK_AGENDA = MOCK_AGENDA.map((a) => (a.id === body[1] ? { ...a, body: text } : a));
      return ok([...MOCK_AGENDA]);
    }
  }

  if (req.method === 'PATCH' && /\/protocols\/[^/]+$/.test(p)) {
    const markdown = (req.body as { markdown?: string } | null)?.markdown ?? MOCK_PROTOCOL.markdown;
    MOCK_PROTOCOL = { ...MOCK_PROTOCOL, markdown };
    return ok(MOCK_PROTOCOL);
  }

  if (req.method === 'DELETE') {
    const agenda = /\/meetings\/[^/]+\/agenda\/([^/]+)$/.exec(p);
    if (agenda) {
      MOCK_AGENDA = MOCK_AGENDA.filter((a) => a.id !== agenda[1]);
      return ok([...MOCK_AGENDA]);
    }
  }

  return next(req);
};
