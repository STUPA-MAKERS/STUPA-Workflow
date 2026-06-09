import { render, screen } from '@testing-library/angular';
import { BadgeComponent, readableTextColor } from './badge.component';

describe('BadgeComponent', () => {
  it('renders content with the default neutral variant', async () => {
    await render(`<app-badge>Entwurf</app-badge>`, { imports: [BadgeComponent] });
    const badge = screen.getByText('Entwurf');
    expect(badge).toHaveClass('badge--neutral');
  });

  it('applies the requested variant class', async () => {
    await render(`<app-badge variant="success">Angenommen</app-badge>`, {
      imports: [BadgeComponent],
    });
    expect(screen.getByText('Angenommen')).toHaveClass('badge--success');
  });

  it('overrides the variant with a custom background and readable text color', async () => {
    // Light background → dark text.
    await render(`<app-badge color="#ffee88">Hell</app-badge>`, { imports: [BadgeComponent] });
    const badge = screen.getByText('Hell');
    expect(badge).toHaveClass('badge--custom');
    expect(badge).not.toHaveClass('badge--neutral');
    expect(badge.style.background).toBe('rgb(255, 238, 136)');
    expect(badge.style.color).toBe('rgb(26, 26, 26)');
  });

  it('uses white text on a dark custom background', async () => {
    await render(`<app-badge color="#222266">Dunkel</app-badge>`, { imports: [BadgeComponent] });
    expect(screen.getByText('Dunkel').style.color).toBe('rgb(255, 255, 255)');
  });

  it('falls back to the variant when no color is set', async () => {
    await render(`<app-badge variant="info">Ohne</app-badge>`, { imports: [BadgeComponent] });
    const badge = screen.getByText('Ohne');
    expect(badge).toHaveClass('badge--info');
    expect(badge.style.background).toBe('');
  });
});

describe('readableTextColor', () => {
  it('returns dark text for light colors and white for dark ones', () => {
    expect(readableTextColor('#ffffff')).toBe('#1a1a1a');
    expect(readableTextColor('#000000')).toBe('#ffffff');
    expect(readableTextColor('#fff')).toBe('#1a1a1a');
  });

  it('returns null for missing/invalid input', () => {
    expect(readableTextColor(null)).toBeNull();
    expect(readableTextColor('')).toBeNull();
    expect(readableTextColor('not-a-color')).toBeNull();
  });
});
