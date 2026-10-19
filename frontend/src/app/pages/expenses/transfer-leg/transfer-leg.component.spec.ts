import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { TransferLegComponent } from './transfer-leg.component';

describe('TransferLegComponent', () => {
  it('shows the expense leg with a mark, the path and a minus amount', async () => {
    const { container } = await render(
      `<app-transfer-leg direction="out" name="Kultur" color="#ff8800" path="AStA › Kultur" amount="12,00 €" fit />`,
      { imports: [TransferLegComponent] },
    );
    expect(screen.getByText('Ausgabe auf')).toBeInTheDocument();
    expect(screen.getByText('Kultur')).toBeInTheDocument();
    expect(screen.getByText('AStA › Kultur')).toBeInTheDocument();
    expect(screen.getByText('−12,00 €')).not.toHaveClass('tl__amount--in');
    expect(container.querySelector('.tl__swatch')).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelector('app-transfer-leg')).toHaveClass('tl--fit');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the income leg with the amount that stays and no mark', async () => {
    const { container } = await render(
      `<app-transfer-leg direction="in" name="Sport" path="AStA › Sport" amount="12,00 €" after="88,00 €" />`,
      { imports: [TransferLegComponent] },
    );
    expect(screen.getByText('Einnahme auf')).toBeInTheDocument();
    expect(screen.getByText('+12,00 €')).toHaveClass('tl__amount--in');
    expect(container.querySelector('.tl__path')?.textContent).toContain('verfügbar danach 88,00 €');
    expect(container.querySelector('.tl__swatch')).toBeNull();
    expect(container.querySelector('app-transfer-leg')).not.toHaveClass('tl--fit');
  });

  it('takes its card colour from the page and sizes a fitted amount by the card', () => {
    const scss = readFileSync(join(__dirname, 'transfer-leg.component.scss'), 'utf8');
    expect(scss).toContain('background: var(--leg-bg, var(--color-surface-2))');
    expect(scss).toMatch(/:host\(\.tl--fit\) \{\s*container-type: inline-size;/);
    expect(scss).toContain('clamp(var(--fs-sm), 12cqi, var(--fs-xl))');
  });
});
