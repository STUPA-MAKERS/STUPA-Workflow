import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { BudgetPotOutWire, BudgetStatsOutWire } from '@core/api/models';
import { BudgetDashboardComponent } from './budget-dashboard.component';

const POTS: BudgetPotOutWire[] = [
  {
    id: 'pot-events',
    gremiumId: 'g1',
    name: 'Veranstaltungen',
    total: '10000.00',
    currency: 'EUR',
    period: '2026',
    active: true,
  },
];

const STATS: BudgetStatsOutWire = {
  pots: [
    {
      budgetPotId: 'pot-events',
      period: '2026',
      total: '10000.00',
      currency: 'EUR',
      requested: '4200.00',
      reserved: '1500.00',
      approved: '3000.00',
      paid: '2000.00',
      committed: '6500.00',
      available: '3500.00',
    },
  ],
  statusDistribution: [{ gremiumId: 'g1', stateId: 's1', count: 5 }],
};

const EMPTY_STATS: BudgetStatsOutWire = { pots: [], statusDistribution: [] };

async function setup() {
  const view = await render(BudgetDashboardComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  // Gremien-Dropdown (#77) lädt beim Start `/admin/gremien` — neutral flushen.
  http.match((r) => r.url.endsWith('/admin/gremien')).forEach((req) => req.flush([]));
  return { ...view, http };
}

/** Töpfe (best-effort) dann Stats beantworten — Reihenfolge des `switchMap`. */
function answer(http: HttpTestingController, pots: BudgetPotOutWire[], stats: BudgetStatsOutWire) {
  http.expectOne((r) => r.url.endsWith('/budget-pots')).flush(pots);
  http.expectOne((r) => r.url.endsWith('/budget/stats')).flush(stats);
}

describe('BudgetDashboardComponent', () => {
  it('loads real /budget/stats and renders KPI cards', async () => {
    const { http, fixture } = await setup();
    answer(http, POTS, STATS);
    fixture.detectChanges();

    // KPI-Labels gerendert; committed-Betrag erscheint (Karte + Topf-Zahlen + Tabelle).
    expect(screen.getByText('Anträge')).toBeInTheDocument(); // nur als KPI-Label
    expect(screen.getAllByText('Gebunden').length).toBeGreaterThan(0);
    expect(screen.getAllByText('6.500,00 €').length).toBeGreaterThan(0);
    http.verify();
  });

  it('enriches pot names from /budget-pots', async () => {
    const { http, fixture } = await setup();
    answer(http, POTS, STATS);
    fixture.detectChanges();
    expect(screen.getAllByText('Veranstaltungen').length).toBeGreaterThan(0);
    http.verify();
  });

  it('falls back to a shortened id when /budget-pots is forbidden (403)', async () => {
    const { http, fixture } = await setup();
    http
      .expectOne((r) => r.url.endsWith('/budget-pots'))
      .flush({ title: 'forbidden' }, { status: 403, statusText: 'Forbidden' });
    http.expectOne((r) => r.url.endsWith('/budget/stats')).flush(STATS);
    fixture.detectChanges();
    expect(screen.getAllByText('pot-even…').length).toBeGreaterThan(0);
    http.verify();
  });

  it('shows the empty state when there are no pots and no applications', async () => {
    const { http, fixture } = await setup();
    answer(http, [], EMPTY_STATS);
    fixture.detectChanges();
    expect(screen.getByText('Noch keine Budgetdaten')).toBeInTheDocument();
    http.verify();
  });

  it('applies the period filter to the stats request', async () => {
    const { http, fixture } = await setup();
    answer(http, POTS, STATS);
    fixture.detectChanges();

    await userEvent.type(screen.getByLabelText('Zeitraum'), '2026');
    await userEvent.click(screen.getByRole('button', { name: 'Anwenden' }));

    // Navigation aktualisiert die Query-Params → erneuter Lade-Zyklus.
    http.expectOne((r) => r.url.endsWith('/budget-pots')).flush(POTS);
    const statsReq = http.expectOne((r) => r.url.endsWith('/budget/stats'));
    expect(statsReq.request.params.get('period')).toBe('2026');
    statsReq.flush(STATS);
    http.verify();
  });

  it('shows an error when the stats request fails', async () => {
    const { http, fixture } = await setup();
    http.expectOne((r) => r.url.endsWith('/budget-pots')).flush([]);
    http
      .expectOne((r) => r.url.endsWith('/budget/stats'))
      .flush({ title: 'boom' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('konnte nicht geladen werden');
    http.verify();
  });
});
