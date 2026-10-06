import { signal } from '@angular/core';
import { render, screen } from '@testing-library/angular';
import { BrandingService } from '@core/branding/branding.service';
import { runAxe } from '../../../../testing/a11y';
import { AvatarComponent, AvatarStackComponent, initials } from './avatar.component';

describe('initials', () => {
  it.each([
    ['Mara Keller', 'MK'],
    ['Paul', 'P'],
    ['Anna-Lena von Stein', 'AS'],
    ['  jonas   weber ', 'JW'],
    ['Erika Beispiel (erika@example.org)', 'EB'],
    ['"Öztürk" Ümit', 'ÖÜ'],
    ['', '?'],
    ['()', '?'],
  ])('%s gives %s', (name, letters) => {
    expect(initials(name)).toBe(letters);
  });
});

describe('AvatarComponent', () => {
  it('shows the initials and names the person', async () => {
    const { container } = await render(AvatarComponent, { inputs: { name: 'Mara Keller' } });
    const img = screen.getByRole('img', { name: 'Mara Keller' });
    expect(img).toHaveTextContent('MK');
    expect(img).toHaveAttribute('title', 'Mara Keller');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('hides itself from screen readers when it is decorative', async () => {
    const view = await render(AvatarComponent, {
      inputs: { name: 'Mara Keller', decorative: true },
    });
    const host = view.fixture.nativeElement as HTMLElement;
    expect(screen.queryByRole('img')).toBeNull();
    expect(host).toHaveAttribute('aria-hidden', 'true');
  });

  it('carries the size and accent classes', async () => {
    const view = await render(AvatarComponent, {
      inputs: { name: 'Mara Keller', size: 'sm', accent: true },
    });
    const host = view.fixture.nativeElement as HTMLElement;
    expect(host).toHaveClass('av--sm');
    expect(host).toHaveClass('av--accent');
  });
});

describe('AvatarComponent with an image', () => {
  const branding = () => ({ loaded: signal(true), gravatarEnabled: signal(true) });

  async function renderWithImage(inputs: Record<string, unknown>) {
    const view = await render(AvatarComponent, {
      inputs: { name: 'Mara Keller', ...inputs },
      providers: [{ provide: BrandingService, useValue: branding() }],
    });
    const host = view.fixture.nativeElement as HTMLElement;
    const img = () => host.querySelector('img');
    return { view, host, img };
  }

  it('loads the proxy image over the initials, hidden until it has loaded', async () => {
    const { view, host, img } = await renderWithImage({ principalId: 'p-1', size: 'sm' });
    expect(img()).toHaveAttribute('src', '/api/principals/p-1/avatar?s=64');
    expect(img()).toHaveAttribute('alt', '');
    expect(img()).not.toHaveClass('av__img--on');
    expect(host).not.toHaveClass('av--img');
    // The initials stay in the DOM: they are the fallback and keep the size.
    expect(host.querySelector('.av__letters')).toHaveTextContent('MK');

    img()!.dispatchEvent(new Event('load'));
    view.fixture.detectChanges();
    expect(img()).toHaveClass('av__img--on');
    expect(host).toHaveClass('av--img');
    // The accessible name stays the name of the person.
    expect(screen.getByRole('img', { name: 'Mara Keller' })).toBe(host);
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('falls back to the initials when the image fails', async () => {
    const { view, host, img } = await renderWithImage({ principalId: 'p-2' });
    expect(img()).toHaveAttribute('src', '/api/principals/p-2/avatar?s=80');
    img()!.dispatchEvent(new Event('error'));
    view.fixture.detectChanges();
    expect(img()).toBeNull();
    expect(host).not.toHaveClass('av--img');
    expect(host).toHaveTextContent('MK');
  });

  it('starts hidden again for a new person', async () => {
    const { view, host, img } = await renderWithImage({ principalId: 'p-3' });
    img()!.dispatchEvent(new Event('load'));
    view.fixture.detectChanges();
    expect(host).toHaveClass('av--img');
    view.fixture.componentRef.setInput('principalId', 'p-4');
    view.fixture.detectChanges();
    expect(img()).toHaveAttribute('src', '/api/principals/p-4/avatar?s=80');
    expect(host).not.toHaveClass('av--img');
  });

  it('shows only the initials without a principal', async () => {
    const { img } = await renderWithImage({});
    expect(img()).toBeNull();
  });

  it('ignores an error without a principal id', async () => {
    const { view } = await renderWithImage({ principalId: 'p-5' });
    const cmp = view.fixture.componentInstance as unknown as { onError(): void };
    view.fixture.componentRef.setInput('principalId', null);
    expect(() => cmp.onError()).not.toThrow();
  });
});

describe('AvatarStackComponent', () => {
  const NAMES = [
    'Mara Keller',
    'Jonas Weber',
    'Paul Neumann',
    'Erika Beispiel',
    'Lea Roth',
    'Tom Fink',
  ];

  it('draws every person when they fit', async () => {
    const { container } = await render(AvatarStackComponent, {
      inputs: { names: NAMES.slice(0, 3) },
    });
    expect(container.querySelectorAll('app-avatar')).toHaveLength(3);
    expect(container.querySelector('.stack__rest')).toBeNull();
    expect(
      screen.getByRole('img', { name: 'Mara Keller, Jonas Weber, Paul Neumann' }),
    ).toBeTruthy();
  });

  it('draws the first ones and counts the rest', async () => {
    const { container } = await render(AvatarStackComponent, {
      inputs: { names: NAMES, max: 4, size: 'md' },
    });
    expect(container.querySelectorAll('app-avatar')).toHaveLength(4);
    expect(container.querySelector('.stack__rest')).toHaveTextContent('+2');
    expect(container.querySelector('.stack__rest')).not.toHaveClass('av--sm');
    expect(
      screen.getByRole('img', {
        name: 'Mara Keller, Jonas Weber, Paul Neumann, Erika Beispiel, 2 weitere',
      }),
    ).toBeTruthy();
  });

  it('is one image: the single avatars are hidden from screen readers', async () => {
    const { container } = await render(AvatarStackComponent, { inputs: { names: NAMES } });
    expect(screen.getAllByRole('img')).toHaveLength(1);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('loads the image of a person with a principal id', async () => {
    const { container } = await render(AvatarStackComponent, {
      inputs: { names: NAMES.slice(0, 3), principalIds: ['p1', null] },
      providers: [
        {
          provide: BrandingService,
          useValue: { loaded: signal(true), gravatarEnabled: signal(true) },
        },
      ],
    });
    const imgs = container.querySelectorAll('app-avatar img');
    expect(imgs).toHaveLength(1);
    expect(imgs[0].getAttribute('src')).toBe('/api/principals/p1/avatar?s=64');
  });

  it('draws at least one avatar whatever the max', async () => {
    const { container } = await render(AvatarStackComponent, {
      inputs: { names: NAMES.slice(0, 2), max: 0 },
    });
    expect(container.querySelectorAll('app-avatar')).toHaveLength(1);
    expect(container.querySelector('.stack__rest')).toHaveTextContent('+1');
  });
});
