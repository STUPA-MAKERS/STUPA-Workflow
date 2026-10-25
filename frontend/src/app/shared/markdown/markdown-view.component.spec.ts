import { Router, provideRouter } from '@angular/router';
import { fireEvent, render, screen } from '@testing-library/angular';
import { MarkdownViewComponent } from './markdown-view.component';

describe('MarkdownViewComponent', () => {
  /** The renderer escapes raw HTML and never runs it. */
  it('renders the source as sanitized markdown HTML', async () => {
    await render(MarkdownViewComponent, {
      inputs: { src: '**fett** und\n<script>alert(1)</script>' },
    });
    const strong = screen.getByText('fett');
    expect(strong.tagName).toBe('STRONG');
    expect(document.querySelector('script')).toBeNull();
    expect(screen.getByText(/<script>/)).toBeInTheDocument();
  });

  it('updates when the input changes', async () => {
    const view = await render(MarkdownViewComponent, { inputs: { src: 'alt' } });
    expect(screen.getByText('alt')).toBeInTheDocument();
    view.fixture.componentRef.setInput('src', '- Punkt');
    view.fixture.detectChanges();
    expect(screen.getByText('Punkt').closest('li')).not.toBeNull();
  });

  it('passes headingOffset and imageSrc to the renderer', async () => {
    const id = '0b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40';
    const view = await render(MarkdownViewComponent, {
      inputs: { src: `# T\n\n![Bild](/api/media/images/${id})`, headingOffset: 0 },
    });
    expect(screen.getByRole('heading', { level: 1, name: 'T' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Bild' })).toHaveAttribute('src', `/api/media/images/${id}`);
    view.fixture.componentRef.setInput('imageSrc', (i: string) => `/pub/${i}`);
    view.detectChanges();
    expect(screen.getByRole('img', { name: 'Bild' })).toHaveAttribute('src', `/pub/${id}`);
    view.fixture.componentRef.setInput('imageSrc', null);
    view.detectChanges();
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('Bild')).toBeInTheDocument();
  });

  it('routes an internal link through the router and leaves others to the browser', async () => {
    const view = await render(MarkdownViewComponent, {
      inputs: { src: '[In](/todos) [Out](https://x.de) [Anker](#a)' },
      providers: [provideRouter([])],
    });
    const router = view.fixture.debugElement.injector.get(Router);
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    expect(fireEvent.click(screen.getByRole('link', { name: 'In' }))).toBe(false);
    expect(nav).toHaveBeenCalledWith('/todos');
    expect(fireEvent.click(screen.getByRole('link', { name: 'Anker' }))).toBe(false);
    expect(nav).toHaveBeenLastCalledWith('/#a');
    nav.mockClear();
    const out = screen.getByRole('link', { name: 'Out' });
    out.addEventListener('click', (e) => e.preventDefault());
    fireEvent.click(out);
    fireEvent.click(screen.getByRole('link', { name: 'In' }), { ctrlKey: true });
    fireEvent.click(screen.getByRole('link', { name: 'In' }), { metaKey: true });
    fireEvent.click(screen.getByRole('link', { name: 'In' }), { shiftKey: true });
    fireEvent.click(screen.getByRole('link', { name: 'In' }), { altKey: true });
    fireEvent.click(screen.getByRole('link', { name: 'In' }), { button: 1 });
    fireEvent.click(view.container.querySelector('.mdv') as Element);
    expect(nav).not.toHaveBeenCalled();
  });

  /** Without a router the browser follows the link; jsdom only records the default. */
  it('leaves an already handled click and a missing router alone', async () => {
    await render(MarkdownViewComponent, { inputs: { src: '[In](/todos)' } });
    const link = screen.getByRole('link', { name: 'In' });
    link.addEventListener('click', (e) => e.preventDefault());
    expect(fireEvent.click(link)).toBe(false);
  });
});
