import { of, throwError } from 'rxjs';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { AdminApiService } from './admin-api.service';
import { AdminHomeComponent } from './admin-home.component';
import type { Gremium } from './admin.models';

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

const GREMIEN: Gremium[] = [
  {
    id: 'g-1',
    name: 'Studierendenparlament',
    slug: 'stupa',
    cdVariantId: null,
    defaultLang: 'de',
    allowVoteDelegation: true,
    memberCount: 23,
    roleCount: 4,
  },
  {
    id: 'g-2',
    name: 'Wahlausschuss',
    slug: 'wahl',
    cdVariantId: null,
    defaultLang: 'de',
    allowVoteDelegation: false,
    memberCount: 1,
    roleCount: 1,
  },
];

async function setup(perms: string[], api: Partial<AdminApiService> = {}) {
  const fake = {
    listGremien: jest.fn(() => of(GREMIEN)),
    listGremienOptions: jest.fn(() =>
      of(GREMIEN.map(({ memberCount: _m, roleCount: _r, ...g }) => g)),
    ),
    ...api,
  };
  const view = await render(AdminHomeComponent, {
    providers: [
      provideRouter([]),
      { provide: AuthService, useValue: fakeAuth(perms) },
      { provide: AdminApiService, useValue: fake },
    ],
  });
  return { view, api: fake };
}

describe('AdminHomeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the gremien with slug, counts and the links to members and roles', async () => {
    const { api } = await setup(['admin.gremien', 'admin.gremium_roles']);
    expect(api.listGremien).toHaveBeenCalledWith({ quiet: true });
    expect(screen.getByRole('heading', { name: 'Gremien', level: 2 })).toBeInTheDocument();
    expect(screen.getByText('stupa')).toBeInTheDocument();
    expect(screen.getByText(/23 Mitglieder/)).toBeInTheDocument();
    expect(screen.getByText(/4 Rollen/)).toBeInTheDocument();
    // One member and one role read in the singular.
    expect(screen.getByText(/1 Mitglied\b/)).toBeInTheDocument();
    expect(screen.getByText(/1 Rolle\b/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Mitglieder: Studierendenparlament' })).toHaveAttribute(
      'href',
      '/admin/gremien/g-1/members',
    );
    expect(screen.getByRole('link', { name: 'Rollen: Studierendenparlament' })).toHaveAttribute(
      'href',
      '/admin/gremien/g-1/roles',
    );
    expect(screen.getByRole('link', { name: 'Gremien verwalten' })).toHaveAttribute(
      'href',
      '/admin/gremien',
    );
  });

  it('hides the roles link without admin.gremium_roles', async () => {
    await setup(['admin.gremien']);
    expect(screen.queryByRole('link', { name: /^Rollen:/ })).toBeNull();
    expect(screen.getAllByRole('link', { name: /^Mitglieder:/ })).toHaveLength(2);
  });

  it('gives admin.gremium_roles alone the master data and the roles links', async () => {
    const { api } = await setup(['admin.gremium_roles']);
    expect(api.listGremien).not.toHaveBeenCalled();
    expect(api.listGremienOptions).toHaveBeenCalled();
    expect(screen.getAllByRole('link', { name: /^Rollen:/ })).toHaveLength(2);
    expect(screen.queryByRole('link', { name: /^Mitglieder:/ })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Gremien verwalten' })).toBeNull();
    // The master data has no counts.
    expect(screen.queryByText(/Mitglieder ·/)).toBeNull();
  });

  it('renders nothing without a gremium permission', async () => {
    const { view, api } = await setup(['backup.manage']);
    expect(api.listGremien).not.toHaveBeenCalled();
    expect(view.container.querySelector('section')).toBeNull();
  });

  it('says so when the list fails', async () => {
    await setup(['admin.gremien'], { listGremien: jest.fn(() => throwError(() => new Error('x'))) });
    expect(screen.getByRole('alert')).toHaveTextContent('Die Gremien konnten nicht geladen werden.');
  });

  it('shows the empty state without gremien', async () => {
    await setup(['admin.gremien'], { listGremien: jest.fn(() => of([])) });
    expect(screen.getByText('Noch keine Gremien.')).toBeInTheDocument();
  });
});
