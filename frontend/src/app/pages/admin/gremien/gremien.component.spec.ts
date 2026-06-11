import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Gremium } from '../admin.models';
import { AdminGremienComponent } from './gremien.component';

const GREMIUM: Gremium = {
  id: 'g-1',
  name: 'Studierendenparlament',
  slug: 'stupa',
  cdVariant: 'stupa',
  defaultLang: 'de',
  allowVoteDelegation: false,
};

async function setup(gremien: Gremium[] = [GREMIUM]) {
  const view = await render(AdminGremienComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush(gremien);
  return { ...view, http };
}

describe('AdminGremienComponent (#18)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists existing committees from /admin/gremien', async () => {
    const { http } = await setup();
    expect(await screen.findByText('Studierendenparlament')).toBeInTheDocument();
    http.verify();
  });

  it('shows the empty state when there are none', async () => {
    const { http } = await setup([]);
    expect(await screen.findByText('Noch keine Gremien angelegt.')).toBeInTheDocument();
    http.verify();
  });

  it('creates a committee via a dialog with an auto-generated slug', async () => {
    const { http } = await setup([]);
    await userEvent.click(screen.getByRole('button', { name: 'Gremium hinzufügen' }));
    await userEvent.type(screen.getByLabelText('Name'), 'AStA Vorstand');
    await userEvent.click(screen.getByRole('button', { name: 'Anlegen' }));

    const post = http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'POST');
    expect(post.request.body).toEqual({
      name: 'AStA Vorstand',
      slug: 'asta-vorstand',
      cdVariant: 'stupa',
      defaultLang: 'de',
      allowVoteDelegation: false,
      delegationLeadMinutes: 0,
      delegationAllowExternal: false,
      quorumPercent: null,
    });
    post.flush({ ...GREMIUM, id: 'g-2', name: 'AStA Vorstand', slug: 'asta-vorstand' });
    // Nach den Stammdaten werden die Zusatz-Protokoll-Empfänger gespeichert
    // (#protocol-recipients) — hier leer.
    const putMail = http.expectOne(
      (r) => r.url.endsWith('/admin/gremien/g-2/mail-recipients') && r.method === 'PUT',
    );
    expect(putMail.request.body).toEqual({ recipients: [] });
    putMail.flush({ recipients: [] });
    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('edits a committee via PATCH (slug stays) incl. extra minutes recipients', async () => {
    const { http } = await setup();
    await screen.findByText('Studierendenparlament');
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    // Beim Öffnen werden die Zusatz-Empfänger nachgeladen (#protocol-recipients).
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien/g-1/mail-recipients') && r.method === 'GET')
      .flush({ recipients: ['alt@x.de'] });
    const name = screen.getByLabelText('Name');
    await userEvent.clear(name);
    await userEvent.type(name, 'StuPa 2026');
    await userEvent.selectOptions(screen.getByLabelText(/Standardsprache/), 'en');
    const mail = screen.getByLabelText('Zusätzliche Protokoll-Empfänger');
    await userEvent.clear(mail);
    await userEvent.type(mail, 'neu@y.org');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    const patch = http.expectOne((r) => r.url.endsWith('/admin/gremien/g-1') && r.method === 'PATCH');
    expect(patch.request.body).toEqual({
      name: 'StuPa 2026',
      cdVariant: 'stupa',
      defaultLang: 'en',
      allowVoteDelegation: false,
      delegationLeadMinutes: 0,
      delegationAllowExternal: false,
      quorumPercent: null,
    });
    patch.flush({ ...GREMIUM, name: 'StuPa 2026', defaultLang: 'en' });
    const putMail = http.expectOne(
      (r) => r.url.endsWith('/admin/gremien/g-1/mail-recipients') && r.method === 'PUT',
    );
    expect(putMail.request.body).toEqual({ recipients: ['neu@y.org'] });
    putMail.flush({ recipients: ['neu@y.org'] });
    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('keeps create disabled until a name is set', async () => {
    await setup([]);
    await userEvent.click(screen.getByRole('button', { name: 'Gremium hinzufügen' }));
    const add = screen.getByRole('button', { name: 'Anlegen' });
    expect(add).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Name'), 'X');
    expect(add).toBeEnabled();
  });
});
