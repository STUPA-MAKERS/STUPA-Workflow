import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute } from '@angular/router';
import { render, screen, within, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { NEVER, of, throwError } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { BrandingService } from '@core/branding/branding.service';
import { CATALOG } from '@core/i18n/translations';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { AdminApiService } from '../admin-api.service';
import type { Branding, SiteConfig } from '../admin.models';
import { BrandingEditorComponent, type BrandingSection } from './branding-editor.component';

/** The route of one of the two pages. */
function route(section: BrandingSection) {
  return { provide: ActivatedRoute, useValue: { snapshot: { data: { section } } } };
}

async function setup(section: BrandingSection = 'texts') {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(BrandingEditorComponent, {
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: true },
      { provide: ToastService, useValue: toast },
      route(section),
    ],
  });
  // ngModel writes the branding into the fields after a tick.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, toast };
}

/** The version (the `meta` of the header). */
function versionLine(container: Element): string {
  return container.querySelector('.ph__meta')?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
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

const STUB_CFG: SiteConfig = { version: 3, branding: emptyBranding() };

async function setupWithStub(
  api: Partial<Record<keyof AdminApiService, unknown>>,
  section: BrandingSection = 'branding',
) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const fullApi = {
    // A fresh branding per test: the editor changes the object in place.
    getSiteConfig: jest.fn(() => of({ ...STUB_CFG, branding: emptyBranding() })),
    saveSiteConfig: jest.fn((b: Branding) => of({ version: 4, branding: b })),
    listConfigRevisions: jest.fn(() => of([])),
    ...api,
  };
  const view = await render(BrandingEditorComponent, {
    providers: [
      { provide: AdminApiService, useValue: fullApi },
      { provide: ToastService, useValue: toast },
      route(section),
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, toast, api: fullApi };
}

describe('BrandingEditorComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('shows the texts on the page "Texte" and nothing of the branding', async () => {
    const { container } = await setup('texts');
    expect(screen.getByRole('heading', { level: 1, name: 'Texte' })).toBeInTheDocument();
    expect(versionLine(container)).toBe('Version 1');
    expect(screen.getByRole('textbox', { name: 'Willkommenstext (DE)' })).toHaveValue('Willkommen auf der Antragsplattform.');
    expect(screen.queryByRole('textbox', { name: 'Voller Name (Browser-Tab)' })).toBeNull();
    expect(screen.queryByText('Vorschau', { selector: 'summary *' })).toBeNull();
    expect(container.querySelector('details')).toBeNull();
  });

  it('shows the name, the accent, the switch and the logos on the page "Branding"', async () => {
    await setup('branding');
    expect(screen.getByRole('heading', { level: 1, name: 'Branding' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Voller Name (Browser-Tab)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Akzentfarbe' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Willkommenstext (DE)' })).toBeNull();
    // An empty slot shows the built-in logo and offers the file dialog.
    expect(screen.getByRole('button', { name: 'Auswählen: Wortmarke' })).toBeInTheDocument();
    expect(screen.getAllByText('Standard').length).toBeGreaterThanOrEqual(2);
  });

  it('shows the built-in logo of an empty slot in the colours of the theme', async () => {
    const { container } = await setupWithStub({});
    const imgs = Array.from(container.querySelectorAll<HTMLImageElement>('.br__thumb img')).map((i) => i.getAttribute('src'));
    expect(imgs).toEqual([expect.stringMatching(/^assets\/logos\/stupa-wordmark-(light|dark)\.svg$/), 'assets/logos/stupa-mark.svg', 'favicon.ico']);
  });

  it('shows the built-in texts muted as placeholders of the empty fields', async () => {
    await setupWithStub({}, 'texts');
    expect(screen.getByRole('textbox', { name: 'Copyright-Zeile (DE)' })).toHaveAttribute(
      'placeholder',
      'Eine Plattform des Studierendenparlaments',
    );
    await userEvent.click(screen.getByRole('radio', { name: 'EN' }));
    expect(screen.getByRole('textbox', { name: 'Copyright-Zeile (EN)' })).toHaveAttribute('placeholder', expect.stringMatching(/\S/));
  });

  it('falls back to the German built-in text while the other catalogue is missing', async () => {
    const { fixture } = await setupWithStub({}, 'texts');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const { de, en } = CATALOG;
    CATALOG.en = {};
    try {
      c.lang.set('en');
      expect(c.copyrightDefault()).toBe('Eine Plattform des Studierendenparlaments');
      CATALOG.de = { ...CATALOG.de, 'app.title': undefined };
      expect(c.appNameDefault()).toBe('');
    } finally {
      CATALOG.en = en;
      CATALOG.de = de;
    }
  });

  it('saves at once as the new active version', async () => {
    const { api, container, toast } = await setupWithStub({});
    expect(versionLine(container)).toBe('Version 3');
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
    await userEvent.type(screen.getByRole('textbox', { name: 'Kurzname (PWA)' }), 'AP');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.saveSiteConfig).toHaveBeenCalledWith(expect.objectContaining({ appShortName: 'AP' }));
    expect(versionLine(container)).toBe('Version 4');
    expect(toast.success).toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
  });

  it('save is a no-op without a branding', async () => {
    const { fixture, api } = await setupWithStub({ getSiteConfig: jest.fn(() => of({ ...STUB_CFG, branding: null as unknown as Branding })) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.save();
    expect(api.saveSiteConfig).not.toHaveBeenCalled();
  });

  it('save toasts an error when the request fails and keeps the edits', async () => {
    const { fixture, toast } = await setupWithStub({
      saveSiteConfig: jest.fn(() => throwError(() => new Error('boom'))),
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.setAppName('appName', 'AStA');
    c.save();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(c.dirty()).toBe(true);
  });

  describe('accent colour', () => {
    it('previews a picked accent on the whole page and saves it', async () => {
      const { api, fixture } = await setupWithStub({});
      const brand = fixture.debugElement.injector.get(BrandingService);
      const preview = jest.spyOn(brand, 'previewAccent');
      const hex = screen.getByRole('textbox', { name: 'Farbwert' });
      expect(hex).toHaveValue('');
      expect(hex).toHaveAttribute('placeholder', '#72a384');
      await userEvent.type(hex, '#0075BF');
      expect(preview).toHaveBeenLastCalledWith('#0075bf');
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('#0075bf');
      await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      expect(api.saveSiteConfig).toHaveBeenCalledWith(expect.objectContaining({ accentColor: '#0075bf' }));
      expect(brand.accentColor()).toBe('#0075bf');
      // "Standard" goes back to the built-in accent.
      await userEvent.click(screen.getByRole('button', { name: 'Standard' }));
      fixture.detectChanges();
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('');
      brand.applyBranding(null);
    });

    it('takes the native colour picker and ignores a partial value', async () => {
      const { fixture, container } = await setupWithStub({});
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      const picker = container.querySelector<HTMLInputElement>('input[type="color"]')!;
      picker.value = '#ce1625';
      picker.dispatchEvent(new Event('input'));
      expect(c.draft().accentColor).toBe('#ce1625');
      c.setAccent('#ce16');
      expect(c.draft().accentColor).toBe('#ce1625');
      c.setAccent('#72A384');
      expect(c.draft().accentColor).toBeNull();
    });

    it('ends the preview when the page goes', async () => {
      const { fixture } = await setupWithStub({});
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = fixture.componentInstance as any;
      const brand = fixture.debugElement.injector.get(BrandingService);
      c.setAccent('#7a4bc2');
      const preview = jest.spyOn(brand, 'previewAccent');
      fixture.destroy();
      expect(preview).toHaveBeenCalledWith(undefined);
    });
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

  it('gives a column and the legal links the same link rows', async () => {
    const { fixture, container } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const lists = container.querySelectorAll('ul.br__links');
    expect(lists).toHaveLength(2);
    for (const list of lists) {
      const row = list.querySelector('li.br__link')!;
      expect(row.querySelector('input.br__linkLabel')).not.toBeNull();
      expect(row.querySelector('input.br__linkUrl.mono')).toHaveAttribute('placeholder', 'https://');
    }
    const legal = c.draft().legalLinks.length;
    await userEvent.click(within(lists[0] as HTMLElement).getByRole('button', { name: /^Link entfernen: / }));
    expect(c.draft().footerColumns[0].links).toHaveLength(0);
    expect(c.draft().legalLinks).toHaveLength(legal);
  });

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
    await userEvent.click(screen.getByRole('radio', { name: 'DE' }));
    expect(c.lang()).toBe('de');
  });

  it('edits the app name', async () => {
    const { fixture } = await setup('branding');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    await userEvent.type(screen.getByRole('textbox', { name: 'Kurzname (PWA)' }), 'AP');
    expect(c.draft().appShortName).toBe('AP');
    await userEvent.type(screen.getByRole('textbox', { name: 'Voller Name (Browser-Tab)' }), 'Plattform');
    expect(c.draft().appName).toBe('Plattform');
  });

  it('edits the legal links', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    await userEvent.click(screen.getByRole('button', { name: 'Link entfernen: Datenschutz' }));
    expect(c.draft().legalLinks.map((l: { url: string }) => l.url)).toEqual(['https://example.org/impressum']);
  });

  it('uploads a logo by the file dialog and shows its row', async () => {
    const { container } = await setup('branding');
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
    const { toast, container } = await setup('branding');
    const input = container.querySelectorAll<HTMLInputElement>('input[type="file"]')[2];
    const bad = new File(['x'], 'evil.exe', { type: 'application/x-msdownload' });
    // applyAccept is false, so the handler runs and its own guard rejects the type.
    await userEvent.upload(input, bad, { applyAccept: false });
    expect(toast.error).toHaveBeenCalledWith('Dateityp nicht erlaubt.');
  });

  it('rejects an SVG logo upload (img-only contract, no inline-SVG XSS)', async () => {
    const { toast, container } = await setup('branding');
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
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
    c.save();
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
    c.save();
    expect(c.version()).toBe(2);
  });

  it('rejects an oversized logo file', async () => {
    const { fixture, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const big = new File(['x'], 'big.png', { type: 'image/png' });
    Object.defineProperty(big, 'size', { value: 5 * 1024 * 1024 });
    c.onLogoSelected('imagemark', [big]);
    expect(toast.error).toHaveBeenCalledWith('Datei zu groß (max. 2 MB).');
  });

  it('onLogoSelected is a no-op when no file is picked', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const before = JSON.stringify(c.draft().logos);
    expect(() => c.onLogoSelected('imagemark', [])).not.toThrow();
    expect(JSON.stringify(c.draft().logos)).toBe(before);
  });

  it('reads an accepted logo via FileReader and stores it in the slot', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const file = new File(['raw'], 'mark.png', { type: 'image/png' });
    c.onLogoSelected('wordmark', [file]);
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
      const { fixture } = await setupWithStub({}, 'texts');
      await fixture.whenStable();
      fixture.detectChanges();
      expect(screen.getByRole('heading', { name: 'Texte nach dem Einreichen' })).toBeInTheDocument();
      const internal = screen.getByRole('textbox', { name: 'Intern: angemeldet mit Konto (DE)' });
      expect(internal).toHaveAttribute('placeholder', expect.stringMatching(/^Vielen Dank! Dein Antrag ist eingereicht/));
      expect(screen.getByRole('textbox', { name: 'Extern: Gast mit E-Mail-Bestätigung (DE)' })).toHaveAttribute(
        'placeholder',
        expect.stringMatching(/persönlichen Link/),
      );
      expect(screen.getByTestId('submitted-preview-external').textContent).toMatch(/persönlichen Link/);
      expect(screen.getAllByText('Standardtext')).toHaveLength(2);
    });

    it('writes the Markdown of the picked language into the draft and previews it safely', async () => {
      const { fixture, api } = await setupWithStub({}, 'texts');
      await fixture.whenStable();
      fixture.detectChanges();
      const internal = screen.getByRole('textbox', { name: 'Intern: angemeldet mit Konto (DE)' });
      await userEvent.type(internal, 'Danke **sehr** <b>x</b>');
      expect(screen.getByTestId('submitted-preview-internal').innerHTML).toContain('<strong>sehr</strong>');
      expect(screen.getByTestId('submitted-preview-internal').querySelector('b')).toBeNull();
      expect(screen.getAllByText('Standardtext')).toHaveLength(1);
      await userEvent.click(screen.getByRole('radio', { name: 'EN' }));
      const en = screen.getByRole('textbox', { name: 'Intern: angemeldet mit Konto (EN)' });
      expect(en).toHaveValue('');
      expect(en).toHaveAttribute('placeholder', expect.stringMatching(/^Thank you\. Your application is submitted/));
      await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      const saved = api.saveSiteConfig.mock.calls[0][0] as Branding;
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

  it('shows the shape of the editor until the config arrives', async () => {
    await setupWithStub({ getSiteConfig: jest.fn(() => NEVER) });
    expect(screen.getByRole('status')).toHaveTextContent('Wird geladen …');
  });

  it('patch is a no-op without a draft', async () => {
    const { fixture } = await setupWithStub({ getSiteConfig: jest.fn(() => of({ ...STUB_CFG, branding: null as unknown as Branding })) });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.draft()).toBeNull();
    expect(() => c.addColumn()).not.toThrow();
    expect(c.draft()).toBeNull();
  });

  it('switches the Gravatar images off and saves the switch with the draft', async () => {
    const { api } = await setupWithStub({});
    // A config without the field counts as on.
    const sw = screen.getByRole('switch', { name: /Gravatar-Bilder zeigen/ });
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'true'));
    await userEvent.click(sw);
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'false'));
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.saveSiteConfig).toHaveBeenCalledWith(
      expect.objectContaining({ gravatarEnabled: false }),
    );
  });

  describe('on a phone', () => {
    let restore: () => void;
    beforeEach(() => (restore = matchMediaQueries(MEDIA.phone)));
    afterEach(() => restore());

    it('shows "Speichern" only for unsaved edits and no activate', async () => {
      const { api } = await setupWithStub({});
      expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
      expect(screen.queryByRole('button', { name: /aktivieren/ })).toBeNull();
      await userEvent.click(screen.getByRole('switch', { name: /Gravatar-Bilder zeigen/ }));
      await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      expect(api.saveSiteConfig).toHaveBeenCalled();
      expect(screen.queryByRole('button', { name: 'Speichern' })).toBeNull();
    });
  });
});
