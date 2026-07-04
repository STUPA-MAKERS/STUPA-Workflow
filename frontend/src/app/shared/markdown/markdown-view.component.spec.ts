import { render, screen } from '@testing-library/angular';
import { MarkdownViewComponent } from './markdown-view.component';

describe('MarkdownViewComponent', () => {
  it('renders the source as sanitized markdown HTML', async () => {
    await render(MarkdownViewComponent, {
      inputs: { src: '**fett** und\n<script>alert(1)</script>' },
    });
    const strong = screen.getByText('fett');
    expect(strong.tagName).toBe('STRONG');
    // Raw HTML is escaped, not executed.
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
});
