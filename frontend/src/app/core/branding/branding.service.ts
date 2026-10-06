import { Injectable, Injector, computed, effect, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ApiClient } from '@core/api/api-client.service';
import type {
  AttachmentLimits,
  I18nMap,
  PublicFooterColumn,
  PublicFooterLink,
  PublicSiteConfig,
} from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';

/** The free texts of the branding, keyed by their slot. */
export type FreeTexts = NonNullable<NonNullable<PublicSiteConfig['branding']>['freetexts']>;

/**
 * App name from the active site config, which needs no authentication.
 *
 * This service is the single source of truth for the configurable branding. It loads
 * the public config once at app start and exposes the app name, the footer copyright
 * and the footer legal links as signals. The header (aria-label), the home page (H1)
 * and the footer read them, and it also sets `document.title`.
 *
 * Fallback: when the config name is empty or not yet loaded, the existing i18n
 * texts apply. `app.title` gives the full name and `home.heading` gives the H1.
 * An empty title or heading therefore never appears. The backend serves the PWA
 * manifest (name/short_name) dynamically and separately.
 */
@Injectable({ providedIn: 'root' })
export class BrandingService {
  // Resolve `ApiClient` (→ HttpClient) in `init()`, not in the field initializer.
  // Otherwise the root `BrandingService` pulls HttpClient into every component
  // that injects it, and their specs fail with NG0201 (no HttpClient provider).
  private readonly injector = inject(Injector);
  private readonly i18n = inject(I18nService);
  private readonly title = inject(Title);

  /** Configured full name (empty ⇒ fallback). */
  private readonly _configuredName = signal('');

  /* Footer content comes from the PUBLIC config, which needs no session. A logged-out
     visitor on the landing page or the 404 sees what the admin configured; reading it
     from `/admin/site-config` would refuse that request and fall back to the defaults. */
  private readonly _copyright = signal<I18nMap | null>(null);
  private readonly _legalLinks = signal<PublicFooterLink[]>([]);
  private readonly _footerColumns = signal<PublicFooterColumn[]>([]);

  /** Default confirmation window of a guest application, in hours. */
  static readonly DEFAULT_CONFIRM_TTL_HOURS = 12;

  private readonly _confirmTtlHours = signal(BrandingService.DEFAULT_CONFIRM_TTL_HOURS);

  /** The upload limits of the backend defaults (10 MB per file, 20 files, 50 MB). */
  static readonly DEFAULT_ATTACHMENT_LIMITS: AttachmentLimits = {
    maxFileBytes: 10 * 1024 * 1024,
    maxDraftFiles: 20,
    maxDraftBytes: 50 * 1024 * 1024,
  };

  private readonly _linkTtlDays = signal<number | null>(null);
  private readonly _attachmentLimits = signal<AttachmentLimits>(
    BrandingService.DEFAULT_ATTACHMENT_LIMITS,
  );
  private readonly _freetexts = signal<FreeTexts>({});

  private readonly _loaded = signal(false);

  private readonly _gravatarEnabled = signal(true);

  /**
   * The admin switch for the Gravatar images of the avatars (`gravatarEnabled`). An older
   * config without the field counts as on. Read {@link loaded} as well: the avatars load
   * no image before the config is there.
   */
  readonly gravatarEnabled = this._gravatarEnabled.asReadonly();

  /**
   * Days a new magic link works; `null` means that it does not expire. The default of
   * the backend is `null`, and the value stays so until the config is loaded. Read
   * {@link loaded} before a text says "unbegrenzt".
   */
  readonly linkTtlDays = this._linkTtlDays.asReadonly();

  /** True after the public config loaded. A failed load keeps it false. */
  readonly loaded = this._loaded.asReadonly();

  /** The upload limits of the wizard (Z4). The backend defaults until the config loads. */
  readonly attachmentLimits = this._attachmentLimits.asReadonly();

  /** The free texts of the branding (Freitexte), per locale. Empty until loaded. */
  readonly freetexts = this._freetexts.asReadonly();

  /**
   * Hours a guest has to confirm the email. The wizard confirmation page shows it.
   * The value is the backend default (12) until the config is loaded.
   */
  readonly confirmTtlHours = this._confirmTtlHours.asReadonly();

  /** Footer copyright per locale, or `null` for the built-in co-branding text. */
  readonly copyright = this._copyright.asReadonly();
  /** Maintained footer links; empty means the built-in imprint/privacy pair. */
  readonly legalLinks = this._legalLinks.asReadonly();
  /** Footer columns, each a heading and its links. */
  readonly footerColumns = this._footerColumns.asReadonly();

  /**
   * Full app name: the config value, else i18n `app.title`. The value reacts to
   * a language change through the i18n fallback and to the config load.
   */
  readonly appName = computed(
    () => this._configuredName().trim() || this.i18n.translate('app.title'),
  );

  /**
   * Home heading (H1): the config value, else i18n `home.heading`. By design the
   * configured name replaces the WHOLE heading. It gets no "Workflow" suffix.
   */
  readonly homeHeading = computed(
    () => this._configuredName().trim() || this.i18n.translate('home.heading'),
  );

  constructor() {
    effect(() => this.title.setTitle(this.appName()));
  }

  /** Call once at app start. Loads the active branding config and ignores failures. */
  init(): void {
    this.injector.get(ApiClient).publicSiteConfig().subscribe({
      next: (cfg) => {
        this._configuredName.set(cfg.branding?.appName ?? '');
        this._copyright.set(cfg.branding?.copyright ?? null);
        this._legalLinks.set(cfg.branding?.legalLinks ?? []);
        this._footerColumns.set(cfg.branding?.footerColumns ?? []);
        if (typeof cfg.confirmTtlHours === 'number' && cfg.confirmTtlHours > 0) {
          this._confirmTtlHours.set(cfg.confirmTtlHours);
        }
        if (typeof cfg.linkTtlDays === 'number' && cfg.linkTtlDays > 0) {
          this._linkTtlDays.set(cfg.linkTtlDays);
        }
        if (cfg.attachmentLimits) this._attachmentLimits.set(cfg.attachmentLimits);
        this._freetexts.set(cfg.branding?.freetexts ?? {});
        this._gravatarEnabled.set(cfg.branding?.gravatarEnabled !== false);
        this._loaded.set(true);
      },
      error: () => {
        /* Keep everything empty so the i18n default fallbacks stay. */
      },
    });
  }
}
