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
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
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
 * Branding and site-config editor. It makes the logos, the footer and the free texts
 * editable in the UI instead of in code. It holds a logo upload with a preview. The upload
 * has a MIME guard and a size guard. It also holds footer link columns, i18n free texts and
 * a live preview. It versions the active config against the draft and adds an activate
 * button.
 *
 * It works against `/api/admin/site-config`. That route is not part of the API spec. The mock
 * serves it. The editor writes valid `branding` JSON.
 */
@Component({
  selector: 'app-branding-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    VersionHistoryComponent,
    PageHeaderComponent,
  ],
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
  protected readonly loadFailed = signal(false);

  protected readonly lang = computed(() => this.i18n.locale());

  /** Disallowed link URLs. Their scheme is not http, https or mailto. They block a save. */
  protected readonly linkErrors = computed(() => brandingLinkErrors(this.draft()));

  /** Version sidebar. Reload it after an activate or a restore. */
  protected readonly history = viewChild(VersionHistoryComponent);

  constructor() {
    this.loadConfig();
  }

  /** Load the active branding and the draft, also after a version restore. */
  protected loadConfig(): void {
    this.loadFailed.set(false);
    this.api.getSiteConfig().subscribe({
      next: (cfg) => {
        this.version.set(cfg.version);
        this.hasDraftChanges.set(cfg.hasDraftChanges);
        this.draft.set(cfg.draft);
      },
      error: () => this.loadFailed.set(true),
    });
  }

  protected text(map: Record<string, string> | null | undefined): string {
    return resolveI18n(map, this.lang());
  }

  protected slotLabel(slot: LogoSlot): string {
    return this.i18n.translate(`admin.brand.logo.${slot}` as TranslationKey);
  }

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

  /** Create the apply info on first use. An older config does not have this field. */
  protected applyInfo(d: Branding): I18nMap {
    d.freetexts.applyInfo ??= {};
    return d.freetexts.applyInfo;
  }

  /** Emit the signal again after an in-place `[(ngModel)]` change, to refresh the preview. */
  protected reemit(): void {
    this.patch(() => {
      /* re-emit only */
    });
  }

  /** Change the draft and emit the signal again, for the preview and the validation. */
  protected patch(fn: (d: Branding) => void): void {
    const d = this.draft();
    if (!d) return;
    fn(d);
    this.draft.set({ ...d });
  }

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
