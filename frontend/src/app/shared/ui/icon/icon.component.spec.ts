import { render } from '@testing-library/angular';
import { IconComponent } from './icon.component';

describe('IconComponent', () => {
  it('renders a decorative Font Awesome solid glyph', async () => {
    const { container } = await render(`<app-icon name="sun" />`, { imports: [IconComponent] });
    const i = container.querySelector('i');
    expect(i).toBeTruthy();
    expect(i).toHaveAttribute('aria-hidden', 'true');
    expect(i).toHaveClass('fa-solid');
    expect(i).toHaveClass('fa-sun');
  });

  it('maps the icon name to its FA class', async () => {
    const { container } = await render(`<app-icon name="webhook" />`, { imports: [IconComponent] });
    expect(container.querySelector('i')).toHaveClass('fa-globe');
  });

  it('honours the size input (font-size)', async () => {
    const { container } = await render(`<app-icon name="sun" [size]="32" />`, {
      imports: [IconComponent],
    });
    expect((container.querySelector('i') as HTMLElement).style.fontSize).toBe('32px');
  });
});
