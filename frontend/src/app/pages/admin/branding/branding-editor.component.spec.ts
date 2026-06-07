import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@shared/ui';
import { BrandingEditorComponent } from './branding-editor.component';

async function setup() {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(BrandingEditorComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: true },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, toast };
}

describe('BrandingEditorComponent (#21)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the active version and seeded free text into the live preview', async () => {
    await setup();
    expect(screen.getByText('Version 1')).toBeInTheDocument();
    expect(screen.getByTestId('preview-welcome')).toHaveTextContent(/Willkommen/);
  });

  it('live-updates the preview as free text changes', async () => {
    await setup();
    const welcome = screen.getByRole('textbox', { name: 'Willkommenstext' });
    await userEvent.clear(welcome);
    await userEvent.type(welcome, 'Servus');
    expect(screen.getByTestId('preview-welcome')).toHaveTextContent('Servus');
  });

  it('saving a draft enables activation and bumps the version', async () => {
    await setup();
    const activate = screen.getByRole('button', { name: 'Entwurf aktivieren' });
    expect(activate).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
    expect(screen.getByText('Nicht aktivierter Entwurf')).toBeInTheDocument();
    expect(activate).toBeEnabled();

    await userEvent.click(activate);
    expect(screen.getByText('Version 2')).toBeInTheDocument();
  });

  it('uploads a logo and shows a preview thumbnail', async () => {
    await setup();
    const input = screen.getByLabelText('Bildmarke') as HTMLInputElement;
    const file = new File(['x'], 'logo.png', { type: 'image/png' });
    await userEvent.upload(input, file);

    // editor thumbnail carries the slot name as alt → exposed as role img
    await waitFor(() =>
      expect(screen.getByRole('img', { name: 'Bildmarke' })).toBeInTheDocument(),
    );
    expect(screen.getByText('logo.png')).toBeInTheDocument();
  });

  it('rejects a disallowed logo MIME type', async () => {
    const { toast } = await setup();
    const input = screen.getByLabelText('Favicon') as HTMLInputElement;
    const bad = new File(['x'], 'evil.exe', { type: 'application/x-msdownload' });
    // applyAccept:false so the handler runs and its own guard rejects the type
    await userEvent.upload(input, bad, { applyAccept: false });
    expect(toast.error).toHaveBeenCalledWith('Dateityp nicht erlaubt.');
  });

  it('exercises footer/legal/logo mutators', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;

    c.addColumn();
    const cols = c.draft().footerColumns;
    const col = cols[cols.length - 1];
    c.addLink(col);
    expect(col.links.length).toBeGreaterThan(0);
    c.removeLink(col, 0);
    c.moveColumn(cols.length - 1, -1); // valid move up
    c.moveColumn(0, -1); // out of bounds → no-op
    c.moveColumn(cols.length - 1, 1); // out of bounds → no-op
    c.removeColumn(0);

    c.addLegalLink();
    expect(c.draft().legalLinks.length).toBeGreaterThan(0);
    c.removeLegalLink(0);

    c.removeLogo('wordmark'); // absent slot → safe delete branch
    c.reemit();
    c.saveDraft();
    expect(c.hasDraftChanges()).toBe(true);
  });

  it('rejects an oversized logo file', async () => {
    const { fixture, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const big = new File(['x'], 'big.png', { type: 'image/png' });
    Object.defineProperty(big, 'size', { value: 5 * 1024 * 1024 });
    const input = { files: [big], value: 'x' } as unknown as HTMLInputElement;
    c.onLogoSelected('imagemark', input);
    expect(toast.error).toHaveBeenCalledWith('Datei zu groß (max. 2 MB).');
  });
});
