import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../testing/a11y';
import { DocumentViewerComponent, type ShownDocument } from './document-viewer.component';

const DOC: ShownDocument = {
  name: 'Plan.pdf',
  url: '/api/media/documents/0b8f3c3e-4d6a-4f43-9a1e-2f0c1d2e3f40',
};

describe('DocumentViewerComponent (spec 000863)', () => {
  it('shows nothing while no PDF is open', async () => {
    await render(DocumentViewerComponent);
    expect(screen.queryByTitle('Plan.pdf')).toBeNull();
    expect(screen.queryByRole('link', { name: 'PDF herunterladen' })).toBeNull();
  });

  it('frames the inline preview, offers the download and has no axe violations', async () => {
    const { container } = await render(DocumentViewerComponent, { inputs: { doc: DOC } });
    const frame = await screen.findByTitle('Plan.pdf');
    expect(frame).toHaveAttribute('src', `${DOC.url}?inline=true`);
    expect(screen.getByRole('link', { name: 'PDF herunterladen' })).toHaveAttribute('href', DOC.url);
    expect(await runAxe(container.ownerDocument.body)).toHaveNoViolations();
  });
});
