import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { USE_MOCK_API } from '@core/api/api.config';
import { AdminHomeComponent } from './admin-home.component';

async function setup(mock = true) {
  await render(AdminHomeComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: mock },
    ],
  });
}

describe('AdminHomeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows a navigation tile per admin area', async () => {
    await setup();
    expect(screen.getByRole('heading', { name: 'Verwaltung', level: 1 })).toBeInTheDocument();
    for (const name of ['Formular-Builder', 'Flow-Editor', 'Branding & Texte', 'Webhooks', 'Benachrichtigungen']) {
      expect(screen.getByRole('heading', { name })).toBeInTheDocument();
    }
  });

  it('links each tile to its sub-route', async () => {
    await setup();
    const forms = screen.getByRole('link', { name: /Formular-Builder/ });
    expect(forms).toHaveAttribute('href', '/forms');
  });

  it('surfaces the mock notice while the admin API is mocked', async () => {
    await setup(true);
    expect(screen.getByRole('status')).toHaveTextContent(/Mock/);
  });

  it('hides the mock notice in real mode', async () => {
    await setup(false);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('lists active forms with their gremium, status and version (#75)', async () => {
    await setup();
    expect(screen.getByRole('heading', { name: 'Aktive Formulare' })).toBeInTheDocument();
    expect(screen.getByText('Förderantrag')).toBeInTheDocument();
    // Gremium-Name aufgelöst (nicht die rohe ID).
    expect(screen.getAllByText('Studierendenparlament').length).toBeGreaterThan(0);
    // Status-Badge + Version sichtbar.
    expect(screen.getAllByText('Aktiv').length).toBeGreaterThan(0);
    expect(screen.getByText('v3')).toBeInTheDocument();
  });

  it('shows an error state when the active-forms request fails (#review2 §5)', async () => {
    // Real mode → the overview comes from the API; a failure must surface an error state.
    const view = await render(AdminHomeComponent, {
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.url.endsWith('/admin/application-types'))
      .flush(null, { status: 500, statusText: 'Server Error' });
    http.expectOne((r) => r.url.endsWith('/admin/gremien')).flush([]);
    view.fixture.detectChanges();

    expect(screen.getByRole('alert')).toHaveTextContent('konnten nicht geladen werden');
    http.verify();
  });
});
