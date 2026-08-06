import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  RowDetailDirective,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import {
  CD_BASE_VARIANTS,
  CD_LOGO_ACCEPT,
  CD_LOGO_SLOTS,
  CD_VARIANT_KEY_MAX,
  CD_VARIANT_KEY_PATTERN,
  type CdBaseVariant,
  type CdLogoSlot,
  type CdVariant,
  type CdVariantLogo,
  MAX_CD_LOGO_BYTES,
  VENDORED_LOGO_NAMES,
  slugify,
} from '../admin.models';

/** Dialog state of the create/edit form. */
interface VariantForm {
  key: string;
  name: string;
  baseVariant: CdBaseVariant;
}

/** Dialog state of "add a logo". A logo is either an upload or a vendored name. */
interface LogoDraft {
  variantId: Uuid;
  slot: CdLogoSlot;
  source: 'upload' | 'vendored';
  vendoredName: string;
  file: File | null;
}

function emptyForm(): VariantForm {
  return { key: '', name: '', baseVariant: 'report' };
}

/** HTTP status of a failed request, or 0 when the error carries none. */
function errorStatus(err: unknown): number {
  if (typeof err === 'object' && err !== null && 'status' in err) {
    const status = Number((err as { status: unknown }).status);
    return Number.isFinite(status) ? status : 0;
  }
  return 0;
}

/**
 * Corporate-design variants: the logo sets a Gremium renders its documents with.
 *
 * A variant carries no color and no font. It only holds an ordered list of logos per
 * slot (title page, page footer) on top of a pytex base variant. A logo is either a
 * name that pytex ships or a file an admin uploaded. Create, edit and "add a logo" all
 * run in a dialog. The key is a slug that the name generates, and it is immutable after
 * the create, because the renderer refers to it.
 */
@Component({
  selector: 'app-admin-cd-variants',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CellDirective,
    DataTableComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    RowDetailDirective,
    SelectComponent,
    PageHeaderComponent,
  ],
  templateUrl: './cd-variants.component.html',
  styleUrl: './cd-variants.component.scss',
})
export class AdminCdVariantsComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly variants = signal<CdVariant[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);

  readonly expandedId = signal<Uuid | null>(null);

  readonly dialogOpen = signal(false);
  readonly editingId = signal<Uuid | null>(null);
  readonly form = signal<VariantForm>(emptyForm());
  /** True once the admin typed a key: the name no longer overwrites it. */
  readonly keyEdited = signal(false);
  readonly saving = signal(false);
  readonly formError = signal<TranslationKey | null>(null);

  readonly confirmDelete = signal<CdVariant | null>(null);
  readonly deleting = signal(false);
  readonly deleteError = signal<TranslationKey | null>(null);

  readonly logoDraft = signal<LogoDraft | null>(null);
  readonly logoSaving = signal(false);
  readonly logoError = signal<TranslationKey | null>(null);

  readonly slots = CD_LOGO_SLOTS;
  readonly accept = CD_LOGO_ACCEPT;
  readonly maxMb = Math.round(MAX_CD_LOGO_BYTES / (1024 * 1024));

  readonly baseOptions = computed<SelectOption[]>(() =>
    CD_BASE_VARIANTS.map((v) => ({ value: v, label: this.baseLabel(v) })),
  );
  readonly vendoredOptions: SelectOption[] = VENDORED_LOGO_NAMES.map((n) => ({
    value: n,
    label: n,
  }));
  readonly sourceOptions = computed<SelectOption[]>(() => [
    { value: 'upload', label: this.i18n.translate('admin.cdVariants.sourceUpload') },
    { value: 'vendored', label: this.i18n.translate('admin.cdVariants.sourceVendored') },
  ]);

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.cdVariants.col.name') },
    { key: 'key', label: this.i18n.translate('admin.common.key') },
    { key: 'baseVariant', label: this.i18n.translate('admin.cdVariants.col.base') },
    { key: 'logos', label: this.i18n.translate('admin.cdVariants.col.logos') },
    {
      key: 'actions',
      label: this.i18n.translate('admin.common.actions'),
      align: 'end',
      width: '10rem',
    },
  ]);

  readonly rowId = (v: unknown): string => (v as CdVariant).id;
  readonly rowExpanded = (v: unknown): boolean => this.expandedId() === (v as CdVariant).id;

  constructor() {
    this.reload();
  }

  // --- reading -------------------------------------------------------------

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.listCdVariants().subscribe({
      next: (list) => {
        this.variants.set(list);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  baseLabel(base: CdBaseVariant): string {
    return this.i18n.translate(`admin.cdVariants.base.${base}` as TranslationKey);
  }

  slotLabel(slot: CdLogoSlot): string {
    return this.i18n.translate(`admin.cdVariants.slot.${slot}` as TranslationKey);
  }

  /** The logos of one slot, in render order. */
  logosOf(variant: CdVariant, slot: CdLogoSlot): CdVariantLogo[] {
    return variant.logos.filter((l) => l.slot === slot).sort((a, b) => a.position - b.position);
  }

  /** Display name of a logo: the vendored name, else the uploaded file name. */
  logoLabel(logo: CdVariantLogo): string {
    return logo.vendoredName ?? logo.fileName ?? '—';
  }

  /** Per-slot counts for the collapsed row, e.g. "Titelseite 2 · Fußzeile 1". */
  logoSummary(variant: CdVariant): string {
    return this.slots
      .map((s) => `${this.slotLabel(s)} ${this.logosOf(variant, s).length}`)
      .join(' · ');
  }

  /** Download URL of an uploaded logo. The server always answers `attachment`. */
  fileUrl(logo: CdVariantLogo): string {
    return this.api.cdVariantLogoFileUrl(logo.id);
  }

  toggle(id: Uuid): void {
    this.expandedId.update((cur) => (cur === id ? null : id));
  }

  isExpanded(id: Uuid): boolean {
    return this.expandedId() === id;
  }

  // --- create / edit -------------------------------------------------------

  openCreate(): void {
    this.editingId.set(null);
    this.keyEdited.set(false);
    this.formError.set(null);
    this.form.set(emptyForm());
    this.dialogOpen.set(true);
  }

  openEdit(variant: CdVariant): void {
    this.editingId.set(variant.id);
    this.keyEdited.set(true);
    this.formError.set(null);
    this.form.set({ key: variant.key, name: variant.name, baseVariant: variant.baseVariant });
    this.dialogOpen.set(true);
  }

  closeDialog(): void {
    this.dialogOpen.set(false);
  }

  patch<K extends keyof VariantForm>(key: K, value: VariantForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  /** The name generates the key until the admin edits the key by hand. */
  patchName(value: string): void {
    this.form.update((f) => ({
      ...f,
      name: value,
      key: this.keyEdited() ? f.key : slugify(value).slice(0, CD_VARIANT_KEY_MAX),
    }));
  }

  patchKey(value: string): void {
    this.keyEdited.set(true);
    this.patch('key', value.trim().toLowerCase().slice(0, CD_VARIANT_KEY_MAX));
  }

  /** A create needs a name and a key that matches the server pattern. */
  canSave(): boolean {
    const f = this.form();
    if (!f.name.trim() || this.saving()) return false;
    return this.editingId() !== null || CD_VARIANT_KEY_PATTERN.test(f.key);
  }

  submit(event: Event): void {
    event.preventDefault();
    if (!this.canSave()) return;
    const f = this.form();
    this.saving.set(true);
    this.formError.set(null);
    const id = this.editingId();
    const request = id
      ? this.api.updateCdVariant(id, { name: f.name.trim(), baseVariant: f.baseVariant })
      : this.api.createCdVariant({
          key: f.key,
          name: f.name.trim(),
          baseVariant: f.baseVariant,
        });
    request.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.dialogOpen.set(false);
        this.variants.update((list) =>
          id ? list.map((v) => (v.id === id ? saved : v)) : [...list, saved],
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: (err: unknown) => {
        this.saving.set(false);
        const key: TranslationKey =
          errorStatus(err) === 409 ? 'admin.cdVariants.keyExists' : 'admin.common.saveFailed';
        this.formError.set(key);
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  // --- delete --------------------------------------------------------------

  askDelete(variant: CdVariant): void {
    this.deleteError.set(null);
    this.confirmDelete.set(variant);
  }

  doDelete(): void {
    const variant = this.confirmDelete();
    if (!variant || this.deleting()) return;
    this.deleting.set(true);
    this.deleteError.set(null);
    this.api.deleteCdVariant(variant.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.confirmDelete.set(null);
        this.variants.update((list) => list.filter((v) => v.id !== variant.id));
        this.toast.success(this.i18n.translate('admin.cdVariants.deleted'));
      },
      error: (err: unknown) => {
        this.deleting.set(false);
        // 409 = a Gremium still points at this variant. Name that reason, so the
        // admin knows the delete needs a change on the Gremium first.
        const key: TranslationKey =
          errorStatus(err) === 409 ? 'admin.cdVariants.inUse' : 'admin.common.saveFailed';
        this.deleteError.set(key);
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  // --- logos ---------------------------------------------------------------

  openLogoDialog(variantId: Uuid, slot: CdLogoSlot): void {
    this.logoError.set(null);
    this.logoDraft.set({
      variantId,
      slot,
      source: 'upload',
      vendoredName: VENDORED_LOGO_NAMES[0],
      file: null,
    });
  }

  closeLogoDialog(): void {
    this.logoDraft.set(null);
  }

  patchLogo<K extends keyof LogoDraft>(key: K, value: LogoDraft[K]): void {
    this.logoDraft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  /** Read the picked file and reject anything above the server cap up front. */
  onFileSelected(input: HTMLInputElement): void {
    const file = input.files?.[0] ?? null;
    if (file && file.size > MAX_CD_LOGO_BYTES) {
      this.logoError.set('admin.cdVariants.logoTooLarge');
      this.patchLogo('file', null);
      return;
    }
    this.logoError.set(null);
    this.patchLogo('file', file);
  }

  canSaveLogo(): boolean {
    const draft = this.logoDraft();
    if (!draft || this.logoSaving()) return false;
    return draft.source === 'upload' ? draft.file !== null : !!draft.vendoredName;
  }

  saveLogo(): void {
    const draft = this.logoDraft();
    if (!draft || !this.canSaveLogo()) return;
    this.logoSaving.set(true);
    this.logoError.set(null);
    const request =
      draft.source === 'upload' && draft.file
        ? this.api.uploadCdVariantLogo(draft.variantId, draft.slot, draft.file)
        : this.api.addCdVariantVendoredLogo(draft.variantId, draft.slot, draft.vendoredName);
    request.subscribe({
      next: (logo) => {
        this.logoSaving.set(false);
        this.logoDraft.set(null);
        this.variants.update((list) =>
          list.map((v) =>
            v.id === draft.variantId ? { ...v, logos: [...v.logos, logo] } : v,
          ),
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: (err: unknown) => {
        this.logoSaving.set(false);
        const status = errorStatus(err);
        let key: TranslationKey = 'admin.common.saveFailed';
        if (status === 413) key = 'admin.cdVariants.logoTooLarge';
        else if (status === 415) key = 'admin.cdVariants.logoType';
        this.logoError.set(key);
        this.toast.error(this.i18n.translate(key));
      },
    });
  }

  removeLogo(variant: CdVariant, logo: CdVariantLogo): void {
    this.api.deleteCdVariantLogo(logo.id).subscribe({
      next: () => {
        this.variants.update((list) =>
          list.map((v) =>
            v.id === variant.id ? { ...v, logos: v.logos.filter((l) => l.id !== logo.id) } : v,
          ),
        );
        this.toast.success(this.i18n.translate('admin.cdVariants.logoRemoved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  /** Move a logo one place up (-1) or down (+1) inside its slot. */
  moveLogo(variant: CdVariant, slot: CdLogoSlot, index: number, delta: number): void {
    const inSlot = this.logosOf(variant, slot);
    const target = index + delta;
    if (target < 0 || target >= inSlot.length) return;
    const ordered = [...inSlot];
    const [moved] = ordered.splice(index, 1);
    ordered.splice(target, 0, moved);
    const ids = ordered.map((l) => l.id);
    this.api.reorderCdVariantLogos(variant.id, slot, ids).subscribe({
      next: (logos) => {
        this.variants.update((list) =>
          list.map((v) =>
            v.id === variant.id
              ? { ...v, logos: [...v.logos.filter((l) => l.slot !== slot), ...logos] }
              : v,
          ),
        );
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
