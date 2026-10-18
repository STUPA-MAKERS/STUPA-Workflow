import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { CdVariant, CdVariantLogo } from '../admin.models';
import { AdminCdVariantsComponent } from './cd-variants.component';
import { pickOption } from '../../../../testing/select';

const TITLE_LOGO: CdVariantLogo = {
  id: 'l-1',
  slot: 'title',
  position: 0,
  vendoredName: 'HSRT',
  fileName: null,
};
const TITLE_UPLOAD: CdVariantLogo = {
  id: 'l-2',
  slot: 'title',
  position: 1,
  vendoredName: null,
  fileName: 'wappen.png',
  mime: 'image/png',
  size: 1234,
};
const FOOTER_LOGO: CdVariantLogo = {
  id: 'l-3',
  slot: 'footer',
  position: 0,
  vendoredName: 'STUPA',
  fileName: null,
};

const VARIANT: CdVariant = {
  id: 'cd-1',
  key: 'stupa',
  name: 'StuPa',
  baseVariant: 'protocol',
  logos: [TITLE_LOGO, TITLE_UPLOAD, FOOTER_LOGO],
};

/** HTTP error stub — only the status matters to the page. */
function httpError(status: number) {
  return throwError(() => ({ status }));
}

function makeApi(over: Partial<Record<string, unknown>> = {}) {
  return {
    listCdVariants: jest.fn(() => of([VARIANT])),
    createCdVariant: jest.fn((b: unknown) => of({ id: 'cd-new', logos: [], ...(b as object) })),
    updateCdVariant: jest.fn((id: string, b: unknown) => of({ ...VARIANT, id, ...(b as object) })),
    deleteCdVariant: jest.fn(() => of(void 0)),
    uploadCdVariantLogo: jest.fn(() =>
      of({ id: 'l-9', slot: 'title', position: 2, fileName: 'neu.png' }),
    ),
    reorderCdVariantLogos: jest.fn(() =>
      of([
        { ...TITLE_UPLOAD, position: 0 },
        { ...TITLE_LOGO, position: 1 },
      ]),
    ),
    deleteCdVariantLogo: jest.fn(() => of(void 0)),
    cdVariantLogoFileUrl: jest.fn((id: string) => `/api/admin/cd-variant-logos/${id}/file`),
    cdVariantSquareLogoUrl: jest.fn((id: string) => `/api/admin/cd-variant-logos/${id}/square`),
    listGremienOptions: jest.fn(() =>
      of([
        { id: 'g-1', name: 'Studierendenparlament', cdVariantId: 'cd-1' },
        { id: 'g-2', name: 'Fachschaftenrat', cdVariantId: 'cd-1' },
        { id: 'g-3', name: 'AStA', cdVariantId: null },
      ]),
    ),
    ...over,
  };
}

async function setup(api: ReturnType<typeof makeApi> = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminCdVariantsComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, api, toast, c };
}

describe('AdminCdVariantsComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  // --- list ---------------------------------------------------------------

  it('lists the variants with name, key, base and the gremien that use them', async () => {
    const { c } = await setup();
    expect(await screen.findByText('StuPa')).toBeInTheDocument();
    expect(screen.getByText('stupa')).toBeInTheDocument();
    expect(screen.getByText('Basis: Protokoll · genutzt von Studierendenparlament, Fachschaftenrat')).toBeInTheDocument();
    expect(c.loading()).toBe(false);
    expect(c.loadError()).toBe(false);
    // The first variant starts open.
    expect(c.isExpanded('cd-1')).toBe(true);
    expect(screen.getByRole('button', { name: /^Logos ausblenden/ })).toHaveAttribute('aria-expanded', 'true');
  });

  it('names a variant that no gremium uses', async () => {
    const other: CdVariant = { ...VARIANT, id: 'cd-2', key: 'bericht', name: 'Bericht', baseVariant: 'report', logos: [] };
    const { c } = await setup(makeApi({ listCdVariants: jest.fn(() => of([VARIANT, other])) }));
    expect(c.usage(other)).toBe('Basis: Bericht · von keinem Gremium genutzt');
  });

  it('leaves the gremien out after a failed master-data read', async () => {
    const { c } = await setup(
      makeApi({ listGremienOptions: jest.fn(() => throwError(() => new Error('403'))) }),
    );
    expect(c.usage(VARIANT)).toBe('Basis: Protokoll · von keinem Gremium genutzt');
  });

  it('describes a logo: the shipped name, else the file with its size', async () => {
    const { c } = await setup();
    expect(c.logoDetail(TITLE_LOGO)).toBe('HSRT');
    expect(c.logoDetail(TITLE_UPLOAD)).toBe('wappen.png · 1,2 KB');
    expect(c.logoDetail({ ...TITLE_UPLOAD, size: null })).toBe('wappen.png');
    expect(c.logoDetail({ ...TITLE_UPLOAD, size: 10, fileName: null })).toBe('— · 10 B');
    expect(c.logoDetail({ ...TITLE_UPLOAD, size: undefined, fileName: undefined })).toBe('—');
  });

  it('explains under a bundled logo why it has no file', async () => {
    await setup();
    await screen.findByText('StuPa');
    const hint =
      'Dieses Logo liefert der PDF-Renderer mit. Der Server wandelt es beim nächsten Start in einen normalen Upload um.';
    // Two bundled logos (HSRT, STUPA), none for the upload.
    const lines = screen.getAllByText(hint).filter((el) => el.classList.contains('cdv__logoHint'));
    expect(lines).toHaveLength(2);
    expect(screen.getByText('wappen.png · 1,2 KB').parentElement).not.toHaveTextContent(hint);
  });

  it('shows the empty state without variants', async () => {
    await setup(makeApi({ listCdVariants: jest.fn(() => of([])) }));
    expect(await screen.findByText('Noch keine Dokument-Varianten angelegt.')).toBeInTheDocument();
  });

  it('shows an error when the list request fails', async () => {
    const { c } = await setup(makeApi({ listCdVariants: jest.fn(() => httpError(500)) }));
    expect(c.loadError()).toBe(true);
    expect(c.loading()).toBe(false);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('sorts the logos of a slot by position and labels their source', async () => {
    const { c } = await setup();
    const unsorted: CdVariant = {
      ...VARIANT,
      logos: [{ ...TITLE_UPLOAD, position: 1 }, { ...TITLE_LOGO, position: 0 }],
    };
    expect(c.logosOf(unsorted, 'title').map((l: CdVariantLogo) => l.id)).toEqual(['l-1', 'l-2']);
    expect(c.logoLabel(TITLE_LOGO)).toBe('HSRT');
    expect(c.logoLabel(TITLE_UPLOAD)).toBe('wappen.png');
    expect(c.logoLabel({ id: 'x', slot: 'title', position: 0 })).toBe('—');
    expect(c.fileUrl(TITLE_UPLOAD)).toBe('/api/admin/cd-variant-logos/l-2/file');
  });

  it('collapses and expands the logo rows of a variant', async () => {
    const { c } = await setup();
    expect(screen.getByText('HSRT')).toBeInTheDocument();
    expect(screen.getByText('wappen.png · 1,2 KB')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Logos ausblenden/ }));
    expect(c.isExpanded('cd-1')).toBe(false);
    expect(screen.queryByText('HSRT')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Logos anzeigen/ }));
    expect(c.isExpanded('cd-1')).toBe(true);
    // Only an upload has a download link.
    expect(screen.getAllByRole('link', { name: /^Datei herunterladen/ })).toHaveLength(1);
  });

  it('adds a logo from the card into the slot that the dialog picks', async () => {
    const { c, api, fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Logo hinzufügen' }));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(c.logoDraft()).toMatchObject({ variantId: 'cd-1', variantName: 'StuPa', slot: 'title' });
    // The dialog names the variant and offers only the upload: no source choice.
    expect(screen.getByText('Variante StuPa')).toBeInTheDocument();
    expect(screen.queryByLabelText('Quelle')).not.toBeInTheDocument();
    const slots = screen.getByRole('radiogroup', { name: 'Position' });
    expect(slots).toHaveTextContent('Titelseite');
    expect(slots).toHaveTextContent('Fußzeile');
    expect(slots).toHaveTextContent('Quadratisch 1:1');
    await userEvent.click(screen.getByRole('radio', { name: /Fußzeile/ }));
    expect(c.logoDraft().slot).toBe('footer');
    const file = new File(['x'], 'fuss.svg', { type: 'image/svg+xml' });
    c.onFileSelected({ files: [file] } as unknown as HTMLInputElement);
    c.saveLogo();
    expect(api.uploadCdVariantLogo).toHaveBeenCalledWith('cd-1', 'footer', file);
  });

  it('shows an empty text for a variant without logos', async () => {
    await setup(makeApi({ listCdVariants: jest.fn(() => of([{ ...VARIANT, logos: [] }])) }));
    expect(await screen.findByText('Noch keine Logos.')).toBeInTheDocument();
  });

  // --- create / edit ------------------------------------------------------

  it('creates a variant through the dialog and generates the key from the name', async () => {
    const { api, c, toast } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Variante anlegen' }));
    await userEvent.type(screen.getByLabelText(/^Name/), 'AStA Vorstand');
    expect(c.form().key).toBe('asta-vorstand');
    await pickOption(screen.getByLabelText(/Basis-Variante/), 'Protokoll');
    await userEvent.click(screen.getByRole('button', { name: 'Hinzufügen' }));
    expect(api.createCdVariant).toHaveBeenCalledWith({
      key: 'asta-vorstand',
      name: 'AStA Vorstand',
      baseVariant: 'protocol',
    });
    expect(c.variants()).toHaveLength(2);
    expect(c.dialogOpen()).toBe(false);
    expect(toast.success).toHaveBeenCalled();
  });

  it('stops generating the key once it is edited by hand', async () => {
    const { c } = await setup();
    c.openCreate();
    c.patchName('AStA');
    expect(c.form().key).toBe('asta');
    c.patchKey('  Eigener-Key  ');
    expect(c.form().key).toBe('eigener-key');
    c.patchName('Ganz anders');
    expect(c.form().key).toBe('eigener-key');
  });

  it('caps the generated and the typed key at the server maximum', async () => {
    const { c } = await setup();
    c.openCreate();
    c.patchName('a'.repeat(90));
    expect(c.form().key).toHaveLength(64);
    c.patchKey('b'.repeat(90));
    expect(c.form().key).toHaveLength(64);
  });

  it('canSave requires a name and a key that matches the slug pattern', async () => {
    const { c } = await setup();
    expect(c.canSave()).toBe(false); // no dialog values yet
    c.openCreate();
    c.patchName('  ');
    expect(c.canSave()).toBe(false);
    c.patchName('StuPa');
    expect(c.canSave()).toBe(true);
    c.patchKey('Not A Slug');
    expect(c.canSave()).toBe(false);
    c.patchKey('slug-ok');
    expect(c.canSave()).toBe(true);
    c.saving.set(true);
    expect(c.canSave()).toBe(false);
  });

  it('submit is a no-op while it cannot save', async () => {
    const { api, c } = await setup();
    c.openCreate();
    c.submit(new Event('submit'));
    expect(api.createCdVariant).not.toHaveBeenCalled();
  });

  it('edits a variant: the key stays read-only and only name/base go out', async () => {
    const { api, c, fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten: StuPa' }));
    expect(c.editingId()).toBe('cd-1');
    // The key is immutable: a changed key answers 409, so the field stays locked.
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByLabelText(/^Schlüssel/)).toBeDisabled();
    c.patch('name', 'StuPa 2026');
    c.submit(new Event('submit'));
    expect(api.updateCdVariant).toHaveBeenCalledWith('cd-1', {
      name: 'StuPa 2026',
      baseVariant: 'protocol',
    });
    expect(c.variants()[0].name).toBe('StuPa 2026');
  });

  it('renders the 409 on create as a duplicate-key message', async () => {
    const { c, toast } = await setup(makeApi({ createCdVariant: jest.fn(() => httpError(409)) }));
    c.openCreate();
    c.patchName('StuPa');
    c.submit(new Event('submit'));
    expect(c.formError()).toBe('admin.cdVariants.keyExists');
    expect(c.saving()).toBe(false);
    expect(c.dialogOpen()).toBe(true); // stays open so the key can be fixed
    expect(toast.error).toHaveBeenCalledWith('Dieser Schlüssel ist bereits vergeben.');
  });

  it('falls back to the generic message on any other save failure', async () => {
    const { c, toast } = await setup(
      makeApi({ createCdVariant: jest.fn(() => throwError(() => new Error('boom'))) }),
    );
    c.openCreate();
    c.patchName('StuPa');
    c.submit(new Event('submit'));
    expect(c.formError()).toBe('admin.common.saveFailed');
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  it('closeDialog closes without saving', async () => {
    const { c } = await setup();
    c.openCreate();
    c.closeDialog();
    expect(c.dialogOpen()).toBe(false);
  });

  // --- delete -------------------------------------------------------------

  it('deletes a variant after the confirmation', async () => {
    const { api, c, toast } = await setup();
    c.askDelete(VARIANT);
    expect(c.confirmDelete()).toEqual(VARIANT);
    c.doDelete();
    expect(api.deleteCdVariant).toHaveBeenCalledWith('cd-1');
    expect(c.variants()).toEqual([]);
    expect(c.confirmDelete()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
  });

  it('names the 409 "still in use" reason instead of a generic failure', async () => {
    const { c, toast } = await setup(makeApi({ deleteCdVariant: jest.fn(() => httpError(409)) }));
    c.askDelete(VARIANT);
    c.doDelete();
    expect(c.deleteError()).toBe('admin.cdVariants.inUse');
    expect(c.deleting()).toBe(false);
    expect(c.confirmDelete()).not.toBeNull(); // the dialog keeps the message
    expect(toast.error).toHaveBeenCalledWith(
      'Diese Variante ist noch einem Gremium zugewiesen. Ändern Sie zuerst das Gremium.',
    );
  });

  it('shows the generic message on a non-409 delete failure', async () => {
    const { c, toast } = await setup(makeApi({ deleteCdVariant: jest.fn(() => httpError(500)) }));
    c.askDelete(VARIANT);
    c.doDelete();
    expect(c.deleteError()).toBe('admin.common.saveFailed');
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  it('doDelete is a no-op without a target or while it deletes', async () => {
    const { api, c } = await setup();
    c.doDelete();
    c.confirmDelete.set(VARIANT);
    c.deleting.set(true);
    c.doDelete();
    expect(api.deleteCdVariant).not.toHaveBeenCalled();
  });

  // --- logos --------------------------------------------------------------

  it('uploads a logo file into the chosen slot', async () => {
    const { api, c, toast } = await setup();
    c.openLogoDialog(VARIANT, 'title');
    expect(c.canSaveLogo()).toBe(false); // no file yet
    const file = new File(['x'], 'neu.png', { type: 'image/png' });
    c.onFileSelected({ files: [file] } as unknown as HTMLInputElement);
    expect(c.canSaveLogo()).toBe(true);
    c.saveLogo();
    expect(api.uploadCdVariantLogo).toHaveBeenCalledWith('cd-1', 'title', file);
    expect(c.variants()[0].logos).toHaveLength(4);
    expect(c.logoDraft()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
  });

  it('rejects a file above the 2 MB cap before it reaches the server', async () => {
    const { api, c } = await setup();
    c.openLogoDialog(VARIANT, 'title');
    const big = new File([''], 'big.png', { type: 'image/png' });
    Object.defineProperty(big, 'size', { value: 3 * 1024 * 1024 });
    c.onFileSelected({ files: [big] } as unknown as HTMLInputElement);
    expect(c.logoError()).toBe('admin.cdVariants.logoTooLarge');
    expect(c.canSaveLogo()).toBe(false);
    c.saveLogo();
    expect(api.uploadCdVariantLogo).not.toHaveBeenCalled();
  });

  it('clears the file when the picker is cancelled', async () => {
    const { c } = await setup();
    c.openLogoDialog(VARIANT, 'title');
    c.onFileSelected({ files: null } as unknown as HTMLInputElement);
    expect(c.logoDraft().file).toBeNull();
  });

  // --- square logo ----------------------------------------------------------

  describe('square logo', () => {
    let urls = 0;

    // jsdom has no object URLs. The fakes stay after each test, because the fixture
    // revokes its preview when the test bed tears it down after the test.
    beforeEach(() => {
      urls = 0;
      (URL.createObjectURL as unknown) = jest.fn(() => `blob:preview-${++urls}`);
      (URL.revokeObjectURL as unknown) = jest.fn();
    });

    const png = (name = 'quadrat.png') => new File(['x'], name, { type: 'image/png' });

    async function squareSetup(
      size: Promise<{ width: number; height: number }>,
      api: ReturnType<typeof makeApi> = makeApi(),
    ) {
      const view = await setup(api);
      view.c.readImageSize = jest.fn(() => size);
      view.c.openLogoDialog(VARIANT, 'square');
      return view;
    }

    it('checks a square file, previews it as a gremium row and uploads it', async () => {
      const square: CdVariantLogo = {
        id: 'l-sq', slot: 'square', position: 0, fileName: 'quadrat.png', mime: 'image/png',
      };
      const { api, c, fixture, toast } = await squareSetup(
        Promise.resolve({ width: 512, height: 512 }),
        makeApi({ uploadCdVariantLogo: jest.fn(() => of(square)) }),
      );
      expect(c.accept()).toBe('image/png,image/jpeg,image/webp');
      const file = png();
      c.onFileSelected({ files: [file] } as unknown as HTMLInputElement);
      expect(c.logoDraft().checking).toBe(true);
      expect(c.canSaveLogo()).toBe(false); // the size is not known yet
      fixture.detectChanges();
      expect(screen.getByText('Bild wird geprüft …')).toBeInTheDocument();
      await fixture.whenStable();
      fixture.detectChanges();
      expect(c.readImageSize).toHaveBeenCalledWith('blob:preview-1');
      expect(c.verdict()).toBe('ok');
      expect(screen.getByText(/512 × 512 px · quadratisch, groß genug/)).toBeInTheDocument();
      // The preview row carries the first gremium that uses the variant.
      expect(screen.getByText('So erscheint es in der Gremien-Liste')).toBeInTheDocument();
      expect(screen.getByText('Studierendenparlament')).toBeInTheDocument();
      expect(c.canSaveLogo()).toBe(true);
      c.saveLogo();
      expect(api.uploadCdVariantLogo).toHaveBeenCalledWith('cd-1', 'square', file);
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview-1');
      expect(c.squareLogo(c.variants()[0])).toEqual(square);
      expect(toast.success).toHaveBeenCalled();
    });

    it('replaces the square logo that the variant held', async () => {
      const old: CdVariantLogo = { id: 'l-old', slot: 'square', position: 0, fileName: 'alt.png' };
      const next: CdVariantLogo = { id: 'l-new', slot: 'square', position: 0, fileName: 'neu.png' };
      const api = makeApi({
        listCdVariants: jest.fn(() => of([{ ...VARIANT, logos: [...VARIANT.logos, old] }])),
        uploadCdVariantLogo: jest.fn(() => of(next)),
      });
      const { c, fixture } = await squareSetup(Promise.resolve({ width: 300, height: 300 }), api);
      c.onFileSelected({ files: [png('neu.png')] } as unknown as HTMLInputElement);
      await fixture.whenStable();
      c.saveLogo();
      const ids = c.variants()[0].logos.map((l: CdVariantLogo) => l.id);
      expect(ids).toContain('l-new');
      expect(ids).not.toContain('l-old');
      expect(ids).toContain('l-1'); // the other slots stay
    });

    it.each([
      [{ width: 600, height: 300 }, 'notSquare', /600 × 300 px · nicht quadratisch/],
      [{ width: 128, height: 128 }, 'tooSmall', /128 × 128 px · zu klein, mindestens 256 × 256 px/],
    ])('refuses %p before the upload', async (size, verdict, text) => {
      const { api, c, fixture } = await squareSetup(Promise.resolve(size));
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      await fixture.whenStable();
      fixture.detectChanges();
      expect(c.verdict()).toBe(verdict);
      expect(screen.getByRole('status')).toHaveTextContent(text);
      expect(screen.queryByText('So erscheint es in der Gremien-Liste')).not.toBeInTheDocument();
      expect(c.canSaveLogo()).toBe(false);
      c.saveLogo();
      expect(api.uploadCdVariantLogo).not.toHaveBeenCalled();
    });

    it('refuses an SVG for the square slot', async () => {
      const { c } = await squareSetup(Promise.resolve({ width: 512, height: 512 }));
      const svg = new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' });
      c.onFileSelected({ files: [svg] } as unknown as HTMLInputElement);
      expect(c.logoError()).toBe('admin.cdVariants.squareType');
      expect(c.logoDraft().file).toBeNull();
      expect(c.readImageSize).not.toHaveBeenCalled();
    });

    it('reports an image that does not load', async () => {
      const { c, fixture } = await squareSetup(Promise.reject(new Error('broken')));
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      await fixture.whenStable();
      expect(c.logoError()).toBe('admin.cdVariants.squareUnreadable');
      expect(c.logoDraft().checking).toBe(false);
      expect(c.canSaveLogo()).toBe(false);
    });

    it('ignores the size of a file that a later pick replaced', async () => {
      let resolveFirst: (s: { width: number; height: number }) => void = () => undefined;
      let rejectSecond: (e: Error) => void = () => undefined;
      const { c, fixture } = await squareSetup(Promise.resolve({ width: 1, height: 1 }));
      c.readImageSize = jest
        .fn()
        .mockReturnValueOnce(new Promise((r) => (resolveFirst = r)))
        .mockReturnValueOnce(new Promise((_, r) => (rejectSecond = r)));
      c.onFileSelected({ files: [png('a.png')] } as unknown as HTMLInputElement);
      c.onFileSelected({ files: [png('b.png')] } as unknown as HTMLInputElement);
      // The first preview URL goes when the second file comes.
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview-1');
      c.closeLogoDialog();
      resolveFirst({ width: 512, height: 512 });
      rejectSecond(new Error('late'));
      await fixture.whenStable();
      expect(c.logoDraft()).toBeNull();
      expect(c.logoError()).toBeNull();
    });

    it('drops the picked file when the slot changes', async () => {
      const { c, fixture } = await squareSetup(Promise.resolve({ width: 512, height: 512 }));
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      await fixture.whenStable();
      c.setSlot('square'); // the same slot keeps everything
      expect(c.logoDraft().file).not.toBeNull();
      c.setSlot('title');
      expect(c.logoDraft()).toMatchObject({ slot: 'title', file: null, previewUrl: null, size: null });
      expect(c.accept()).toBe('image/png,image/jpeg,image/webp,image/svg+xml,application/pdf');
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview-1');
      c.setSlot(null);
      expect(c.logoDraft().slot).toBe('title');
    });

    it.each([
      ['logo_not_square', 'admin.cdVariants.serverNotSquare', 'Das Logo ist nicht quadratisch.'],
      ['logo_too_small', 'admin.cdVariants.serverTooSmall', 'Das Logo ist kleiner als 256 × 256 px.'],
      ['logo_too_many_px', 'admin.cdVariants.serverTooManyPx', 'Das Logo ist größer als 4096 × 4096 px.'],
      ['logo_unreadable', 'admin.cdVariants.squareUnreadable', 'Das Bild konnte nicht gelesen werden.'],
      ['logo_type_not_allowed', 'admin.cdVariants.squareType', 'Ein quadratisches Logo muss PNG, JPEG oder WebP sein.'],
    ])('maps the server code %s to its own message', async (code, key, text) => {
      const api = makeApi({
        uploadCdVariantLogo: jest.fn(() => throwError(() => ({ status: 422, error: { code } }))),
      });
      const { c, fixture, toast } = await squareSetup(
        Promise.resolve({ width: 512, height: 512 }),
        api,
      );
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      await fixture.whenStable();
      c.saveLogo();
      expect(c.logoError()).toBe(key);
      expect(toast.error).toHaveBeenCalledWith(text);
    });

    it('falls back to the status for an unknown code', async () => {
      const api = makeApi({
        uploadCdVariantLogo: jest.fn(() => throwError(() => ({ status: 413, error: { code: 'x' } }))),
      });
      const { c, fixture } = await squareSetup(Promise.resolve({ width: 512, height: 512 }), api);
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      await fixture.whenStable();
      c.saveLogo();
      expect(c.logoError()).toBe('admin.cdVariants.logoTooLarge');
    });

    it('reads an error body without a code as "no code"', async () => {
      const api = makeApi({
        uploadCdVariantLogo: jest.fn(() => throwError(() => ({ status: 415, error: 'nope' }))),
      });
      const { c, fixture } = await squareSetup(Promise.resolve({ width: 512, height: 512 }), api);
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      await fixture.whenStable();
      c.saveLogo();
      expect(c.logoError()).toBe('admin.cdVariants.logoType');
    });

    it('reads the size through an image element by default', async () => {
      const { c } = await setup();
      // jsdom never loads the source, so the promise stays open; the call must not throw.
      expect(c.readImageSize('blob:x')).toBeInstanceOf(Promise);
    });

    it('revokes the preview when the page goes', async () => {
      const { c, fixture } = await squareSetup(Promise.resolve({ width: 512, height: 512 }));
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      fixture.destroy();
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview-1');
    });

    it('ignores a pick without an open dialog', async () => {
      const { c } = await setup();
      c.onFileSelected({ files: [png()] } as unknown as HTMLInputElement);
      expect(c.logoDraft()).toBeNull();
    });
  });

  // --- list thumbnails -------------------------------------------------------

  it('shows the square logo before the name, else the initials', async () => {
    const square: CdVariantLogo = { id: 'l-sq', slot: 'square', position: 0, fileName: 'q.png' };
    const other: CdVariant = { id: 'cd-2', key: 'hsrt-inf', name: 'HSRT INF', baseVariant: 'report', logos: [] };
    const { c, container } = await setup(
      makeApi({
        listCdVariants: jest.fn(() => of([{ ...VARIANT, logos: [...VARIANT.logos, square] }, other])),
      }),
    );
    const heads = container.querySelectorAll('.cdv__head .cdv__square');
    expect(heads[0].tagName).toBe('IMG');
    expect(heads[0].getAttribute('src')).toBe('/api/admin/cd-variant-logos/l-sq/square');
    expect(heads[1]).toHaveTextContent('HI');
    expect(heads[1]).toHaveAttribute('title', 'Kein quadratisches Logo');
    // The square row comes first and has no move buttons.
    const rows = container.querySelectorAll('.cdv__logo');
    expect(rows[0]).toHaveTextContent('Quadratisch 1:1');
    expect(rows[0].querySelector('.cdv__moveGap')).not.toBeNull();
    expect(rows[0].querySelector('img.cdv__thumb')).not.toBeNull();
    expect(rows[1].querySelector('.cdv__moveGap')).toBeNull();
    expect(c.initials('STUPA')).toBe('ST');
  });

  it('falls back to the placeholder when a thumbnail fails to load', async () => {
    const square: CdVariantLogo = { id: 'l-sq', slot: 'square', position: 0, fileName: 'q.png' };
    const { c, container, fixture } = await setup(
      makeApi({ listCdVariants: jest.fn(() => of([{ ...VARIANT, logos: [...VARIANT.logos, square] }])) }),
    );
    container.querySelector('.cdv__head img')?.dispatchEvent(new Event('error'));
    fixture.detectChanges();
    expect(c.squareLogo(c.variants()[0])).toBeNull();
    expect(container.querySelector('.cdv__head .cdv__square--none')).toHaveTextContent('ST');
    expect(container.querySelector('.cdv__logo img')).toBeNull();
  });

  it('names the variant in the preview when no gremium uses it', async () => {
    const { c } = await setup(makeApi({ listGremienOptions: jest.fn(() => of([])) }));
    c.openLogoDialog(VARIANT, 'square');
    expect(c.previewName(c.logoDraft())).toBe('StuPa');
  });

  it.each([
    [413, 'admin.cdVariants.logoTooLarge'],
    [415, 'admin.cdVariants.logoType'],
    [500, 'admin.common.saveFailed'],
  ])('maps upload status %i to its own message', async (status, key) => {
    const file = new File(['x'], 'neu.svg', { type: 'image/svg+xml' });
    const { c, toast } = await setup(
      makeApi({ uploadCdVariantLogo: jest.fn(() => httpError(status as number)) }),
    );
    c.openLogoDialog(VARIANT, 'title');
    c.onFileSelected({ files: [file] } as unknown as HTMLInputElement);
    c.saveLogo();
    expect(c.logoError()).toBe(key);
    expect(c.logoSaving()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });

  it('saveLogo and setSlot are no-ops without an open dialog', async () => {
    const { api, c } = await setup();
    c.setSlot('footer');
    expect(c.logoDraft()).toBeNull();
    expect(c.accept()).toBe('image/png,image/jpeg,image/webp,image/svg+xml,application/pdf');
    c.saveLogo();
    expect(api.uploadCdVariantLogo).not.toHaveBeenCalled();
    c.openLogoDialog(VARIANT, 'title');
    c.logoSaving.set(true);
    expect(c.canSaveLogo()).toBe(false);
    c.closeLogoDialog();
    expect(c.logoDraft()).toBeNull();
  });

  it('removes a logo from its variant', async () => {
    const { api, c, toast } = await setup();
    c.removeLogo(VARIANT, TITLE_LOGO);
    expect(api.deleteCdVariantLogo).toHaveBeenCalledWith('l-1');
    expect(c.variants()[0].logos.map((l: CdVariantLogo) => l.id)).toEqual(['l-2', 'l-3']);
    expect(toast.success).toHaveBeenCalledWith('Logo entfernt.');
  });

  it('toasts when the logo removal fails', async () => {
    const { c, toast } = await setup(
      makeApi({ deleteCdVariantLogo: jest.fn(() => httpError(500)) }),
    );
    c.removeLogo(VARIANT, TITLE_LOGO);
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(c.variants()[0].logos).toHaveLength(3);
  });

  it('reorders inside a slot and keeps the other slot untouched', async () => {
    const { api, c } = await setup();
    c.moveLogo(VARIANT, 'title', 1, -1);
    expect(api.reorderCdVariantLogos).toHaveBeenCalledWith('cd-1', 'title', ['l-2', 'l-1']);
    const logos = c.variants()[0].logos as CdVariantLogo[];
    expect(logos.filter((l) => l.slot === 'footer')).toHaveLength(1);
    expect(c.logosOf(c.variants()[0], 'title').map((l: CdVariantLogo) => l.id)).toEqual([
      'l-2',
      'l-1',
    ]);
  });

  it('touches only the edited variant when more than one exists', async () => {
    const other: CdVariant = { id: 'cd-2', key: 'asta', name: 'AStA', baseVariant: 'report', logos: [] };
    const { c } = await setup(makeApi({ listCdVariants: jest.fn(() => of([other, VARIANT])) }));

    c.openEdit(VARIANT);
    c.patch('name', 'StuPa 2026');
    c.submit(new Event('submit'));
    expect(c.variants()[0]).toEqual(other);

    c.openLogoDialog(VARIANT, 'footer');
    c.onFileSelected({
      files: [new File(['x'], 'f.png', { type: 'image/png' })],
    } as unknown as HTMLInputElement);
    c.saveLogo();
    expect(c.variants()[0].logos).toEqual([]);

    c.removeLogo(VARIANT, TITLE_LOGO);
    expect(c.variants()[0].logos).toEqual([]);

    c.moveLogo(VARIANT, 'title', 1, -1);
    expect(c.variants()[0].logos).toEqual([]);
  });

  // A thrown string carries no status, and a non-numeric one is unusable. Both
  // must fall back to the generic message instead of matching 409 by accident.
  it.each([['boom'], [{ status: 'nope' }]])(
    'reads an error without a usable status as "no status" (%p)',
    async (thrown) => {
      const { c, toast } = await setup(
        makeApi({ deleteCdVariant: jest.fn(() => throwError(() => thrown)) }),
      );
      c.askDelete(VARIANT);
      c.doDelete();
      expect(c.deleteError()).toBe('admin.common.saveFailed');
      expect(toast.error).toHaveBeenCalled();
    },
  );

  it('ignores a move beyond either end of the slot', async () => {
    const { api, c } = await setup();
    c.moveLogo(VARIANT, 'title', 0, -1);
    c.moveLogo(VARIANT, 'title', 1, 1);
    expect(api.reorderCdVariantLogos).not.toHaveBeenCalled();
  });

  it('toasts when the reorder fails', async () => {
    const { c, toast } = await setup(
      makeApi({ reorderCdVariantLogos: jest.fn(() => httpError(500)) }),
    );
    c.moveLogo(VARIANT, 'title', 1, -1);
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });
});
