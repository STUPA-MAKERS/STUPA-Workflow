import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import { MailTemplatesComponent } from './mail-templates.component';

const TPL = {
  id: null,
  key: 'magic_link',
  subjectI18n: { de: 'Anmeldung', en: 'Sign in' },
  bodyI18n: { de: 'Hallo {{name}}', en: 'Hi {{name}}' },
  bodyHtmlI18n: {},
  placeholders: { name: 'Anzeigename' },
  source: 'builtin',
};

function setupApi() {
  return {
    listMailTemplates: jest.fn(() => of([TPL])),
    upsertMailTemplate: jest.fn(() => of({ ...TPL, source: 'override' })),
    previewMailPayload: jest.fn(() =>
      of({ subject: 'Anmeldung', text: 'Hallo Anzeigename', html: null, lang: 'de' }),
    ),
  };
}

async function setup() {
  const api = setupApi();
  await render(MailTemplatesComponent, {
    providers: [provideRouter([]), { provide: AdminApiService, useValue: api }],
  });
  return api;
}

describe('MailTemplatesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists templates and auto-selects the first with its subject', async () => {
    await setup();
    expect(await screen.findByRole('button', { name: /magic_link/ })).toBeInTheDocument();
    expect(screen.getByDisplayValue('Anmeldung')).toBeInTheDocument();
    // placeholder reference is shown.
    expect(screen.getByText(/name/)).toBeInTheDocument();
  });

  it('saves edits and renders a preview', async () => {
    const api = await setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Speichern' }));
    expect(api.upsertMailTemplate).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Vorschau' }));
    expect(api.previewMailPayload).toHaveBeenCalled();
    expect(await screen.findByText('Hallo Anzeigename')).toBeInTheDocument();
  });
});
