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

  it('defaults the size to 18px when no size is given', async () => {
    const { container } = await render(`<app-icon name="sun" />`, { imports: [IconComponent] });
    expect((container.querySelector('i') as HTMLElement).style.fontSize).toBe('18px');
  });

  it('falls back to fa-circle-question for an unknown icon name', async () => {
    // Cast an out-of-catalog value to exercise the FA[...] ?? fallback branch.
    const { container } = await render(`<app-icon [name]="name" />`, {
      imports: [IconComponent],
      componentProperties: { name: 'does-not-exist' as never },
    });
    expect(container.querySelector('i')).toHaveClass('fa-circle-question');
  });

  it('updates the rendered glyph when the name input changes', async () => {
    const view = await render(`<app-icon [name]="name" />`, {
      imports: [IconComponent],
      componentProperties: { name: 'sun' as const },
    });
    expect(view.container.querySelector('i')).toHaveClass('fa-sun');
    view.rerender({ componentProperties: { name: 'moon' as const } });
    expect(view.container.querySelector('i')).toHaveClass('fa-moon');
  });
});
