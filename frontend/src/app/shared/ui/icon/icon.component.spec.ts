import { render } from '@testing-library/angular';
import { IconComponent } from './icon.component';

describe('IconComponent', () => {
  it('renders a decorative svg that inherits currentColor', async () => {
    const { container } = await render(`<app-icon name="sun" />`, { imports: [IconComponent] });
    const svg = container.querySelector('svg');
    expect(svg).toBeTruthy();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(svg).toHaveAttribute('stroke', 'currentColor');
  });

  it('renders the moon glyph (single path) for the moon icon', async () => {
    const { container } = await render(`<app-icon name="moon" />`, { imports: [IconComponent] });
    expect(container.querySelectorAll('svg path').length).toBe(1);
  });

  it('honours the size input', async () => {
    const { container } = await render(`<app-icon name="sun" [size]="32" />`, {
      imports: [IconComponent],
    });
    expect(container.querySelector('svg')).toHaveAttribute('width', '32');
  });
});
