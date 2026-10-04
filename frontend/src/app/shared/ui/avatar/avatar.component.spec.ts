import { render, screen } from '@testing-library/angular';
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

describe('AvatarStackComponent', () => {
  const NAMES = ['Mara Keller', 'Jonas Weber', 'Paul Neumann', 'Erika Beispiel', 'Lea Roth', 'Tom Fink'];

  it('draws every person when they fit', async () => {
    const { container } = await render(AvatarStackComponent, {
      inputs: { names: NAMES.slice(0, 3) },
    });
    expect(container.querySelectorAll('app-avatar')).toHaveLength(3);
    expect(container.querySelector('.stack__rest')).toBeNull();
    expect(screen.getByRole('img', { name: 'Mara Keller, Jonas Weber, Paul Neumann' })).toBeTruthy();
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

  it('draws at least one avatar whatever the max', async () => {
    const { container } = await render(AvatarStackComponent, {
      inputs: { names: NAMES.slice(0, 2), max: 0 },
    });
    expect(container.querySelectorAll('app-avatar')).toHaveLength(1);
    expect(container.querySelector('.stack__rest')).toHaveTextContent('+1');
  });
});
