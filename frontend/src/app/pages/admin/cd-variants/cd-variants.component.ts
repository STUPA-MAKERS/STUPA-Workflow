import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { NoteComponent } from '@shared/ui/note/note.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SegmentedComponent,
  type SegmentedOption,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { SelectFieldComponent } from '@shared/ui/select/select.component';
import { AdminApiService } from '../admin-api.service';
import { formatBytes } from '../admin-health/admin-health.util';
import {
  CD_BASE_VARIANTS,
  CD_LOGO_ACCEPT,
  CD_LOGO_LIST_ORDER,
  CD_LOGO_SLOTS,
  CD_SQUARE_LOGO_ACCEPT,
  CD_VARIANT_KEY_MAX,
  CD_VARIANT_KEY_PATTERN,
  type CdBaseVariant,
  type CdLogoSlot,
  type CdVariant,
  type CdVariantLogo,
  MAX_CD_LOGO_BYTES,
  SQUARE_LOGO_MAX_PX,
  SQUARE_LOGO_MIN_PX,
  slugify,
} from '../admin.models';
import {
  type ImageSize,
  type SquareVerdict,
  isSquareLogoType,
  readImageSize,
  squareVerdict,
  variantInitials,
} from './cd-variants.util';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';

/** Dialog state of the create/edit form. */
interface VariantForm {
  key: string;
  name: string;
  baseVariant: CdBaseVariant;
}

/**
 * Dialog state of "add a logo". A new logo is always an upload. For the square slot the
 * dialog also holds an object URL of the file (the preview) and its pixel size.
 */
interface LogoDraft {
  variantId: Uuid;
  variantName: string;
  slot: CdLogoSlot;
  file: File | null;
  previewUrl: string | null;
  size: ImageSize | null;
  checking: boolean;
}

/** Message per server error code of a square upload (`check_square_logo`). */
const SQUARE_ERROR_KEYS: Readonly<Record<string, TranslationKey>> = {
  logo_not_square: 'admin.cdVariants.serverNotSquare',
  logo_too_small: 'admin.cdVariants.serverTooSmall',
  logo_too_many_px: 'admin.cdVariants.serverTooManyPx',
  logo_unreadable: 'admin.cdVariants.squareUnreadable',
  logo_type_not_allowed: 'admin.cdVariants.squareType',
};

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

/** The problem+json `code` of a failed request, or '' when the error carries none. */
function errorCode(err: unknown): string {
  if (typeof err === 'object' && err !== null && 'error' in err) {
    const body = (err as { error: unknown }).error;
    if (typeof body === 'object' && body !== null && 'code' in body) {
      return String((body as { code: unknown }).code);
    }
  }
  return '';
}

/**
 * Corporate-design variants (board Admin-Dokument-Varianten): the logo sets a Gremium
 * renders its documents with, and the square logo the app shows for a Gremium.
 *
 * A variant carries no color and no font. It holds an ordered list of logos per PDF slot
 * (title page, page footer) on top of a base variant, and at most one square 1:1 logo.
 * A new logo is always an upload; a logo that the render service ships (an older row)
 * still shows until the worker converts it. One row per variant shows the square logo
 * (or an outlined placeholder with the initials), the name, the key, the base and the
 * gremien that use it; "Logos anzeigen" opens its logo rows (move, download, remove; the
 * square logo has no move). Create, edit and "add a logo" run in a dialog, which is a
 * bottom sheet on a phone. The key is a slug that the name generates, and it is immutable
 * after the create, because the renderer refers to it.
 */
@Component({
  selector: 'app-admin-cd-variants',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    EmptyStateComponent,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    SegmentedComponent,
    SelectFieldComponent,
    SkeletonComponent,
    PageHeaderComponent,
  ],
  templateUrl: './cd-variants.component.html',
  styleUrl: './cd-variants.component.scss',
})
export class AdminCdVariantsComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** Reads the pixel size of the picked square file. Tests replace it: jsdom loads no image. */
  readImageSize: (url: string) => Promise<ImageSize> = (url) => readImageSize(url);

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

  readonly listOrder = CD_LOGO_LIST_ORDER;
  readonly minPx = SQUARE_LOGO_MIN_PX;

  /** Ids of square logos whose image failed to load: they show the placeholder. */
  readonly brokenThumbs = signal<ReadonlySet<Uuid>>(new Set());

  readonly baseOptions = computed<SelectOption[]>(() =>
    CD_BASE_VARIANTS.map((v) => ({ value: v, label: this.baseLabel(v) })),
  );

  readonly slotOptions = computed<SegmentedOption[]>(() =>
    CD_LOGO_SLOTS.map((s) => ({ value: s, label: this.slotLabel(s) })),
  );

  /** The file types of the picker: raster only for the square slot. */
  readonly accept = computed(() =>
    this.logoDraft()?.slot === 'square' ? CD_SQUARE_LOGO_ACCEPT : CD_LOGO_ACCEPT,
  );

  /** The client verdict on the picked square file, once its size is known. */
  readonly verdict = computed<SquareVerdict | null>(() => {
    const size = this.logoDraft()?.size;
    return size ? squareVerdict(size) : null;
  });

  /** Gremium names per variant id, from the gremium master data. */
  private readonly usedBy = signal<ReadonlyMap<string, string[]>>(new Map());

  constructor() {
    inject(DestroyRef).onDestroy(() => this.revokePreview());
    this.reload();
    // The master data names the variant of each gremium. A failed read leaves the
    // "genutzt von" part out.
    this.api.listGremienOptions().subscribe({
      next: (gremien) => {
        const map = new Map<string, string[]>();
        for (const g of gremien) {
          if (!g.cdVariantId) continue;
          map.set(g.cdVariantId, [...(map.get(g.cdVariantId) ?? []), g.name]);
        }
        this.usedBy.set(map);
      },
      error: () => this.usedBy.set(new Map()),
    });
  }

  // --- reading -------------------------------------------------------------

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.listCdVariants().subscribe({
      next: (list) => {
        this.variants.set(list);
        this.loading.set(false);
        // The first variant starts open, so its logos show at once.
        if (this.expandedId() === null && list.length) this.expandedId.set(list[0].id);
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

  /** "Basis: Protokoll · genutzt von StuPa, AStA" for the card of a variant. */
  usage(variant: CdVariant): string {
    const base = this.i18n.translate('admin.cdVariants.baseLine', { base: this.baseLabel(variant.baseVariant) });
    const names = this.usedBy().get(variant.id) ?? [];
    const used = names.length
      ? this.i18n.translate('admin.cdVariants.usedBy', { names: names.join(', ') })
      : this.i18n.translate('admin.cdVariants.unused');
    return `${base} · ${used}`;
  }

  /** "Dateiname · 3 KB" of an upload, the name of a shipped logo. */
  logoDetail(logo: CdVariantLogo): string {
    if (logo.vendoredName) return logo.vendoredName;
    return logo.size != null ? `${logo.fileName ?? '—'} · ${formatBytes(logo.size, this.i18n)}` : (logo.fileName ?? '—');
  }

  /** Download URL of an uploaded logo. The server always answers `attachment`. */
  fileUrl(logo: CdVariantLogo): string {
    return this.api.cdVariantLogoFileUrl(logo.id);
  }

  /** The uploaded square logo of a variant whose image loads, else null. */
  squareLogo(variant: CdVariant): CdVariantLogo | null {
    const logo = variant.logos.find((l) => l.slot === 'square' && !!l.fileName);
    return logo && !this.brokenThumbs().has(logo.id) ? logo : null;
  }

  /** Inline image URL of a square logo. */
  squareUrl(logo: CdVariantLogo): string {
    return this.api.cdVariantSquareLogoUrl(logo.id);
  }

  /** A thumbnail failed to load: show the placeholder instead. */
  thumbFailed(logo: CdVariantLogo): void {
    this.brokenThumbs.update((set) => new Set([...set, logo.id]));
  }

  /** The letters of the placeholder of a variant without a square logo. */
  initials(name: string): string {
    return variantInitials(name);
  }

  /** "512 × 512 px · quadratisch, groß genug" or the reason why the file does not fit. */
  verdictText(size: ImageSize): string {
    const key = `admin.cdVariants.square.${squareVerdict(size)}` as TranslationKey;
    return this.i18n.translate(key, { w: size.width, h: size.height, min: this.minPx });
  }

  /** The name in the preview row: the first Gremium that uses the variant, else the variant. */
  previewName(draft: LogoDraft): string {
    return this.usedBy().get(draft.variantId)?.[0] ?? draft.variantName;
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

  openLogoDialog(variant: CdVariant, slot: CdLogoSlot = 'title'): void {
    this.revokePreview();
    this.logoError.set(null);
    this.logoDraft.set({
      variantId: variant.id,
      variantName: variant.name,
      slot,
      file: null,
      previewUrl: null,
      size: null,
      checking: false,
    });
  }

  closeLogoDialog(): void {
    this.revokePreview();
    this.logoDraft.set(null);
  }

  /** A new slot drops the picked file, because the allowed types differ per slot. */
  setSlot(slot: string | null): void {
    const draft = this.logoDraft();
    if (!draft || !slot || draft.slot === slot) return;
    this.revokePreview();
    this.logoError.set(null);
    this.logoDraft.set({ ...draft, slot: slot as CdLogoSlot, ...this.noFile() });
  }

  /**
   * Read the picked file and reject what the server would refuse: a file above the cap,
   * and for the square slot a type other than PNG, JPEG or WebP. A square file then loads
   * as an image, for the preview and the size check.
   */
  onFileSelected(input: HTMLInputElement): void {
    const draft = this.logoDraft();
    if (!draft) return;
    const file = input.files?.[0] ?? null;
    this.revokePreview();
    this.logoError.set(null);
    if (file && file.size > MAX_CD_LOGO_BYTES) {
      this.logoError.set('admin.cdVariants.logoTooLarge');
      this.logoDraft.set({ ...draft, ...this.noFile() });
      return;
    }
    if (!file || draft.slot !== 'square') {
      this.logoDraft.set({ ...draft, ...this.noFile(), file });
      return;
    }
    if (!isSquareLogoType(file)) {
      this.logoError.set('admin.cdVariants.squareType');
      this.logoDraft.set({ ...draft, ...this.noFile() });
      return;
    }
    const url = URL.createObjectURL(file);
    this.logoDraft.set({ ...draft, file, previewUrl: url, size: null, checking: true });
    this.readImageSize(url).then(
      (size) => this.applyIfCurrent(file, { size, checking: false }),
      () => {
        if (this.applyIfCurrent(file, { checking: false })) {
          this.logoError.set('admin.cdVariants.squareUnreadable');
        }
      },
    );
  }

  private noFile(): Pick<LogoDraft, 'file' | 'previewUrl' | 'size' | 'checking'> {
    return { file: null, previewUrl: null, size: null, checking: false };
  }

  /** Patch the draft only while it still holds `file`: a later pick wins. */
  private applyIfCurrent(file: File, patch: Partial<LogoDraft>): boolean {
    const draft = this.logoDraft();
    if (draft?.file !== file) return false;
    this.logoDraft.set({ ...draft, ...patch });
    return true;
  }

  private revokePreview(): void {
    const url = this.logoDraft()?.previewUrl;
    if (url) URL.revokeObjectURL(url);
  }

  canSaveLogo(): boolean {
    const draft = this.logoDraft();
    if (!draft?.file || this.logoSaving()) return false;
    return draft.slot !== 'square' || this.verdict() === 'ok';
  }

  saveLogo(): void {
    const draft = this.logoDraft();
    if (!draft?.file || !this.canSaveLogo()) return;
    this.logoSaving.set(true);
    this.logoError.set(null);
    this.api.uploadCdVariantLogo(draft.variantId, draft.slot, draft.file).subscribe({
      next: (logo) => {
        this.logoSaving.set(false);
        this.closeLogoDialog();
        // A square logo replaces the one that the variant held.
        const keep = (l: CdVariantLogo) => logo.slot !== 'square' || l.slot !== 'square';
        this.variants.update((list) =>
          list.map((v) =>
            v.id === draft.variantId ? { ...v, logos: [...v.logos.filter(keep), logo] } : v,
          ),
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: (err: unknown) => {
        this.logoSaving.set(false);
        const status = errorStatus(err);
        let key: TranslationKey = SQUARE_ERROR_KEYS[errorCode(err)] ?? 'admin.common.saveFailed';
        if (key === 'admin.common.saveFailed' && status === 413) key = 'admin.cdVariants.logoTooLarge';
        else if (key === 'admin.common.saveFailed' && status === 415) key = 'admin.cdVariants.logoType';
        this.logoError.set(key);
        this.toast.error(this.i18n.translate(key, { min: this.minPx, max: SQUARE_LOGO_MAX_PX }));
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
