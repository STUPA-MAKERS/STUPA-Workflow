import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
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
};

async function setup(gremien: Gremium[] = [GREMIUM]) {
  const view = await render(AdminGremienComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush(gremien);
  return { ...view, http };
}

describe('AdminGremienComponent', () => {
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

  it('creates a committee via POST and reloads', async () => {
    const { http } = await setup([]);
    await userEvent.type(screen.getByLabelText('Name'), 'AStA');
    await userEvent.type(screen.getByLabelText(/Kürzel/), 'asta');

    await userEvent.click(screen.getByRole('button', { name: 'Anlegen' }));

    const post = http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'POST');
    expect(post.request.body).toEqual({
      name: 'AStA',
      slug: 'asta',
      cdVariant: 'stupa',
      defaultLang: 'de',
    });
    post.flush({ ...GREMIUM, id: 'g-2', name: 'AStA', slug: 'asta' });

    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('edits a committee via PATCH', async () => {
    const { http } = await setup();
    await screen.findByText('Studierendenparlament');

    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    const name = screen.getByLabelText('Name');
    await userEvent.clear(name);
    await userEvent.type(name, 'StuPa 2026');
    await userEvent.selectOptions(screen.getByLabelText(/Standardsprache/), 'en');

    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    const patch = http.expectOne(
      (r) => r.url.endsWith('/admin/gremien/g-1') && r.method === 'PATCH',
    );
    expect(patch.request.body).toEqual({
      name: 'StuPa 2026',
      slug: 'stupa',
      cdVariant: 'stupa',
      defaultLang: 'en',
    });
    patch.flush({ ...GREMIUM, name: 'StuPa 2026', defaultLang: 'en' });
    http.expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('keeps create disabled until name and slug are set', async () => {
    await setup([]);
    const add = screen.getByRole('button', { name: 'Anlegen' });
    expect(add).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Name'), 'X');
    expect(add).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Kürzel/), 'x');
    expect(add).toBeEnabled();
  });

  it('shows an error when the list cannot load', async () => {
    const view = await render(AdminGremienComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.url.endsWith('/admin/gremien') && r.method === 'GET')
      .flush({ detail: 'fail' }, { status: 500, statusText: 'Server Error' });
    expect(await screen.findByText(/konnten nicht geladen/i)).toBeInTheDocument();
  });
});
