import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { CostCentreLabelComponent } from './cost-centre-label.component';

describe('CostCentreLabelComponent', () => {
  it('shows a hidden colour mark before the name', async () => {
    const { container } = await render(`<app-cost-centre-label name="Kultur" color="#ff8800" />`, {
      imports: [CostCentreLabelComponent],
    });
    expect(screen.getByText('Kultur')).toBeInTheDocument();
    const mark = container.querySelector('.ccl__mark') as HTMLElement;
    expect(mark).toHaveAttribute('aria-hidden', 'true');
    expect(mark.style.background).toBe('rgb(255, 136, 0)');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows only the name without a colour', async () => {
    const { container } = await render(`<app-cost-centre-label name="AStA › Kultur" [color]="null" />`, {
      imports: [CostCentreLabelComponent],
    });
    expect(container.querySelector('.ccl__mark')).toBeNull();
    expect(container.textContent?.trim()).toBe('AStA › Kultur');
  });

  it('is inline text with a mark on the baseline, sized by the page', () => {
    const scss = readFileSync(join(__dirname, 'cost-centre-label.component.scss'), 'utf8');
    expect(scss).toMatch(/:host \{\s*display: inline;/);
    expect(scss).toContain('var(--ccl-size, 10px)');
    expect(scss).toContain('margin-inline-end: var(--ccl-gap, 6px)');
    expect(scss).toContain('vertical-align: 0');
  });
});
