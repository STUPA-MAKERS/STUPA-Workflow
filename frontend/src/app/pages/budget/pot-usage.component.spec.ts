import { render, screen } from '@testing-library/angular';
import type { PotUsage } from '@core/api/models';
import { PotUsageComponent } from './pot-usage.component';

function pot(overrides: Partial<PotUsage> = {}): PotUsage {
  return {
    budgetPotId: 'p1',
    name: 'Veranstaltungen',
    period: '2026',
    total: 10000,
    currency: 'EUR',
    requested: 4200,
    reserved: 1500,
    approved: 3000,
    paid: 2000,
    committed: 6500,
    available: 3500,
    ...overrides,
  };
}

describe('PotUsageComponent', () => {
  it('renders one bar per pot with its name and usage ratio', async () => {
    await render(PotUsageComponent, { inputs: { pots: [pot()] } });
    // Name erscheint im Balken-Kopf und in der Tabellen-Zeile.
    expect(screen.getAllByText('Veranstaltungen').length).toBeGreaterThan(0);
    expect(screen.getByText('65%')).toBeInTheDocument(); // 6500 / 10000
  });

  it('emits committed segments scaled to the pot total', async () => {
    const { container } = await render(PotUsageComponent, { inputs: { pots: [pot()] } });
    const paid = container.querySelector('.usage__seg--paid') as HTMLElement;
    const approved = container.querySelector('.usage__seg--approved') as HTMLElement;
    expect(paid.style.width).toBe('20%'); // 2000 / 10000
    expect(approved.style.width).toBe('30%'); // 3000 / 10000
  });

  it('gives the utilisation bar an accessible image label', async () => {
    await render(PotUsageComponent, { inputs: { pots: [pot()] } });
    const bar = screen.getByRole('img');
    expect(bar.getAttribute('aria-label')).toContain('Veranstaltungen');
    expect(bar.getAttribute('aria-label')).toMatch(/gebunden/);
  });

  it('marks an unlimited pot instead of a percentage', async () => {
    await render(PotUsageComponent, {
      inputs: { pots: [pot({ total: null, available: null })] },
    });
    expect(screen.getAllByText('ohne Limit').length).toBeGreaterThan(0);
  });

  it('flags an overcommitted pot', async () => {
    await render(PotUsageComponent, {
      inputs: { pots: [pot({ total: 1000, committed: 6500, available: 0 })] },
    });
    expect(screen.getByText('Überzeichnet')).toBeInTheDocument();
  });

  it('renders the accessible table fallback for every pot', async () => {
    await render(PotUsageComponent, { inputs: { pots: [pot()] } });
    // Stufen-Spaltenköpfe der Tabelle existieren (Diagramm-Alternativtext).
    expect(screen.getByText('Reserviert')).toBeInTheDocument();
    expect(screen.getByText('Bewilligt')).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'Veranstaltungen' })).toBeInTheDocument();
  });

  it('shows an empty hint when no pots are present', async () => {
    await render(PotUsageComponent, { inputs: { pots: [] } });
    expect(screen.getByText('Keine Töpfe für die aktuelle Auswahl.')).toBeInTheDocument();
  });
});
