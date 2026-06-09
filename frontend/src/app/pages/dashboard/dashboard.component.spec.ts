import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import { DashboardComponent } from './dashboard.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import type {
  ApplicationListItemWire,
  ApplicationTypeListItemWire,
  Page,
  Principal,
  StateOutWire,
} from '@core/api/models';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read', 'vote.cast'],
  groups: [],
};

const OPEN_STATE: StateOutWire = {
  id: 's-open',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  category: 'open',
  editAllowed: true,
};
const CLOSED_STATE: StateOutWire = {
  id: 's-closed',
  key: 'decided',
  label: { de: 'Entschieden', en: 'Decided' },
  category: 'closed',
  editAllowed: false,
};

const TYPES: Page<ApplicationTypeListItemWire> = {
  items: [
    { id: 't1', name: 'Finanzantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' },
    { id: 't2', name: 'Veranstaltung', hasBudget: false, active: true, activeFormVersionId: 'v2' },
  ],
  total: 2,
  limit: 20,
  offset: 0,
};

function item(id: string, typeId: string, state: StateOutWire): ApplicationListItemWire {
  return {
    id,
    typeId,
    state,
    gremiumId: null,
    budgetPotId: null,
    amount: null,
    currency: 'EUR',
    createdAt: '2026-05-30T09:00:00Z',
    updatedAt: '2026-05-30T09:00:00Z',
  };
}

// Two applications; one open (a task) + one closed (only "my applications").
const PAGE: Page<ApplicationListItemWire> = {
  items: [item('app-1', 't1', OPEN_STATE), item('app-2', 't2', CLOSED_STATE)],
  total: 2,
  limit: 20,
  offset: 0,
};

async function setup(
  principal: Principal,
  opts: { apps?: 'ok' | 'empty' | 'error' } = {},
) {
  const view = await render(DashboardComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const auth = view.fixture.debugElement.injector.get(AuthService);
  const http = view.fixture.debugElement.injector.get(HttpTestingController);

  auth.ensureLoaded().subscribe();
  http.expectOne('/api/auth/me').flush(principal);

  const appsReq = http.expectOne((r) => r.url.endsWith('/api/applications'));
  if (opts.apps === 'error') {
    appsReq.flush(null, { status: 500, statusText: 'Server Error' });
  } else if (opts.apps === 'empty') {
    appsReq.flush({ items: [], total: 0, limit: 20, offset: 0 });
  } else {
    appsReq.flush(PAGE);
  }
  http.expectOne((r) => r.url.endsWith('/api/application-types')).flush(TYPES);
  // Sitzungs-Shortcuts (#Sessions) laden `/meetings` — im Test leer beantworten.
  http
    .match((r) => r.url.endsWith('/api/meetings') && r.method === 'GET')
    .forEach((req) => req.flush([]));

  view.detectChanges();
  return { ...view, auth, http };
}

describe('DashboardComponent', () => {
  it('greets the signed-in member by name and shows their roles', async () => {
    const { http } = await setup(MEMBER);
    expect(screen.getByText('Willkommen, Mia Member')).toBeInTheDocument();
    expect(screen.getByText('Member')).toBeInTheDocument();
    http.verify();
  });

  it('offers a prominent "submit application" CTA linking to the wizard', async () => {
    const { http } = await setup(MEMBER);
    const cta = screen.getByRole('link', { name: /Antrag stellen/ });
    expect(cta).toHaveAttribute('href', '/apply');
    http.verify();
  });

  it('separates open tasks from my applications with distinct content', async () => {
    const { http } = await setup(MEMBER);
    expect(screen.getByText('Offene Aufgaben')).toBeInTheDocument();
    expect(screen.getByText('Meine Anträge')).toBeInTheDocument();

    // Open task = the non-closed application; appears in BOTH panels (tasks = the
    // actionable subset of my applications) and deep-links to its detail.
    const openLinks = screen.getAllByRole('link', { name: 'Finanzantrag' });
    expect(openLinks.length).toBe(2);
    for (const l of openLinks) expect(l).toHaveAttribute('href', '/applications/app-1');
    // The closed application is NOT a task — shows only under "my applications".
    const closedLinks = screen.getAllByRole('link', { name: 'Veranstaltung' });
    expect(closedLinks.length).toBe(1);
    expect(closedLinks[0]).toHaveAttribute('href', '/applications/app-2');
    // State labels are rendered as badges.
    expect(screen.getByText('Entschieden')).toBeInTheDocument();
    http.verify();
  });

  it('shows an empty state with an apply CTA when there are no applications', async () => {
    const { http } = await setup(MEMBER, { apps: 'empty' });
    expect(screen.getByText('Noch keine Anträge.')).toBeInTheDocument();
    const cta = screen.getByRole('link', { name: /Ersten Antrag stellen/ });
    expect(cta).toHaveAttribute('href', '/apply');
    http.verify();
  });

  it('surfaces an error state when the applications request fails', async () => {
    const { http } = await setup(MEMBER, { apps: 'error' });
    expect(screen.getAllByText('Konnte nicht geladen werden.').length).toBeGreaterThan(0);
    http.verify();
  });
});
