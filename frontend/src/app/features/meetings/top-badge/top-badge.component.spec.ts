import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render } from '@testing-library/angular';
import { TopBadgeComponent } from './top-badge.component';

describe('TopBadgeComponent', () => {
  it('shows the number of an open item', async () => {
    const { container } = await render(`<app-top-badge [number]="3" />`, { imports: [TopBadgeComponent] });
    const badge = container.querySelector('app-top-badge')!;
    expect(badge.textContent?.trim()).toBe('3');
    expect(badge).not.toHaveClass('tb--now');
    expect(badge).not.toHaveAttribute('aria-hidden');
  });

  it('fills the current item and rings a done one with a check', async () => {
    const { container, rerender } = await render(`<app-top-badge [number]="3" [state]="state" decorative />`, {
      imports: [TopBadgeComponent],
      componentProperties: { state: 'now' as 'now' | 'done' },
    });
    const badge = container.querySelector('app-top-badge')!;
    expect(badge).toHaveClass('tb--now');
    expect(badge).toHaveAttribute('aria-hidden', 'true');
    await rerender({ componentProperties: { state: 'done' } });
    expect(badge).toHaveClass('tb--done');
    expect(badge.querySelector('app-icon')).not.toBeNull();
    expect(badge.textContent?.trim()).toBe('');
  });

  it('shows a lock for a non-public item in any state', async () => {
    const { container } = await render(`<app-top-badge [number]="2" state="now" lock [iconSize]="15" />`, {
      imports: [TopBadgeComponent],
    });
    const badge = container.querySelector('app-top-badge')!;
    expect(badge).toHaveClass('tb--now');
    expect(badge.querySelector('app-icon')).not.toBeNull();
    expect(badge.textContent?.trim()).toBe('');
  });

  it('lets the page set the size, the type size and the digits', () => {
    const scss = readFileSync(join(__dirname, 'top-badge.component.scss'), 'utf8');
    expect(scss).toContain('width: var(--tb-size, 2rem)');
    expect(scss).toContain('font-size: var(--tb-font, 0.75rem)');
    expect(scss).toContain('font-variant-numeric: var(--tb-nums, tabular-nums)');
  });
});
