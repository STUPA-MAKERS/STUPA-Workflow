import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { VersionHistoryComponent } from '../version-history/version-history.component';
import type { I18nMap } from '@core/api/models';
import {
  type Branding,
  type FooterColumn,
  LOGO_ACCEPT_MIME,
  LOGO_MAX_SIZE_MB,
  type LogoSlot,
} from '../admin.models';
import { brandingLinkErrors } from '../branding.util';

/**
 * Branding/site-config editor. Makes logos, footer and free texts editable via the UI
 * instead of in code. Logo upload with preview + mime/size guard, footer link columns,
 * i18n free texts, a live preview, and versioning (active vs. draft) with an activate
 * button.
 *
 * Works against `/api/admin/site-config` (not part of the API spec; served by the mock).
 * Produces valid `branding` JSON.
 */
@Component({
  selector: 'app-branding-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, VersionHistoryComponent],
  templateUrl: './branding-editor.component.html',
  styleUrl: './branding-editor.component.scss',
})
export class BrandingEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly maxMb = LOGO_MAX_SIZE_MB;
  protected readonly accept = LOGO_ACCEPT_MIME.join(',');
  protected readonly logoSlots: readonly LogoSlot[] = ['wordmark', 'imagemark', 'favicon'];

  protected readonly version = signal(0);
  protected readonly hasDraftChanges = signal(false);
  protected readonly draft = signal<Branding | null>(null);

  /** Currently active language for the preview. */
  protected readonly lang = computed(() => this.i18n.locale());

  /** Disallowed link URLs (scheme ≠ http(s)/mailto) — blocks saving. */
  protected readonly linkErrors = computed(() => brandingLinkErrors(this.draft()));

  /** Version sidebar — reload after activate/restore. */
  protected readonly history = viewChild(VersionHistoryComponent);

  constructor() {
    this.loadConfig();
  }

  /** Load active + draft branding (also after a version restore). */
  protected loadConfig(): void {
    this.api.getSiteConfig().subscribe((cfg) => {
      this.version.set(cfg.version);
      this.hasDraftChanges.set(cfg.hasDraftChanges);
      this.draft.set(cfg.draft);
    });
  }

  protected text(map: Record<string, string> | null | undefined): string {
    return resolveI18n(map, this.lang());
  }

  protected slotLabel(slot: LogoSlot): string {
    return this.i18n.translate(`admin.brand.logo.${slot}` as TranslationKey);
  }

  // --- logos ---------------------------------------------------------------
  protected onLogoSelected(slot: LogoSlot, input: HTMLInputElement): void {
    const file = input.files?.[0];
    if (!file) return;
    if (!LOGO_ACCEPT_MIME.includes(file.type)) {
      this.toast.error(this.i18n.translate('admin.brand.badType'));
      input.value = '';
      return;
    }
    if (file.size > LOGO_MAX_SIZE_MB * 1024 * 1024) {
      this.toast.error(this.i18n.translate('admin.brand.tooLarge', { mb: LOGO_MAX_SIZE_MB }));
      input.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      this.patch((d) => {
        d.logos = {
          ...d.logos,
          [slot]: { url: String(reader.result), filename: file.name, mime: file.type, size: file.size },
        };
      });
    };
    reader.readAsDataURL(file);
    input.value = '';
  }

  protected removeLogo(slot: LogoSlot): void {
    this.patch((d) => {
      const logos = { ...d.logos };
      delete logos[slot];
      d.logos = logos;
    });
  }

  // --- footer --------------------------------------------------------------
  protected addColumn(): void {
    this.patch((d) => {
      d.footerColumns = [...d.footerColumns, { label: { de: '', en: '' }, links: [] }];
    });
  }

  protected removeColumn(i: number): void {
    this.patch((d) => {
      d.footerColumns = d.footerColumns.filter((_, idx) => idx !== i);
    });
  }

  protected moveColumn(i: number, dir: -1 | 1): void {
    this.patch((d) => {
      const next = [...d.footerColumns];
      const j = i + dir;
      if (j < 0 || j >= next.length) return;
      [next[i], next[j]] = [next[j], next[i]];
      d.footerColumns = next;
    });
  }

  protected addLink(col: FooterColumn): void {
    this.patch(() => {
      col.links = [...col.links, { label: { de: '', en: '' }, url: '' }];
    });
  }

  protected removeLink(col: FooterColumn, li: number): void {
    this.patch(() => {
      col.links = col.links.filter((_, idx) => idx !== li);
    });
  }

  protected addLegalLink(): void {
    this.patch((d) => {
      d.legalLinks = [...d.legalLinks, { label: { de: '', en: '' }, url: '' }];
    });
  }

  protected removeLegalLink(i: number): void {
    this.patch((d) => {
      d.legalLinks = d.legalLinks.filter((_, idx) => idx !== i);
    });
  }

  /** Lazy-init the apply info — existing configs don't have this field. */
  protected applyInfo(d: Branding): I18nMap {
    d.freetexts.applyInfo ??= {};
    return d.freetexts.applyInfo;
  }

  /** Re-emit the signal after an in-place `[(ngModel)]` mutation (preview). */
  protected reemit(): void {
    this.patch(() => {
      /* re-emit only */
    });
  }

  /** Apply a mutation on the draft + re-emit the signal (preview/validation). */
  protected patch(fn: (d: Branding) => void): void {
    const d = this.draft();
    if (!d) return;
    fn(d);
    this.draft.set({ ...d });
  }

  // --- persistence ---------------------------------------------------------
  protected saveDraft(): void {
    const d = this.draft();
    if (!d) return;
    if (this.linkErrors().length > 0) {
      this.toast.error(this.i18n.translate('admin.brand.badUrl'));
      return;
    }
    this.api.saveBrandingDraft(d).subscribe({
      next: (cfg) => {
        this.hasDraftChanges.set(cfg.hasDraftChanges);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  protected activate(): void {
    this.api.activateBranding().subscribe({
      next: (cfg) => {
        this.version.set(cfg.version);
        this.hasDraftChanges.set(cfg.hasDraftChanges);
        this.draft.set(cfg.draft);
        this.toast.success(this.i18n.translate('admin.brand.activated', { n: cfg.version }));
        this.history()?.reload();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
