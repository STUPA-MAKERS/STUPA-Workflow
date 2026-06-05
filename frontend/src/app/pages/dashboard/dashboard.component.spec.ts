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
import type { ApplicationOut, Page, Principal } from '@core/api/models';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read', 'vote.cast'],
  groups: [],
};

const PAGE: Page<ApplicationOut> = { items: [], total: 2, limit: 20, offset: 0 };

async function setup(principal: Principal) {
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
  http.expectOne((r) => r.url.endsWith('/api/applications')).flush(PAGE);
  view.detectChanges();
  return { ...view, auth, http };
}

describe('DashboardComponent', () => {
  it('greets the signed-in member by name and shows their roles', async () => {
    const { http } = await setup(MEMBER);
    expect(screen.getByText('Willkommen, Mia Member')).toBeInTheDocument();
    expect(screen.getByText('member')).toBeInTheDocument();
    http.verify();
  });

  it('renders RBAC-permitted tiles and hides the rest', async () => {
    const { http } = await setup(MEMBER);
    expect(screen.getByText('Offene Aufgaben')).toBeInTheDocument();
    expect(screen.getByText('Meine Anträge')).toBeInTheDocument();
    expect(screen.getByText('Meine Abstimmungen')).toBeInTheDocument();
    // member lacks admin.config / budget.view / meeting.manage
    expect(screen.queryByText('Verwaltung')).not.toBeInTheDocument();
    expect(screen.queryByText('Budget')).not.toBeInTheDocument();
    http.verify();
  });

  it('shows the application count from the API once loaded', async () => {
    const { http } = await setup(MEMBER);
    expect(screen.getAllByText('2').length).toBeGreaterThan(0);
    http.verify();
  });

  it('shows every tile for an admin principal', async () => {
    const admin: Principal = {
      ...MEMBER,
      display_name: 'Adam Admin',
      roles: ['admin'],
      permissions: ['application.read', 'admin.config', 'budget.view', 'meeting.manage'],
    };
    const { http } = await setup(admin);
    expect(screen.getByText('Verwaltung')).toBeInTheDocument();
    expect(screen.getByText('Budget')).toBeInTheDocument();
    expect(screen.getByText('Sitzungen')).toBeInTheDocument();
    http.verify();
  });
});
