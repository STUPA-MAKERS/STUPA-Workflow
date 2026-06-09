import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApplicationsListComponent } from './applications-list.component';
import { USE_MOCK_API } from '@core/api/api.config';
import type {
  ApplicationListItemWire,
  ApplicationTypeListItemWire,
  Page,
  StateOutWire,
} from '@core/api/models';

const OPEN_STATE: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};

const TYPES: Page<ApplicationTypeListItemWire> = {
  items: [{ id: 't1', name: 'Finanzantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' }],
  total: 1,
  limit: 20,
  offset: 0,
};

function listPage(items: ApplicationListItemWire[], total = items.length): Page<ApplicationListItemWire> {
  return { items, total, limit: 20, offset: 0 };
}

const ITEM: ApplicationListItemWire = {
  id: 'app-1',
  typeId: 't1',
  title: 'Mein Antrag',
  state: OPEN_STATE,
  gremiumId: null,
  budgetPotId: null,
  amount: '250.00',
  currency: 'EUR',
  createdAt: '2026-05-30T09:00:00Z',
  updatedAt: '2026-05-30T09:00:00Z',
};

const ITEM2: ApplicationListItemWire = { ...ITEM, id: 'app-2', title: 'Zweiter Antrag' };

async function setup() {
  const view = await render(ApplicationsListComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const router = view.fixture.debugElement.injector.get(Router);
  // Der Kostenstellen-Baum (linker Filter) wird im Konstruktor eager geladen.
  flushBudgets(http);
  return { ...view, http, router };
}

function flushTypes(http: HttpTestingController) {
  http.expectOne('/api/application-types').flush(TYPES);
}

/** Kostenstellen-Baum (linker Filter-Picker) — eager im Konstruktor geladen. */
function flushBudgets(http: HttpTestingController) {
  for (const req of http.match((r) => r.url === '/api/budgets')) req.flush([]);
}

describe('ApplicationsListComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders a row per application with type name, state badge and amount', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    expect(screen.getByRole('heading', { name: 'Anträge', level: 1 })).toBeInTheDocument();
    // state appears both as the row badge and as a real status filter option (#review2 §2)
    const badge = screen.getAllByText('Eingereicht').find((el) => el.tagName !== 'OPTION');
    expect(badge).toBeTruthy();
    expect(screen.getByText(/250/)).toBeInTheDocument();
    // type name shows as a plain cell (and in the filter <option>)
    expect(screen.getAllByText('Finanzantrag').length).toBeGreaterThan(0);
    // the row link now carries the application title and points at the detail route
    const link = screen.getByRole('link', { name: /Mein Antrag/ });
    expect(link).toHaveAttribute('href', '/applications/app-1');
    http.verify();
  });

  it('offers the real loaded states as status filter options with the state UUID as value (#review2 §2)', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);

    // The status filter is a dropdown (not free text); option label = state name,
    // option value = the backend state UUID (sent filter value unchanged).
    const option = screen.getByRole('option', { name: 'Eingereicht' }) as HTMLOptionElement;
    expect(option.value).toBe('s1');
    http.verify();
  });

  it('shows the empty state when no applications match', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([], 0));
    detectChanges();
    expect(screen.getByText('Keine Anträge gefunden.')).toBeInTheDocument();
    http.verify();
  });

  it('renders an error message when the list request fails', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http
      .expectOne((r) => r.url === '/api/applications')
      .flush(null, { status: 500, statusText: 'Server Error' });
    detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('Anträge konnten nicht geladen werden.');
    http.verify();
  });

  it('sends the current filter values as query params on submit', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);
    await userEvent.type(screen.getByLabelText('Suche'), 'Beamer');
    await userEvent.click(screen.getByRole('button', { name: 'Filtern' }));

    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: expect.objectContaining({ q: 'Beamer', offset: null }),
        queryParamsHandling: 'merge',
      }),
    );
    http.verify();
  });

  it('requests the first page and shows the count + "load more" when more exist', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    // 50 total, only 1 loaded so far → infinite-scroll fallback button visible.
    const req = http.expectOne((r) => r.url === '/api/applications');
    expect(req.request.params.get('limit')).toBe('20');
    expect(req.request.params.get('offset')).toBe('0');
    req.flush(listPage([ITEM], 50));
    detectChanges();

    expect(screen.getByText('1 von 50')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mehr laden' })).toBeEnabled();
    http.verify();
  });

  it('appends the next page on "load more" (infinite scroll)', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM], 50));
    detectChanges();

    await userEvent.click(screen.getByRole('button', { name: 'Mehr laden' }));
    // Nächster Offset = bisher geladene Trefferzahl (hier 1), Filter bleiben erhalten.
    const more = http.expectOne((r) => r.url === '/api/applications');
    expect(more.request.params.get('offset')).toBe('1');
    more.flush(listPage([ITEM2], 50));
    detectChanges();

    expect(screen.getByRole('link', { name: /Mein Antrag/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Zweiter Antrag/ })).toBeInTheDocument();
    expect(screen.getByText('2 von 50')).toBeInTheDocument();
    http.verify();
  });

  it('clears every filter param on reset', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);
    await userEvent.click(screen.getByRole('button', { name: 'Zurücksetzen' }));
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: {
          q: null, type: null, state: null, gremium: null, topf: null, budget: null,
          amountMin: null, amountMax: null, createdFrom: null, createdTo: null, offset: null,
        },
      }),
    );
    http.verify();
  });

  it('sorts by amount when the Amount header is clicked', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: /Betrag/ }));
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: expect.objectContaining({ sort: 'amount', order: 'desc', offset: null }),
      }),
    );
    http.verify();
  });

  it('sends amount range and date filters on submit', async () => {
    const { http, detectChanges, router } = await setup();
    flushTypes(http);
    http.expectOne((r) => r.url === '/api/applications').flush(listPage([ITEM]));
    detectChanges();

    const navigate = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Filter' }));
    flushBudgets(http);
    await userEvent.type(screen.getByLabelText('Min'), '100');
    await userEvent.type(screen.getByLabelText('Max'), '500');
    await userEvent.click(screen.getByRole('button', { name: 'Filtern' }));
    expect(navigate).toHaveBeenCalledWith(
      [],
      expect.objectContaining({
        queryParams: expect.objectContaining({ amountMin: 100, amountMax: 500, offset: null }),
      }),
    );
    http.verify();
  });

  it('renders a dash for a missing amount', async () => {
    const { http, detectChanges } = await setup();
    flushTypes(http);
    http
      .expectOne((r) => r.url === '/api/applications')
      .flush(listPage([{ ...ITEM, amount: null }]));
    detectChanges();
    // amount cell falls back to the "not provided" dash
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    http.verify();
  });
});
