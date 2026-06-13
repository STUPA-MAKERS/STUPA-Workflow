import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AuthService } from '@core/auth/auth.service';
import { AdminHomeComponent } from './admin-home.component';

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

const ALL_PERMS = [
  'admin.roles',
  'admin.gremien',
  'admin.site',
  'admin.types',
  'admin.notifications',
  'account.manage',
  'budget.structure',
  'form.configure',
  'flow.configure',
  'webhook.manage',
  'audit.read',
];

async function setup(perms: string[] = ALL_PERMS) {
  await render(AdminHomeComponent, {
    providers: [provideRouter([]), { provide: AuthService, useValue: fakeAuth(perms) }],
  });
}

describe('AdminHomeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows a navigation tile per admin area', async () => {
    await setup();
    expect(screen.getByRole('heading', { name: 'Verwaltung', level: 1 })).toBeInTheDocument();
    for (const name of ['Formular-Builder', 'Flow-Editor', 'Branding & Texte', 'Webhooks']) {
      expect(screen.getByRole('link', { name: new RegExp(name) })).toBeInTheDocument();
    }
  });

  it('links each tile to its sub-route', async () => {
    await setup();
    const forms = screen.getByRole('link', { name: /Formular-Builder/ });
    expect(forms).toHaveAttribute('href', '/forms');
  });

  it('no longer renders the active-forms overview table (task 1)', async () => {
    await setup();
    expect(screen.queryByRole('heading', { name: 'Aktive Formulare' })).not.toBeInTheDocument();
  });

  it('hides tiles the user has no permission for (#5-1)', async () => {
    await setup(['form.configure']); // nur Formular-Builder
    expect(screen.getByRole('link', { name: /Formular-Builder/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Flow-Editor/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Webhooks/ })).not.toBeInTheDocument();
  });
});
