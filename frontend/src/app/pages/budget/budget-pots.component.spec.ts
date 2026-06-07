import { of } from 'rxjs';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { BudgetPotOutWire } from '@core/api/models';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetPotsComponent } from './budget-pots.component';

const POT: BudgetPotOutWire = {
  id: 'pot-1',
  gremiumId: 'g-1',
  name: 'Reisekosten',
  total: '5000.00',
  currency: 'EUR',
  period: '2026',
  active: true,
};

async function setup(pots: BudgetPotOutWire[] = [POT]) {
  const listGremienOptions = jest.fn(() =>
    of([{ id: 'g-1', name: 'StuPa', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de' }]),
  );
  const view = await render(BudgetPotsComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AdminApiService, useValue: { listGremienOptions } },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.expectOne((r) => r.url.endsWith('/budget-pots') && r.method === 'GET').flush(pots);
  return { ...view, http };
}

describe('BudgetPotsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists existing pots from the real /budget-pots endpoint', async () => {
    const { http } = await setup();
    expect(await screen.findByText('Reisekosten')).toBeInTheDocument();
    http.verify();
  });

  it('shows the empty state when there are no pots', async () => {
    const { http } = await setup([]);
    expect(await screen.findByText('Noch keine Budget-Töpfe angelegt.')).toBeInTheDocument();
    http.verify();
  });

  it('creates a pot via POST and reloads the list', async () => {
    const { http } = await setup([]);

    await userEvent.type(screen.getByLabelText('Name'), 'Druckkosten');
    await userEvent.selectOptions(screen.getByLabelText(/Gremium/), 'g-1');
    await userEvent.type(screen.getByLabelText('Limit'), '1000');

    await userEvent.click(screen.getByRole('button', { name: 'Anlegen' }));

    const post = http.expectOne((r) => r.url.endsWith('/budget-pots') && r.method === 'POST');
    expect(post.request.body).toEqual({
      gremiumId: 'g-1',
      name: 'Druckkosten',
      total: '1000',
      currency: 'EUR',
      period: null,
      active: true,
    });
    post.flush({ ...POT, id: 'pot-2', name: 'Druckkosten' });

    // Reload nach Erfolg.
    http.expectOne((r) => r.url.endsWith('/budget-pots') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('edits an existing pot via PATCH (committee stays locked)', async () => {
    const { http } = await setup();
    await screen.findByText('Reisekosten');

    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    const name = screen.getByLabelText('Name');
    await userEvent.clear(name);
    await userEvent.type(name, 'Reise 2026');

    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));

    const patch = http.expectOne(
      (r) => r.url.endsWith('/budget-pots/pot-1') && r.method === 'PATCH',
    );
    expect(patch.request.body).toEqual({
      name: 'Reise 2026',
      total: '5000',
      currency: 'EUR',
      period: '2026',
      active: true,
    });
    patch.flush({ ...POT, name: 'Reise 2026' });
    http.expectOne((r) => r.url.endsWith('/budget-pots') && r.method === 'GET').flush([]);
    http.verify();
  });

  it('keeps create disabled until a name and committee are set', async () => {
    await setup([]);
    const add = screen.getByRole('button', { name: 'Anlegen' });
    expect(add).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Name'), 'X');
    // Ohne Gremium bleibt der Button gesperrt.
    expect(add).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText(/Gremium/), 'g-1');
    expect(add).toBeEnabled();
  });

  it('shows an error when the list cannot be loaded', async () => {
    const listGremienOptions = jest.fn(() => of([]));
    const view = await render(BudgetPotsComponent, {
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        { provide: AdminApiService, useValue: { listGremienOptions } },
      ],
    });
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    http
      .expectOne((r) => r.url.endsWith('/budget-pots') && r.method === 'GET')
      .flush({ title: 'boom' }, { status: 500, statusText: 'Server Error' });
    expect(await screen.findByText('Die Töpfe konnten nicht geladen werden.')).toBeInTheDocument();
    http.verify();
  });
});
