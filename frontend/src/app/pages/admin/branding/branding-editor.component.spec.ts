import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
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
  // ngModel writes the draft into the fields after a tick.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, toast };
}

/** The version line under the header (the version list below repeats the number). */
function stateLine(container: Element): string {
  return container.querySelector('.br__state')?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
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
    // A fresh draft per test: the editor changes the draft object in place.
    getSiteConfig: jest.fn(() => of({ ...STUB_CFG, draft: emptyBranding() })),
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

describe('BrandingEditorComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads the active version, the app name, the logos and the free texts', async () => {
    const { container } = await setup();
    expect(stateLine(container)).toBe('Version 1');
    expect(screen.getByRole('textbox', { name: 'Willkommenstext (DE)' })).toHaveValue('Willkommen auf der Antragsplattform.');
    expect(screen.getByRole('textbox', { name: 'Voller Name (Browser-Tab)' })).toBeInTheDocument();
    // An empty slot offers the file dialog; the button names its slot.
    expect(screen.getByRole('button', { name: 'Auswählen: Wortmarke' })).toBeInTheDocument();
  });

  it('edits the footer columns with their links and the mail footer text (gaps N43)', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(screen.getByRole('textbox', { name: 'Überschrift (DE)' })).toHaveValue('Über uns');
    expect(screen.getByRole('textbox', { name: 'Überschrift (EN)' })).toHaveValue('About');
    expect(screen.getByRole('textbox', { name: 'E-Mail-Fußzeile (DE)' })).toHaveValue('Automatische Nachricht – nicht antworten.');
    const heading = screen.getByRole('textbox', { name: 'Überschrift (EN)' });
    await userEvent.clear(heading);
    await userEvent.type(heading, 'Contact');
    expect(c.draft().footerColumns[0].label.en).toBe('Contact');
    // The first "Link hinzufügen" belongs to the column, the last one to the legal links.
    await userEvent.click(screen.getAllByRole('button', { name: 'Link hinzufügen' })[0]);
    expect(c.draft().footerColumns[0].links).toHaveLength(2);
    const urls = screen.getAllByRole('textbox', { name: 'URL' });
    await userEvent.type(urls[1], 'https://k.de');
    expect(c.draft().footerColumns[0].links[1].url).toBe('https://k.de');
    const mail = screen.getByRole('textbox', { name: 'E-Mail-Fußzeile (DE)' });
    await userEvent.clear(mail);
    await userEvent.type(mail, 'Gruß');
    expect(c.draft().freetexts.emailFooter.de).toBe('Gruß');
    await userEvent.click(screen.getByRole('button', { name: 'Spalte entfernen: Spalte 1' }));
    expect(c.draft().footerColumns).toHaveLength(0);
    expect(screen.getByText('Noch keine Spalte.')).toBeInTheDocument();
    // Many typed keys: the default 5 s is short on a busy runner.
  }, 15000);

  it('switches the text fields to English', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    await userEvent.click(screen.getByRole('radio', { name: 'EN' }));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByRole('textbox', { name: 'Copyright-Zeile (EN)' })).toHaveValue('© Student body');
    const support = screen.getByRole('textbox', { name: 'Support-Hinweis (EN)' });
    await userEvent.clear(support);
    await userEvent.type(support, 'EN support');
    expect(c.draft().freetexts.support.en).toBe('EN support');
    // The German text stays.
    expect(c.draft().freetexts.support.de).toBe('Bei Fragen: support@example.org');
    const label = screen.getAllByRole('textbox', { name: 'Bezeichnung (EN)' })[0];
    expect(label).toHaveValue('Imprint');
    c.setLang('de');
    expect(c.lang()).toBe('de');
  });

  it('edits the app name and the legal links', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    await userEvent.type(screen.getByRole('textbox', { name: 'Kurzname (PWA)' }), 'AP');
    expect(c.draft().appShortName).toBe('AP');
    await userEvent.type(screen.getByRole('textbox', { name: 'Voller Name (Browser-Tab)' }), 'Plattform');
    expect(c.draft().appName).toBe('Plattform');
    await userEvent.click(screen.getByRole('button', { name: 'Link entfernen: Datenschutz' }));
    expect(c.draft().legalLinks.map((l: { url: string }) => l.url)).toEqual(['https://example.org/impressum']);
  });

  it('shows the draft in a live preview behind the "Vorschau" disclosure', async () => {
    const { fixture } = await setup();
    const summary = screen.getByText('Vorschau').closest('summary') as HTMLElement;
    const details = summary.closest('details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    await userEvent.click(summary);
    expect(details.open).toBe(true);
    expect(screen.getByTestId('preview-welcome')).toHaveTextContent('Willkommen auf der Antragsplattform.');
    expect(screen.getByTestId('preview-support')).toHaveTextContent('support@example.org');
    expect(screen.getByTestId('preview-footer')).toHaveTextContent('Über uns');
    const legal = screen.getByTestId('preview-legal');
    expect(legal).toHaveTextContent('Impressum');
    expect(legal).toHaveTextContent('Datenschutz');
    // The preview follows the form at once.
    const welcome = screen.getByRole('textbox', { name: 'Willkommenstext (DE)' });
    await userEvent.clear(welcome);
    await userEvent.type(welcome, 'Servus');
    fixture.detectChanges();
    expect(screen.getByTestId('preview-welcome')).toHaveTextContent('Servus');
    // An empty text shows its field name as a placeholder.
    await userEvent.clear(welcome);
    fixture.detectChanges();
    expect(screen.getByTestId('preview-welcome')).toHaveTextContent('Willkommenstext');
    // The preview shows the language that is edited now.
    await userEvent.click(screen.getByRole('radio', { name: 'EN' }));
    fixture.detectChanges();
    expect(screen.getByTestId('preview-footer')).toHaveTextContent('About');
  });

  it('saving a draft enables activation and bumps the version', async () => {
    const { container } = await setup();
    const activate = screen.getByRole('button', { name: 'Entwurf aktivieren' });
    expect(activate).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
    expect(stateLine(container)).toMatch(/^Version 1\s*·\s*Nicht aktivierter Entwurf$/);
    expect(activate).toBeEnabled();

    await userEvent.click(activate);
    expect(stateLine(container)).toBe('Version 2');
  });

  it('uploads a logo by the file dialog and shows its row', async () => {
    const { container } = await setup();
    const inputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]');
    const file = new File(['x'], 'logo.png', { type: 'image/png' });
    await userEvent.upload(inputs[1], file);
    await waitFor(() => expect(screen.getByText(/logo\.png ·/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Datei ersetzen: Bildmarke' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Logo entfernen: Bildmarke' }));
    expect(screen.queryByText(/logo\.png ·/)).not.toBeInTheDocument();
  });

  it('takes a dropped logo and marks the row while a file is over it', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const prevented = jest.fn();
    c.onDragOver('favicon', { preventDefault: prevented } as unknown as DragEvent);
    expect(c.dropSlot()).toBe('favicon');
    c.onDragLeave();
    expect(c.dropSlot()).toBeNull();
    const file = new File(['ico'], 'fav.ico', { type: 'image/x-icon' });
    c.onDrop('favicon', { preventDefault: prevented, dataTransfer: { files: [file] } } as unknown as DragEvent);
    await waitFor(() => expect(c.draft().logos.favicon?.filename).toBe('fav.ico'));
    expect(prevented).toHaveBeenCalledTimes(2);
    // A drop without a file changes nothing.
    c.onDrop('wordmark', { preventDefault: prevented, dataTransfer: null } as unknown as DragEvent);
    expect(c.draft().logos.wordmark).toBeUndefined();
  });

  it('rejects a disallowed logo MIME type', async () => {
    const { toast, container } = await setup();
    const input = container.querySelectorAll<HTMLInputElement>('input[type="file"]')[2];
    const bad = new File(['x'], 'evil.exe', { type: 'application/x-msdownload' });
    // applyAccept is false, so the handler runs and its own guard rejects the type.
    await userEvent.upload(input, bad, { applyAccept: false });
    expect(toast.error).toHaveBeenCalledWith('Dateityp nicht erlaubt.');
  });

  it('rejects an SVG logo upload (img-only contract, no inline-SVG XSS)', async () => {
    const { toast, container } = await setup();
    const input = container.querySelectorAll<HTMLInputElement>('input[type="file"]')[1];
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
    c.setUrl(col.links[0], 'javascript:alert(1)');
    expect(c.linkErrors()).toContain('javascript:alert(1)');
    expect(c.isBadUrl('javascript:alert(1)')).toBe(true);
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('javascript:alert(1)');
    expect(screen.getByRole('button', { name: 'Entwurf speichern' })).toBeDisabled();
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
    c.setColumnLabel(col, 'de', 'Neu');
    expect(col.label.de).toBe('Neu');
    c.moveColumn(cols.length - 1, -1); // a valid move up
    c.moveColumn(0, -1); // out of bounds, so a no-op
    c.moveColumn(cols.length - 1, 1); // out of bounds, so a no-op
    c.removeColumn(0);

    c.addLegalLink(); // adds a legal link with an empty URL
    expect(c.draft().legalLinks.length).toBeGreaterThan(0);
    c.removeLegalLink(c.draft().legalLinks.length - 1); // drop the empty one, keep the valid seed

    c.removeLogo('wordmark'); // an absent slot takes the safe delete branch
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

  it('creates the apply info map on first use', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const d = c.draft();
    delete d.freetexts.applyInfo;
    const map = c.freetext(d, 'applyInfo');
    expect(map).toEqual({});
    expect(c.freetext(d, 'applyInfo')).toBe(map);
    expect(c.freetext(d, 'welcome')).toBe(d.freetexts.welcome);
  });

  describe('texts after the submission', () => {
    it('shows both fields with the built-in text as placeholder and preview', async () => {
      const { fixture } = await setupWithStub({});
      await fixture.whenStable();
      fixture.detectChanges();
      expect(screen.getByRole('heading', { name: 'Texte nach dem Einreichen' })).toBeInTheDocument();
      const internal = screen.getByRole('textbox', { name: 'Intern – angemeldet mit Konto (DE)' });
      expect(internal).toHaveAttribute('placeholder', expect.stringMatching(/^Vielen Dank! Dein Antrag ist eingereicht/));
      expect(screen.getByRole('textbox', { name: 'Extern – Gast mit E-Mail-Bestätigung (DE)' })).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/persönlichen Link/),
      );
      expect(screen.getByTestId('submitted-preview-external').textContent).toMatch(/persönlichen Link/);
      expect(screen.getAllByText('Standardtext')).toHaveLength(2);
    });

    it('writes the Markdown of the picked language into the draft and previews it safely', async () => {
      const { fixture, api } = await setupWithStub({});
      await fixture.whenStable();
      fixture.detectChanges();
      const internal = screen.getByRole('textbox', { name: 'Intern – angemeldet mit Konto (DE)' });
      await userEvent.type(internal, 'Danke **sehr** <b>x</b>');
      expect(screen.getByTestId('submitted-preview-internal').innerHTML).toContain('<strong>sehr</strong>');
      expect(screen.getByTestId('submitted-preview-internal').querySelector('b')).toBeNull();
      expect(screen.getAllByText('Standardtext')).toHaveLength(1);
      await userEvent.click(screen.getByRole('radio', { name: 'EN' }));
      const en = screen.getByRole('textbox', { name: 'Intern – angemeldet mit Konto (EN)' });
      expect(en).toHaveValue('');
      expect(en).toHaveAttribute('placeholder', expect.stringMatching(/^Thank you\. Your application is submitted/));
      await userEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
      const saved = api.saveBrandingDraft.mock.calls[0][0] as Branding;
      expect(saved.freetexts.submittedInternal).toEqual({ de: 'Danke **sehr** <b>x</b>' });
      expect(saved.freetexts.submittedExternal).toEqual({});
    });

    it('keeps a map that the config already has', async () => {
      const { fixture } = await setup();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      const d = c.draft();
      d.freetexts.submittedExternal = { de: 'x' };
      expect(c.submittedMap(d, 'external')).toBe(d.freetexts.submittedExternal);
      expect(c.submittedIsDefault(d, 'external')).toBe(false);
      delete d.freetexts.submittedInternal;
      expect(c.submittedIsDefault(d, 'internal')).toBe(true);
    });
  });

  it('slotLabel localises the logo slot', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(typeof c.slotLabel('favicon')).toBe('string');
    expect(c.slotLabel('favicon').length).toBeGreaterThan(0);
  });

  it('patch is a no-op without a draft', async () => {
    const { fixture } = await setupWithStub({ getSiteConfig: jest.fn(() => of({ ...STUB_CFG, draft: null as unknown as Branding })) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.draft()).toBeNull();
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

  it('switches the Gravatar images off and saves the switch with the draft', async () => {
    const { api } = await setupWithStub({});
    // A config without the field counts as on.
    const sw = screen.getByRole('switch', { name: /Gravatar-Bilder zeigen/ });
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'true'));
    await userEvent.click(sw);
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'false'));
    await userEvent.click(screen.getByRole('button', { name: /Entwurf speichern/ }));
    expect(api.saveBrandingDraft).toHaveBeenCalledWith(
      expect.objectContaining({ gravatarEnabled: false }),
    );
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

  it('saves unsaved edits before it activates, so the activation publishes the screen', async () => {
    const calls: string[] = [];
    const { api } = await setupWithStub({
      saveBrandingDraft: jest.fn((d: Branding) => {
        calls.push(`save:${d.freetexts.emailFooter.de}`);
        return of({ ...STUB_CFG, hasDraftChanges: true });
      }),
      activateBranding: jest.fn(() => {
        calls.push('activate');
        return of({ ...STUB_CFG, version: 4, hasDraftChanges: false });
      }),
    });
    const activate = screen.getByRole('button', { name: 'Entwurf aktivieren' });
    expect(activate).toBeDisabled();

    // Save once, then edit again: the server holds the older draft.
    await userEvent.click(screen.getByRole('button', { name: 'Entwurf speichern' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'E-Mail-Fußzeile (DE)' }), 'Gruß');
    expect(activate).toBeEnabled();

    await userEvent.click(activate);
    expect(calls).toEqual(['save:', 'save:Gruß', 'activate']);
    expect(api.activateBranding).toHaveBeenCalledTimes(1);
  });

  it('activates without a second save when the screen holds no unsaved edits', async () => {
    const { fixture, api } = await setupWithStub({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.saveDraft();
    expect(c.dirty()).toBe(false);
    c.activate();
    expect(api.saveBrandingDraft).toHaveBeenCalledTimes(1);
    expect(api.activateBranding).toHaveBeenCalledTimes(1);
  });

  it('enables the activate for local edits alone and blocks it for a bad link', async () => {
    const { fixture, api, toast } = await setupWithStub({});
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.canActivate()).toBe(false);
    c.setAppName('appName', 'AStA');
    expect(c.dirty()).toBe(true);
    expect(c.canActivate()).toBe(true);
    c.addLegalLink();
    c.setUrl(c.draft().legalLinks[0], 'javascript:alert(1)');
    expect(c.canActivate()).toBe(false);
    c.activate();
    expect(toast.error).toHaveBeenCalled();
    expect(api.saveBrandingDraft).not.toHaveBeenCalled();
    expect(api.activateBranding).not.toHaveBeenCalled();
  });

  it('keeps the edits unsaved when the save before the activate fails', async () => {
    const { fixture, api, toast } = await setupWithStub({
      saveBrandingDraft: jest.fn(() => throwError(() => new Error('boom'))),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.setAppName('appName', 'AStA');
    c.activate();
    expect(api.activateBranding).not.toHaveBeenCalled();
    expect(c.dirty()).toBe(true);
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  describe('on a phone', () => {
    let restore: () => void;
    beforeEach(() => (restore = matchMediaQueries(MEDIA.phone)));
    afterEach(() => restore());

    it('keeps the save in the header and moves the activate into a menu', async () => {
      const { fixture, api } = await setupWithStub({});
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      expect(screen.getByRole('button', { name: 'Entwurf speichern' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Entwurf aktivieren' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Weitere Aktionen' })).toBeInTheDocument();
      expect(c.phoneMenu()[0].items[0].disabledReason).toBe('Erst einen geänderten Entwurf speichern.');
      c.saveDraft();
      expect(c.phoneMenu()[0].items[0].disabledReason).toBeNull();
      expect(api.saveBrandingDraft).toHaveBeenCalled();
    });
  });
});
