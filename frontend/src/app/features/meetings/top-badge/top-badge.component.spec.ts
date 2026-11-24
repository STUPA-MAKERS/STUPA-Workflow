import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render } from '@testing-library/angular';
import { TopBadgeViewComponent } from '@stupa-makers/ui-kit/views/meeting';

describe('TopBadgeViewComponent', () => {
  it('shows the number of an open item', async () => {
    const { container } = await render(`<app-top-badge-view [number]="3" />`, {
      imports: [TopBadgeViewComponent],
    });
    const badge = container.querySelector('app-top-badge-view')!;
    expect(badge.textContent?.trim()).toBe('3');
    expect(badge).not.toHaveClass('tb--now');
    expect(badge).not.toHaveAttribute('aria-hidden');
  });

  it('fills the current item and rings a done one with a check', async () => {
    const { container, rerender } = await render(
      `<app-top-badge-view [number]="3" [state]="state" decorative />`,
      {
        imports: [TopBadgeViewComponent],
        componentProperties: { state: 'now' as 'now' | 'done' },
      },
    );
    const badge = container.querySelector('app-top-badge-view')!;
    expect(badge).toHaveClass('tb--now');
    expect(badge).toHaveAttribute('aria-hidden', 'true');
    await rerender({ componentProperties: { state: 'done' } });
    expect(badge).toHaveClass('tb--done');
    expect(badge.querySelector('app-icon')).not.toBeNull();
    expect(badge.textContent?.trim()).toBe('');
  });

  it('shows a lock for a non-public item in any state', async () => {
    const { container } = await render(
      `<app-top-badge-view [number]="2" state="now" lock [iconSize]="15" />`,
      {
        imports: [TopBadgeViewComponent],
      },
    );
    const badge = container.querySelector('app-top-badge-view')!;
    expect(badge).toHaveClass('tb--now');
    expect(badge.querySelector('app-icon')).not.toBeNull();
    expect(badge.textContent?.trim()).toBe('');
  });

  it('lets the page set the size, the type size and the digits', () => {
    const scss = readFileSync(
      join(
        __dirname,
        '../../../../../vendor/ui-kit/views/meeting/src/top-badge-view.component.scss',
      ),
      'utf8',
    );
    expect(scss).toContain('width: var(--tb-size, 2rem)');
    expect(scss).toContain('font-size: var(--tb-font, 0.75rem)');
    expect(scss).toContain('font-variant-numeric: var(--tb-nums, tabular-nums)');
  });
});
