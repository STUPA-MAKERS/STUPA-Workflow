import { render, screen } from '@testing-library/angular';
import type { StatusBucket } from '@core/api/models';
import { StatusDistributionComponent } from './status-distribution.component';

const BUCKETS: StatusBucket[] = [
  { gremiumId: 'g1', stateId: 's-submitted', count: 7 },
  { gremiumId: 'g1', stateId: 's-review', count: 4 },
  { gremiumId: 'g2', stateId: 's-submitted', count: 3 },
];

describe('StatusDistributionComponent', () => {
  it('aggregates counts per state across bodies and scales the bars', async () => {
    const { container } = await render(StatusDistributionComponent, {
      inputs: { buckets: BUCKETS },
    });
    // submitted = 7 + 3 = 10 (max → 100%), review = 4 (40%)
    expect(screen.getByText('10')).toBeInTheDocument();
    const fills = container.querySelectorAll('.status__fill');
    expect((fills[0] as HTMLElement).style.width).toBe('100%');
    expect((fills[1] as HTMLElement).style.width).toBe('40%');
  });

  it('gives each bar an accessible image label', async () => {
    await render(StatusDistributionComponent, { inputs: { buckets: BUCKETS } });
    const bars = screen.getAllByRole('img');
    expect(bars[0].getAttribute('aria-label')).toMatch(/: 10$/);
  });

  it('renders the cross-tab fallback with a total row', async () => {
    await render(StatusDistributionComponent, { inputs: { buckets: BUCKETS } });
    expect(screen.getByText('14')).toBeInTheDocument(); // 7 + 4 + 3
  });

  it('labels buckets without a body/state with a fallback', async () => {
    await render(StatusDistributionComponent, {
      inputs: { buckets: [{ gremiumId: null, stateId: null, count: 2 }] },
    });
    expect(screen.getByText('Ohne Gremium')).toBeInTheDocument();
    expect(screen.getAllByText('Ohne Status').length).toBeGreaterThan(0);
  });

  it('shows an empty hint when there are no applications', async () => {
    await render(StatusDistributionComponent, { inputs: { buckets: [] } });
    expect(screen.getByText('Keine Anträge für die aktuelle Auswahl.')).toBeInTheDocument();
  });
});
