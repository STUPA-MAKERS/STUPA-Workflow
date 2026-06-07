import { render, screen } from '@testing-library/angular';
import { VoteBarsComponent } from './vote-bars.component';

async function renderBars(inputs: Record<string, unknown>) {
  return render(VoteBarsComponent, { inputs });
}

describe('VoteBarsComponent', () => {
  it('renders one bar per option with translated labels and counts', async () => {
    await renderBars({
      options: ['yes', 'no', 'abstain'],
      counts: { yes: 5, no: 2, abstain: 1 },
      eligible: 12,
      leading: 'yes',
    });
    expect(screen.getByText('Ja')).toBeInTheDocument();
    expect(screen.getByText('Nein')).toBeInTheDocument();
    expect(screen.getByText('Enthaltung')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('scales bar width relative to eligible voters', async () => {
    const { container } = await renderBars({
      options: ['yes', 'no'],
      counts: { yes: 6, no: 0 },
      eligible: 12,
      leading: 'yes',
    });
    const fill = container.querySelector('.bars__fill') as HTMLElement;
    expect(fill.style.width).toBe('50%'); // 6 / 12
  });

  it('falls back to scaling by maximum when eligible is unknown', async () => {
    const { container } = await renderBars({
      options: ['yes', 'no'],
      counts: { yes: 4, no: 2 },
      eligible: 0,
    });
    const fills = container.querySelectorAll('.bars__fill');
    expect((fills[0] as HTMLElement).style.width).toBe('100%'); // max
    expect((fills[1] as HTMLElement).style.width).toBe('50%');
  });

  it('marks the leading option', async () => {
    const { container } = await renderBars({
      options: ['yes', 'no'],
      counts: { yes: 3, no: 1 },
      leading: 'yes',
    });
    expect(container.querySelector('.bars__row--leading .bars__label')?.textContent).toContain('Ja');
  });

  it('keeps raw key for unknown options (no leak of i18n key)', async () => {
    await renderBars({ options: ['maybe'], counts: { maybe: 1 } });
    expect(screen.getByText('maybe')).toBeInTheDocument();
  });

  it('exposes accessible progressbar semantics without names', async () => {
    await renderBars({
      options: ['yes'],
      counts: { yes: 5 },
      eligible: 12,
    });
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '5');
    expect(bar).toHaveAttribute('aria-valuemax', '12');
    expect(bar).toHaveAttribute('aria-label', 'Ja: 5');
  });
});
