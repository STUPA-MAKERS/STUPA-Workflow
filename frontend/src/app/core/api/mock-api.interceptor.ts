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
  ApplicationOut,
  ApplicationType,
  Page,
  Principal,
  Transition,
} from './models';

/**
 * In-Memory-Mock-Backend für den Skelett-Betrieb (Mock erlaubt, T-03-Scope).
 * Aktiv nur wenn `USE_MOCK_API` true ist; greift ausschließlich für `/api/*`.
 * Echte Endpunkte/Persistenz kommen in den Backend-Tasks (T-10ff).
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
const EMPTY_TRANSITIONS: Transition[] = [];
const LOGOUT_OUT = { logout_url: null };

function match(url: string, suffix: string): boolean {
  const path = url.split('?')[0];
  return path.endsWith(suffix);
}

export const mockApiInterceptor: HttpInterceptorFn = (req, next) => {
  if (!inject(USE_MOCK_API)) return next(req);
  if (!req.url.includes('/api/')) return next(req);

  const ok = <T>(body: T): Observable<HttpEvent<unknown>> =>
    of(new HttpResponse({ status: 200, body })).pipe(delay(120));

  if (req.method === 'GET') {
    if (match(req.url, '/auth/me')) return ok(MOCK_PRINCIPAL);
    if (match(req.url, '/application-types')) return ok(MOCK_TYPES);
    if (match(req.url, '/applications')) return ok(MOCK_APPLICATIONS);
    if (match(req.url, '/transitions')) return ok(EMPTY_TRANSITIONS);
  }

  if (req.method === 'POST' && match(req.url, '/auth/logout')) return ok(LOGOUT_OUT);

  return next(req);
};
