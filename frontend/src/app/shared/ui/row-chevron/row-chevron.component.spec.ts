import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render } from '@testing-library/angular';
import { RowChevronComponent } from './row-chevron.component';

describe('RowChevronComponent', () => {
  it('is a decorative right arrow, 17px by default', async () => {
    const { container } = await render(`<app-row-chevron />`, { imports: [RowChevronComponent] });
    const icon = container.querySelector('app-row-chevron app-icon') as HTMLElement;
    expect(icon.style.getPropertyValue('--icon-size')).toBe('17px');
    expect(container.querySelector('app-row-chevron')?.textContent?.trim()).toBe('');
  });

  it('takes another size', async () => {
    const { container } = await render(`<app-row-chevron [size]="16" />`, { imports: [RowChevronComponent] });
    expect((container.querySelector('app-icon') as HTMLElement).style.getPropertyValue('--icon-size')).toBe('16px');
  });

  it('is quiet and pulls into the end padding of the row', () => {
    const scss = readFileSync(join(__dirname, 'row-chevron.component.scss'), 'utf8');
    expect(scss).toContain('margin-inline-end: calc(-1 * var(--space-2))');
    expect(scss).toContain('color: var(--color-text-muted)');
  });
});
