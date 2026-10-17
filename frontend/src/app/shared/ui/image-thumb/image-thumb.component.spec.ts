import { fireEvent, render, screen } from '@testing-library/angular';
import { ImageThumbComponent, inlineUrl, isThumbImage } from './image-thumb.component';

describe('image thumb helpers', () => {
  it('accepts clean raster images only', () => {
    expect(isThumbImage({ mime: 'image/png' })).toBe(true);
    expect(isThumbImage({ mime: 'image/webp', scanState: 'clean' })).toBe(true);
    expect(isThumbImage({ mime: 'image/png', scanState: 'scanning' })).toBe(false);
    expect(isThumbImage({ mime: 'image/svg+xml' })).toBe(false);
    expect(isThumbImage({ mime: 'application/pdf', scanState: null })).toBe(false);
  });

  it('adds inline=1 with the right separator', () => {
    expect(inlineUrl('/api/attachments/a/download')).toBe('/api/attachments/a/download?inline=1');
    expect(inlineUrl('/x?sig=1')).toBe('/x?sig=1&inline=1');
  });
});

describe('ImageThumbComponent', () => {
  it('shows a lazy image and falls back to the icon when it fails', async () => {
    const view = await render(ImageThumbComponent, {
      inputs: { src: '/x?inline=1', alt: 'Foto', size: 'sm' },
    });
    const img = screen.getByRole('img', { name: 'Foto' });
    expect(img).toHaveAttribute('loading', 'lazy');
    expect(view.fixture.nativeElement).toHaveClass('thumb--sm');
    fireEvent.error(img);
    view.detectChanges();
    expect(screen.queryByRole('img', { name: 'Foto' })).toBeNull();
    expect(view.fixture.nativeElement.querySelector('.thumb__icon')).not.toBeNull();
  });

  it('uses the medium size by default', async () => {
    const view = await render(ImageThumbComponent, { inputs: { src: '/x' } });
    expect(view.fixture.nativeElement).not.toHaveClass('thumb--sm');
    fireEvent.error(view.fixture.nativeElement.querySelector('img'));
    view.detectChanges();
    expect(view.fixture.nativeElement.querySelector('.thumb__icon')).not.toBeNull();
  });
});
