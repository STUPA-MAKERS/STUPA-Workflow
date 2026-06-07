import {
  type HttpEvent,
  type HttpInterceptorFn,
  HttpResponse,
} from '@angular/common/http';
import { inject } from '@angular/core';
import { type Observable, of } from 'rxjs';
import { delay } from 'rxjs/operators';
import { USE_MOCK_API } from './api.config';
import type {
  ApplicationCreatedWire,
  ApplicationOutWire,
  ApplicationTypeListItemWire,
  AttachmentOutWire,
  BallotResult,
  CommentOutWire,
  EffectiveForm,
  MagicLinkVerifyResult,
  Page,
  Principal,
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
  // vote.manage/meeting.manage (T-32) für Beamer-/Manage-Ansichten — alle im
  // Mock gesetzt, damit der FE-Dev/Harness-Betrieb die gegateten Ansichten zeigt.
  permissions: ['application.read', 'application.manage', 'vote.cast', 'vote.manage', 'meeting.manage'],
  groups: [],
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
      label: { de: 'Topf-spezifische Felder', en: 'Budget-specific fields' },
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
    if (p.endsWith('/applications')) return ok(MOCK_APPLICATIONS);
    if (/\/votes\/[^/]+$/.test(p)) return ok(MOCK_VOTE);
    if (/\/applications\/[^/]+$/.test(p)) return ok(mockApplication());
  }

  if (req.method === 'POST') {
    if (p.endsWith('/auth/logout')) return ok(LOGOUT_OUT);
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
  }

  if (req.method === 'PATCH' && /\/applications\/[^/]+$/.test(p)) {
    const data = (req.body as { data?: Record<string, unknown> } | null)?.data ?? {};
    return ok(mockApplication(data));
  }

  return next(req);
};
