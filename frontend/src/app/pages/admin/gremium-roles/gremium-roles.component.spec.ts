import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { GremiumRolesComponent } from './gremium-roles.component';

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremienOptions: jest.fn(() => of([{ id: 'g-1', name: 'Studierendenparlament' }])),
    listGremiumRoles: jest.fn(() =>
      of([
        {
          id: 'gr-1',
          gremiumId: 'g-1',
          key: 'vorsitz',
          name: { de: 'Vorsitz' },
          permissions: ['vote.cast'],
        },
      ]),
    ),
    listRoleMappings: jest.fn(() => of([])),
    listMembershipMappings: jest.fn(() => of([])),
    ...over,
  };
}

async function setup(api = makeApi(), params: Record<string, string> = { id: 'g-1' }) {
  await render(GremiumRolesComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: { success: jest.fn(), error: jest.fn() } },
      { provide: AuthService, useValue: { can: () => true } },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap(params) } },
      },
    ],
  });
  return api;
}

describe('GremiumRolesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the matrix of the gremium from the route, with the gremium in the title', async () => {
    const api = await setup();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Gremium-Rollen: Studierendenparlament',
    );
    expect(api.listGremiumRoles).toHaveBeenCalledWith('g-1', { quiet: true });
    expect(screen.getByRole('rowheader', { name: /^Vorsitz/ })).toBeInTheDocument();
    // The page title names the page; the matrix has no heading of its own here.
    expect(screen.queryByRole('heading', { name: 'Gremienrollen und Berechtigungen' })).toBeNull();
  });

  it('keeps the plain title when the gremium is unknown or the read fails', async () => {
    await setup(makeApi({ listGremienOptions: jest.fn(() => of([])) }));
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Gremium-Rollen$/);
  });

  it('keeps the plain title when the gremien read fails', async () => {
    await setup(
      makeApi({ listGremienOptions: jest.fn(() => throwError(() => ({ status: 500 }))) }),
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/^Gremium-Rollen$/);
  });

  it('reads no id as an empty id', async () => {
    const api = await setup(makeApi(), {});
    expect(api.listGremiumRoles).toHaveBeenCalledWith('', { quiet: true });
  });
});
