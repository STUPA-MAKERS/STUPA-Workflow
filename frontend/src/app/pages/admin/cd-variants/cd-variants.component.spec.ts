import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { CdVariant, CdVariantLogo } from '../admin.models';
import { AdminCdVariantsComponent } from './cd-variants.component';

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
function httpError(status: number, code?: string) {
  return throwError(() => ({ status, error: code ? { code } : undefined }));
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
    addCdVariantVendoredLogo: jest.fn(() =>
      of({ id: 'l-8', slot: 'footer', position: 1, vendoredName: 'ECHO' }),
    ),
    reorderCdVariantLogos: jest.fn(() =>
      of([
        { ...TITLE_UPLOAD, position: 0 },
        { ...TITLE_LOGO, position: 1 },
      ]),
    ),
    updateCdVariantLogo: jest.fn((id: string, patch: { slot?: string }) =>
      of({ ...TITLE_LOGO, id, slot: patch.slot ?? 'title', position: 1 }),
    ),
    deleteCdVariantLogo: jest.fn(() => of(void 0)),
    cdVariantLogoFileUrl: jest.fn((id: string) => `/api/admin/cd-variant-logos/${id}/file`),
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

  it('lists the variants with name, key, base variant and a logo summary', async () => {
    const { c } = await setup();
    expect(await screen.findByText('StuPa')).toBeInTheDocument();
    expect(screen.getByText('stupa')).toBeInTheDocument();
    expect(screen.getByText('Protokoll')).toBeInTheDocument();
    expect(screen.getByText('Titelseite 2 · Fußzeile 1')).toBeInTheDocument();
    expect(c.loading()).toBe(false);
    expect(c.loadError()).toBe(false);
  });

  it('shows the empty state without variants', async () => {
    await setup(makeApi({ listCdVariants: jest.fn(() => of([])) }));
    expect(await screen.findByText('Noch keine CD-Varianten angelegt.')).toBeInTheDocument();
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

  it('expands and collapses the logo detail of a row', async () => {
    const { c } = await setup();
    expect(c.isExpanded('cd-1')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Logos anzeigen' }));
    expect(c.isExpanded('cd-1')).toBe(true);
    expect(screen.getByText('HSRT')).toBeInTheDocument();
    expect(screen.getByText('wappen.png')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Logos anzeigen' }));
    expect(c.isExpanded('cd-1')).toBe(false);
  });

  it('shows a per-slot empty text when a slot has no logo', async () => {
    const { c } = await setup(
      makeApi({ listCdVariants: jest.fn(() => of([{ ...VARIANT, logos: [] }])) }),
    );
    c.toggle('cd-1');
    await screen.findAllByText('Noch keine Logos.');
    expect(screen.getAllByText('Noch keine Logos.')).toHaveLength(2);
  });

  // --- create / edit ------------------------------------------------------

  it('creates a variant through the dialog and generates the key from the name', async () => {
    const { api, c, toast } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Variante hinzufügen' }));
    await userEvent.type(screen.getByLabelText(/^Name/), 'AStA Vorstand');
    expect(c.form().key).toBe('asta-vorstand');
    await userEvent.selectOptions(screen.getByLabelText(/Basis-Variante/), 'protocol');
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

  it('edits a variant: key and base variant stay read-only, only the name goes out', async () => {
    const { api, c, fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    expect(c.editingId()).toBe('cd-1');
    // The key is immutable: a changed key answers 409, so the field stays locked.
    await fixture.whenStable();
    fixture.detectChanges();
    expect(screen.getByLabelText(/^Schlüssel/)).toBeDisabled();
    // The render paths pin the document shape per document kind, so a later flip
    // would change nothing.
    expect(screen.getByLabelText(/^Basis-Variante/)).toBeDisabled();
    c.patch('name', 'StuPa 2026');
    c.submit(new Event('submit'));
    expect(api.updateCdVariant).toHaveBeenCalledWith('cd-1', { name: 'StuPa 2026' });
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
    c.openLogoDialog('cd-1', 'title');
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
    c.openLogoDialog('cd-1', 'title');
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
    c.openLogoDialog('cd-1', 'title');
    c.onFileSelected({ files: null } as unknown as HTMLInputElement);
    expect(c.logoDraft().file).toBeNull();
  });

  it('adds a vendored logo from the dropdown', async () => {
    const { api, c } = await setup();
    c.openLogoDialog('cd-1', 'footer');
    c.patchLogo('source', 'vendored');
    c.patchLogo('vendoredName', 'ECHO');
    expect(c.canSaveLogo()).toBe(true);
    c.saveLogo();
    expect(api.addCdVariantVendoredLogo).toHaveBeenCalledWith('cd-1', 'footer', 'ECHO');
    expect(c.variants()[0].logos.map((l: CdVariantLogo) => l.id)).toContain('l-8');
  });

  it('blocks the vendored save without a name', async () => {
    const { c } = await setup();
    c.openLogoDialog('cd-1', 'footer');
    c.patchLogo('source', 'vendored');
    c.patchLogo('vendoredName', '');
    expect(c.canSaveLogo()).toBe(false);
  });

  it.each([
    [413, undefined, 'admin.cdVariants.logoTooLarge'],
    [415, undefined, 'admin.cdVariants.logoType'],
    [409, 'cd_logo_count_limit', 'admin.cdVariants.logoCountLimit'],
    [409, 'cd_logo_total_limit', 'admin.cdVariants.logoTotalLimit'],
    [409, undefined, 'admin.common.saveFailed'],
    [500, undefined, 'admin.common.saveFailed'],
  ])('maps upload status %i / code %s to its own message', async (status, code, key) => {
    const file = new File(['x'], 'neu.png', { type: 'image/png' });
    const { c, toast } = await setup(
      makeApi({
        uploadCdVariantLogo: jest.fn(() => httpError(status as number, code as string | undefined)),
      }),
    );
    c.openLogoDialog('cd-1', 'title');
    c.onFileSelected({ files: [file] } as unknown as HTMLInputElement);
    c.saveLogo();
    expect(c.logoError()).toBe(key);
    expect(c.logoSaving()).toBe(false);
    expect(toast.error).toHaveBeenCalled();
  });

  it('saveLogo and patchLogo are no-ops without an open dialog', async () => {
    const { api, c } = await setup();
    c.patchLogo('source', 'vendored');
    expect(c.logoDraft()).toBeNull();
    c.saveLogo();
    expect(api.uploadCdVariantLogo).not.toHaveBeenCalled();
    c.openLogoDialog('cd-1', 'title');
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

  it('moves a logo to the other slot and renumbers both slots', async () => {
    const { api, c, toast } = await setup();
    c.moveLogoToSlot(VARIANT, TITLE_LOGO);
    expect(api.updateCdVariantLogo).toHaveBeenCalledWith('l-1', { slot: 'footer' });
    const variant = c.variants()[0];
    expect(c.logosOf(variant, 'title').map((l: CdVariantLogo) => l.id)).toEqual(['l-2']);
    expect(c.logosOf(variant, 'footer').map((l: CdVariantLogo) => l.id)).toEqual(['l-3', 'l-1']);
    expect(c.logosOf(variant, 'title')[0].position).toBe(0);
    expect(toast.success).toHaveBeenCalledWith('Logo verschoben.');
  });

  it('names the target slot on the move control', async () => {
    const { c } = await setup();
    expect(c.moveSlotLabel('title')).toBe('Nach Fußzeile verschieben');
    expect(c.moveSlotLabel('footer')).toBe('Nach Titelseite verschieben');
  });

  it('toasts and keeps the slot when the move fails', async () => {
    const { c, toast } = await setup(
      makeApi({ updateCdVariantLogo: jest.fn(() => httpError(500)) }),
    );
    c.moveLogoToSlot(VARIANT, TITLE_LOGO);
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    expect(c.logosOf(c.variants()[0], 'title')).toHaveLength(2);
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

    c.openLogoDialog('cd-1', 'footer');
    c.patchLogo('source', 'vendored');
    c.saveLogo();
    expect(c.variants()[0].logos).toEqual([]);

    c.removeLogo(VARIANT, TITLE_LOGO);
    expect(c.variants()[0].logos).toEqual([]);

    c.moveLogo(VARIANT, 'title', 1, -1);
    expect(c.variants()[0].logos).toEqual([]);
  });

  // A status that is missing or non-numeric must not match 409 by accident.
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
