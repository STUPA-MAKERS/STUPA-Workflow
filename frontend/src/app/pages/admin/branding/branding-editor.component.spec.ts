import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { Branding, SiteConfig } from '../admin.models';
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

function emptyBranding(): Branding {
  return {
    logos: {},
    footerColumns: [],
    copyright: { de: '', en: '' },
    legalLinks: [],
    freetexts: {
      loginHint: { de: '', en: '' },
      welcome: { de: '', en: '' },
      support: { de: '', en: '' },
      emailFooter: { de: '', en: '' },
    },
  };
}

const STUB_CFG: SiteConfig = {
  version: 3,
  active: emptyBranding(),
  draft: emptyBranding(),
  hasDraftChanges: false,
};

async function setupWithStub(api: Partial<Record<keyof AdminApiService, unknown>>) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const fullApi = {
    getSiteConfig: jest.fn(() => of(STUB_CFG)),
    saveBrandingDraft: jest.fn(() => of({ ...STUB_CFG, hasDraftChanges: true })),
    activateBranding: jest.fn(() => of({ ...STUB_CFG, version: 4, hasDraftChanges: false })),
    listConfigRevisions: jest.fn(() => of([])),
    ...api,
  };
  const view = await render(BrandingEditorComponent, {
    providers: [
      { provide: AdminApiService, useValue: fullApi },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, toast, api: fullApi };
}

describe('BrandingEditorComponent (#21)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the active version and seeded free text into the live preview', async () => {
    await setup();
    expect(screen.getByText('Version 1')).toBeInTheDocument();
    expect(screen.getByTestId('preview-welcome')).toHaveTextContent(/Willkommen/);
  });

  it('renders support text and legal links in the preview from the form state (#review2 §4)', async () => {
    await setup();
    expect(screen.getByTestId('preview-support')).toHaveTextContent(/support@/);
    const legal = screen.getByTestId('preview-legal');
    expect(legal).toHaveTextContent('Impressum');
    expect(legal).toHaveTextContent('Datenschutz');
  });

  it('exposes EN inputs for copyright and free texts (#16)', async () => {
    await setup();
    expect(screen.getByRole('textbox', { name: 'Copyright-Zeile (EN)' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Willkommenstext (EN)' })).toBeInTheDocument();
    const supportEn = screen.getByRole('textbox', { name: 'Support-Hinweis (EN)' });
    await userEvent.clear(supportEn);
    await userEvent.type(supportEn, 'EN support');
    expect(supportEn).toHaveValue('EN support');
  });

  it('live-updates the preview as free text changes', async () => {
    await setup();
    const welcome = screen.getByRole('textbox', { name: 'Willkommenstext (DE)' });
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

  it('rejects an SVG logo upload (img-only contract, no inline-SVG XSS)', async () => {
    const { toast } = await setup();
    const input = screen.getByLabelText('Bildmarke') as HTMLInputElement;
    const svg = new File(['<svg onload="alert(1)"/>'], 'logo.svg', { type: 'image/svg+xml' });
    await userEvent.upload(input, svg, { applyAccept: false });
    expect(toast.error).toHaveBeenCalledWith('Dateityp nicht erlaubt.');
  });

  it('blocks saving when a footer link uses a disallowed scheme', async () => {
    const { fixture, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.addColumn();
    const col = c.draft().footerColumns[c.draft().footerColumns.length - 1];
    c.addLink(col);
    col.links[0].url = 'javascript:alert(1)';
    c.reemit();
    expect(c.linkErrors()).toContain('javascript:alert(1)');
    c.saveDraft();
    expect(toast.error).toHaveBeenCalledWith(
      'Unzulässige Link-URL — nur http(s):// oder mailto: erlaubt.',
    );
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

    c.addLegalLink(); // appends an empty-url legal link
    expect(c.draft().legalLinks.length).toBeGreaterThan(0);
    c.removeLegalLink(c.draft().legalLinks.length - 1); // drop the empty one, keep valid seed

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

  it('onLogoSelected is a no-op when no file is picked', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const before = JSON.stringify(c.draft().logos);
    const input = { files: [], value: '' } as unknown as HTMLInputElement;
    expect(() => c.onLogoSelected('imagemark', input)).not.toThrow();
    expect(JSON.stringify(c.draft().logos)).toBe(before);
  });

  it('reads an accepted logo via FileReader and stores it in the slot', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const file = new File(['raw'], 'mark.png', { type: 'image/png' });
    const input = { files: [file], value: 'mark.png' } as unknown as HTMLInputElement;
    c.onLogoSelected('wordmark', input);
    await waitFor(() => expect(c.draft().logos.wordmark).toBeDefined());
    expect(c.draft().logos.wordmark.filename).toBe('mark.png');
    expect(c.draft().logos.wordmark.mime).toBe('image/png');
  });

  it('text() resolves an i18n map and tolerates null/undefined', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.text({ de: 'Hallo', en: 'Hi' })).toBe('Hallo');
    expect(c.text(null)).toBe('');
    expect(c.text(undefined)).toBe('');
  });

  it('applyInfo lazily initialises the freetext map', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const d = c.draft();
    delete d.freetexts.applyInfo;
    const map = c.applyInfo(d);
    expect(map).toEqual({});
    // a second call returns the already-initialised map
    expect(c.applyInfo(d)).toBe(map);
  });

  it('slotLabel localises the logo slot', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(typeof c.slotLabel('favicon')).toBe('string');
    expect(c.slotLabel('favicon').length).toBeGreaterThan(0);
  });

  it('patch/reemit are no-ops without a draft', async () => {
    const { fixture } = await setupWithStub({ getSiteConfig: jest.fn(() => of({ ...STUB_CFG, draft: null as unknown as Branding })) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.draft()).toBeNull();
    expect(() => c.reemit()).not.toThrow();
    expect(() => c.addColumn()).not.toThrow();
    expect(c.draft()).toBeNull();
  });

  it('saveDraft is a no-op without a draft', async () => {
    const { fixture, api } = await setupWithStub({ getSiteConfig: jest.fn(() => of({ ...STUB_CFG, draft: null as unknown as Branding })) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.saveDraft();
    expect(api.saveBrandingDraft).not.toHaveBeenCalled();
  });

  it('saveDraft toasts and persists on success', async () => {
    const { fixture, api, toast } = await setupWithStub({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.saveDraft();
    expect(api.saveBrandingDraft).toHaveBeenCalled();
    expect(c.hasDraftChanges()).toBe(true);
    expect(toast.success).toHaveBeenCalled();
  });

  it('saveDraft toasts an error when the request fails', async () => {
    const { fixture, toast } = await setupWithStub({
      saveBrandingDraft: jest.fn(() => throwError(() => new Error('boom'))),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.saveDraft();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  it('activate bumps the version and toasts on success', async () => {
    const { fixture, api, toast } = await setupWithStub({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.activate();
    expect(api.activateBranding).toHaveBeenCalled();
    expect(c.version()).toBe(4);
    expect(c.hasDraftChanges()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('activate toasts an error when the request fails', async () => {
    const { fixture, toast } = await setupWithStub({
      activateBranding: jest.fn(() => throwError(() => new Error('boom'))),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.activate();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });
});
