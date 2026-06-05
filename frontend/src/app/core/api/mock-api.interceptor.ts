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
  ApplicationComment,
  ApplicationOut,
  ApplicationType,
  EffectiveForm,
  MagicLinkVerifyResult,
  Page,
  Principal,
  TimelineEntry,
  Transition,
} from './models';

/**
 * In-Memory-Mock-Backend für den Skelett-/FE-Betrieb (Mock erlaubt, T-03/T-30).
 * Aktiv nur wenn `USE_MOCK_API` true ist; greift ausschließlich für `/api/*`.
 * Deckt den öffentlichen Apply-Flow (T-30) gegen den OpenAPI-Contract ab:
 * effektive Form, Antrag anlegen, Magic-Link-Verify (Cookie-Modell, kein Token),
 * Timeline, Kommentare, PATCH. Echte Persistenz kommt in den Backend-Tasks (T-12ff).
 */
const MOCK_PRINCIPAL: Principal = {
  sub: '00000000-0000-0000-0000-000000000001',
  display_name: 'Demo Mitglied',
  email: 'demo@stupa.example',
  roles: ['member'],
  permissions: ['application.read', 'vote.cast'],
  groups: [],
};

const MOCK_TYPES: ApplicationType[] = [
  { id: '11111111-1111-1111-1111-111111111111', name: 'Finanzantrag', active: true },
  { id: '22222222-2222-2222-2222-222222222222', name: 'Sonstiger Antrag', active: true },
];

const MOCK_APP_ID = '33333333-3333-3333-3333-333333333333';

const MOCK_EFFECTIVE_FORM: EffectiveForm = {
  applicationTypeId: MOCK_TYPES[0].id,
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

function mockApplication(data: Record<string, unknown> = {}): ApplicationOut {
  return {
    id: MOCK_APP_ID,
    type_id: MOCK_TYPES[0].id,
    state: { key: 'submitted', label: 'Eingereicht', editAllowed: true },
    gremium_id: null,
    budget_pot_id: MOCK_EFFECTIVE_FORM.budgetPotId ?? null,
    amount: null,
    data,
    version: 1,
    created_at: '2026-06-05T10:00:00Z',
  };
}

const MOCK_APPLICATIONS: Page<ApplicationOut> = {
  items: [
    {
      id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      type_id: '11111111-1111-1111-1111-111111111111',
      state: { key: 'submitted', label: 'Eingereicht', editAllowed: false },
      gremium_id: null,
      budget_pot_id: null,
      amount: '250.00',
      data: { title: 'Förderung Ersti-Wochenende' },
      version: 1,
      created_at: '2026-05-30T09:00:00Z',
    },
    {
      id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
      type_id: '22222222-2222-2222-2222-222222222222',
      state: { key: 'draft', label: 'Entwurf', editAllowed: true },
      gremium_id: null,
      budget_pot_id: null,
      amount: null,
      data: { title: 'Anschaffung Beamer' },
      version: 1,
      created_at: '2026-06-02T14:30:00Z',
    },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

const MOCK_TIMELINE: TimelineEntry[] = [
  { state: 'submitted', label: 'Eingereicht', at: '2026-06-05T10:00:00Z' },
  { state: 'review', label: 'In Prüfung', at: '2026-06-05T12:30:00Z', note: 'Eingang bestätigt.' },
];

const MOCK_COMMENTS: ApplicationComment[] = [
  {
    id: 'c0000000-0000-0000-0000-000000000001',
    body: 'Bitte ergänze die Kostenaufstellung.',
    author_name: 'Finanzreferat',
    created_at: '2026-06-05T13:00:00Z',
    is_public: true,
  },
];

const EMPTY_TRANSITIONS: Transition[] = [];
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
    if (p.endsWith('/comments')) return ok([...MOCK_COMMENTS]);
    if (p.endsWith('/transitions')) return ok(EMPTY_TRANSITIONS);
    if (p.endsWith('/applications')) return ok(MOCK_APPLICATIONS);
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
      const created: ApplicationComment = {
        id: `c0000000-0000-0000-0000-0000000000${MOCK_COMMENTS.length + 1}`,
        body,
        author_name: null,
        created_at: '2026-06-05T14:00:00Z',
        is_public: true,
      };
      MOCK_COMMENTS.push(created);
      return ok(created, 201);
    }
    if (p.endsWith('/applications')) {
      const data = (req.body as { data?: Record<string, unknown> } | null)?.data ?? {};
      return ok(mockApplication(data), 201);
    }
  }

  if (req.method === 'PATCH' && /\/applications\/[^/]+$/.test(p)) {
    const data = (req.body as { data?: Record<string, unknown> } | null)?.data ?? {};
    return ok(mockApplication(data));
  }

  return next(req);
};
