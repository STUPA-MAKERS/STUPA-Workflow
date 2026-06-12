import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import { ButtonComponent } from '@shared/ui';
import { ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
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
 * Branding-/Site-Config-Editor (#21, T-34). Macht Logos, Fußzeile und Freitexte
 * über die UI pflegbar statt im Code. Logo-Upload mit Vorschau + mime/size-Guard,
 * Footer-Link-Spalten, i18n-Freitexte, **Live-Vorschau** und Versionierung
 * (aktiv vs. Entwurf) mit Aktivieren-Button.
 *
 * Gegen `/api/admin/site-config` (T-34-Contract — **kein** SDS-Endpunkt, im Mock
 * bedient). Erzeugt valides `branding`-JSON; TODO(T-24/#21): `branding`-Schema
 * aus `/admin/config-schemas` gegenprüfen, sobald Backend es exportiert.
 */
@Component({
  selector: 'app-branding-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent],
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

  /** Aktiv-genutzte Sprache für die Vorschau. */
  protected readonly lang = computed(() => this.i18n.locale());

  /** Unzulässige Link-URLs (Schema ≠ http(s)/mailto) — blockiert Speichern. */
  protected readonly linkErrors = computed(() => brandingLinkErrors(this.draft()));

  constructor() {
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

  /** Antrags-Info (#18) lazy initialisieren — Bestands-Configs kennen das Feld nicht. */
  protected applyInfo(d: Branding): I18nMap {
    d.freetexts.applyInfo ??= {};
    return d.freetexts.applyInfo;
  }

  /** Nach In-Place-`[(ngModel)]`-Mutation das Signal neu emittieren (Vorschau). */
  protected reemit(): void {
    this.patch(() => {
      /* nur re-emit */
    });
  }

  /** Mutation am Entwurf ausführen + Signal neu emittieren (Vorschau/Validierung). */
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
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
