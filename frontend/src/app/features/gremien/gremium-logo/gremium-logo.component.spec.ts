import { fireEvent, render } from '@testing-library/angular';
import { GremiumLogoComponent } from './gremium-logo.component';

describe('GremiumLogoComponent', () => {
  it('shows the initials without a logo', async () => {
    const { container } = await render(GremiumLogoComponent, { inputs: { name: 'Studierendenparlament' } });
    const host = container as HTMLElement;
    expect(host.querySelector('img')).toBeNull();
    expect(host.textContent?.trim()).toBe('ST');
    expect(host.getAttribute('aria-hidden')).toBe('true');
    expect(host.classList.contains('glo--lg')).toBe(false);
  });

  it('shows the logo on white and falls back to the initials when it fails', async () => {
    const view = await render(GremiumLogoComponent, {
      inputs: { name: 'Wahlausschuss', logoUrl: '/api/gremien/g-1/logo', size: 'lg' },
    });
    const host = view.container as HTMLElement;
    const img = host.querySelector('img');
    expect(img?.getAttribute('src')).toBe('/api/gremien/g-1/logo');
    expect(img?.getAttribute('alt')).toBe('');
    expect(host.classList.contains('glo--img')).toBe(true);
    expect(host.classList.contains('glo--lg')).toBe(true);

    fireEvent.error(img as HTMLImageElement);
    view.fixture.detectChanges();
    expect(host.querySelector('img')).toBeNull();
    expect(host.textContent?.trim()).toBe('WA');

    // A new URL gets a new try.
    view.fixture.componentRef.setInput('logoUrl', '/api/gremien/g-2/logo');
    view.fixture.detectChanges();
    expect(host.querySelector('img')?.getAttribute('src')).toBe('/api/gremien/g-2/logo');
  });
});
