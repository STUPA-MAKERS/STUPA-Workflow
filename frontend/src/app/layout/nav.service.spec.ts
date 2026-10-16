import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Principal } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { createLocationMock, provideLocationMock } from '../../testing/location-mock';
import { ADMIN_PAGES } from '../pages/admin/admin-frame/admin-pages';
import { ADMIN_AREA_PERMISSIONS, BOTTOM_BAR_KEYS, NAV_ITEMS, NavService } from './nav.service';
import { routes } from '../app.routes';

const BASE: Principal = { sub: '1', roles: ['member'], permissions: [], groups: [] } as unknown as Principal;

function keysFor(principal: Principal | null): string[] {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(createLocationMock()),
    ],
  });
  const auth = TestBed.inject(AuthService);
  auth.ensureLoaded().subscribe();
  const req = TestBed.inject(HttpTestingController).expectOne('/api/auth/me');
  if (principal) req.flush(principal);
  else req.flush(null, { status: 401, statusText: 'Unauthorized' });
  return TestBed.inject(NavService)
    .visible()
    .map((i) => i.key);
}

describe('NavService', () => {
  it('shows nothing to a visitor who is not signed in', () => {
    expect(keysFor(null)).toEqual([]);
  });

  it('shows a plain member only the personal areas', () => {
    expect(keysFor(BASE)).toEqual(['start', 'applications', 'tasks', 'todos']);
  });

  it('opens the budget areas with a global budget right', () => {
    expect(keysFor({ ...BASE, permissions: ['budget.book'] })).toEqual([
      'start',
      'applications',
      'tasks',
      'todos',
      'budget',
      'expenses',
      'invoices',
    ]);
  });

  it('opens the tickets with ticket.manage, after the invoices', () => {
    expect(keysFor({ ...BASE, permissions: ['ticket.manage'] })).toEqual(['start', 'applications', 'tasks', 'todos', 'tickets']);
    expect(NAV_ITEMS.findIndex((i) => i.key === 'tickets')).toBe(NAV_ITEMS.findIndex((i) => i.key === 'invoices') + 1);
  });

  it('shows the To-Dos to every session, after the tasks', () => {
    const todos = NAV_ITEMS.find((i) => i.key === 'todos');
    expect(todos).toMatchObject({ path: '/todos', labelKey: 'nav.todos', icon: 'circleok', permissions: [] });
    expect(NAV_ITEMS.findIndex((i) => i.key === 'todos')).toBe(NAV_ITEMS.findIndex((i) => i.key === 'tasks') + 1);
  });

  it('opens the administration with any area-admin right', () => {
    expect(keysFor({ ...BASE, permissions: ['backup.manage'] })).toContain('admin');
  });

  it('opens the administration for every page of the admin navigation', () => {
    // An entry of the admin navigation must never sit behind a hidden "Verwaltung".
    for (const page of ADMIN_PAGES) {
      for (const p of page.permissions) expect(ADMIN_AREA_PERMISSIONS).toContain(p);
    }
    expect(keysFor({ ...BASE, permissions: ['budget.structure'] })).toContain('admin');
  });

  it('opens meetings for protocol.write in a gremium, without the voting area', () => {
    const keys = keysFor({ ...BASE, gremium_permissions: { g1: ['protocol.write'] } });
    expect(keys).toContain('meetings');
    expect(keys).not.toContain('voting');
  });

  it('opens the gremien for a member of a gremium, after the meetings', () => {
    const keys = keysFor({ ...BASE, gremien: [{ id: 'g1', name: 'StuPa' }] } as unknown as Principal);
    expect(keys).toContain('gremien');
    expect(keys.indexOf('gremien')).toBe(keys.indexOf('meetings') + 1);
  });

  it('opens the gremien with gremium.view_all, without a membership', () => {
    const keys = keysFor({ ...BASE, permissions: ['gremium.view_all'] });
    expect(keys).toContain('gremien');
    expect(keys).not.toContain('meetings');
  });

  it('keeps the gremien out of the phone bar', () => {
    expect(BOTTOM_BAR_KEYS).not.toContain('gremien');
  });

  it('points every entry at a route the app has, with the same gate', () => {
    const paths = new Set((routes[0].children ?? []).map((r) => `/${r.path}`));
    for (const item of NAV_ITEMS) expect(paths).toContain(item.path);
  });
});
