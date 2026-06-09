import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { AdminHomeComponent } from './admin-home.component';

async function setup() {
  await render(AdminHomeComponent, {
    providers: [provideRouter([])],
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
});
