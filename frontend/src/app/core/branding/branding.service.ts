import { Injectable, Injector, computed, effect, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ApiClient } from '@core/api/api-client.service';
import type {
  AttachmentLimits,
  I18nMap,
  PublicFooterLink,
  PublicSiteConfig,
} from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { applyAccent, normalizeHex } from '@core/theme/accent';
import { ThemeService } from '@core/theme/theme.service';

/** The free texts of the branding, keyed by their slot. */
export type FreeTexts = NonNullable<NonNullable<PublicSiteConfig['branding']>['freetexts']>;

/** The branding part of the public config. */
type PublicBranding = NonNullable<PublicSiteConfig['branding']>;

/** A logo slot of the branding. */
export type BrandLogoSlot = 'wordmark' | 'imagemark' | 'favicon';

/**
 * The built-in logos, which show while a slot holds no upload. The wordmark comes in a
 * light and a dark variant (black or white type); the mark and the favicon serve both
 * themes.
 */
export const DEFAULT_LOGOS = {
  wordmark: { light: 'assets/logos/stupa-wordmark-light.svg', dark: 'assets/logos/stupa-wordmark-dark.svg' },
  imagemark: 'assets/logos/stupa-mark.svg',
  favicon: 'favicon.ico',
} as const;

/**
 * The accent of the last loaded config, kept in the browser. The service applies it at
 * once on the next start, so the page does not show the built-in green until the config
 * has loaded.
 */
const ACCENT_KEY = 'ap.accent';

/**
 * App name from the active site config, which needs no authentication.
 *
 * This service is the single source of truth for the configurable branding. It loads
 * the public config once at app start and exposes the app name, the footer copyright
 * and the footer legal links as signals. The header (aria-label), the home page (H1)
 * and the footer read them, and it also sets `document.title`.
 *
 * It also applies the accent colour of the config to the theme tokens (`core/theme/accent`)
 * and gives the logos of the config, with the built-in logos for an empty slot.
 *
 * Fallback: when the config name is empty or not yet loaded, the existing i18n
 * texts apply. `app.title` gives the full name and `home.heading` gives the H1.
 * An empty title or heading therefore never appears. The backend serves the PWA
 * manifest (name/short_name) dynamically and separately.
 */
@Injectable({ providedIn: 'root' })
export class BrandingService {
  /**
   * Resolves `ApiClient` (→ HttpClient) in `init()`, not in the field initializer, because
   * otherwise the root `BrandingService` pulls HttpClient into every component that injects
   * it, and their specs fail with NG0201 (no HttpClient provider).
   */
  private readonly injector = inject(Injector);
  private readonly i18n = inject(I18nService);
  private readonly title = inject(Title);
  private readonly theme = inject(ThemeService);

  /** Configured full name (empty ⇒ fallback). */
  private readonly _configuredName = signal('');

  /**
   * The footer copyright. Footer content comes from the PUBLIC config, which needs no
   * session. A logged-out visitor on the landing page or the 404 sees what the admin
   * configured, because `/admin/site-config` would refuse that request and fall back to the
   * defaults.
   */
  private readonly _copyright = signal<I18nMap | null>(null);
  private readonly _legalLinks = signal<PublicFooterLink[]>([]);

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

  /** The accent colour of the active config (`#rrggbb`), or null for the built-in one. */
  private readonly _accent = signal<string | null>(readStoredAccent());
  /** An accent that the branding editor shows before the save, or undefined for none. */
  private readonly _accentPreview = signal<string | null | undefined>(undefined);
  private readonly _logos = signal<Partial<Record<BrandLogoSlot, string>>>({});

  /** The accent colour of the active config, or null for the built-in one. */
  readonly accentColor = this._accent.asReadonly();

  /** The wordmark in the colours of the theme: the upload, else the built-in variant. */
  readonly wordmarkSrc = computed(
    () => this._logos().wordmark ?? DEFAULT_LOGOS.wordmark[this.theme.resolved()],
  );
  /** The mark without the wordmark: the upload, else the built-in mark. */
  readonly markSrc = computed(() => this._logos().imagemark ?? DEFAULT_LOGOS.imagemark);
  /** The icon of the browser tab: the upload, else the built-in favicon. */
  readonly faviconSrc = computed(() => this._logos().favicon ?? DEFAULT_LOGOS.favicon);
  /** The uploaded logo of a slot, or null while the built-in one shows. */
  logoUpload(slot: BrandLogoSlot): string | null {
    return this._logos()[slot] ?? null;
  }

  /** The handbook of the platform: the default of the backend until the config loads. */
  static readonly DEFAULT_WIKI_URL = 'https://wiki.reutlingen.university/books/antragsplattform';

  private readonly _wikiUrl = signal(BrandingService.DEFAULT_WIKI_URL);
  private readonly _ticketsPublic = signal(false);

  /** The link "Handbuch" of the help menu (`help.wikiUrl`). */
  readonly wikiUrl = this._wikiUrl.asReadonly();

  /**
   * A visitor without a session may send a ticket (`tickets.publicEnabled`). False until
   * the config loads, so the public header never offers a form the server refuses.
   */
  readonly ticketsPublic = this._ticketsPublic.asReadonly();

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

  /** The upload limits of the wizard. The backend defaults until the config loads. */
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

  /**
   * index.html links the built-in icons; an upload replaces each of them, and an empty slot puts
   * the built-in href back.
   */
  constructor() {
    effect(() => this.title.setTitle(this.appName()));
    effect(() => {
      const preview = this._accentPreview();
      applyAccent(preview === undefined ? this._accent() : preview);
    });
    const builtIn = new Map<HTMLLinkElement, string>();
    effect(() => {
      const upload = this._logos().favicon;
      document.querySelectorAll<HTMLLinkElement>('link[rel="icon"]').forEach((link) => {
        let original = builtIn.get(link);
        if (original === undefined) {
          original = link.getAttribute('href') ?? '';
          builtIn.set(link, original);
        }
        link.setAttribute('href', upload ?? original);
        if (upload) link.removeAttribute('type');
      });
    });
  }

  /**
   * Show an accent before it is saved, app-wide, so the editor shows its effect on the
   * real page. `undefined` ends the preview and the saved accent applies again.
   */
  previewAccent(accent: string | null | undefined): void {
    this._accentPreview.set(accent === undefined ? undefined : normalizeHex(accent));
  }

  /** Take the branding parts that the whole app shows: after the load and after a save. */
  applyBranding(branding: PublicBranding | null | undefined): void {
    this._configuredName.set(branding?.appName ?? '');
    this._copyright.set(branding?.copyright ?? null);
    this._legalLinks.set(branding?.legalLinks ?? []);
    this._freetexts.set(branding?.freetexts ?? {});
    this._gravatarEnabled.set(branding?.gravatarEnabled !== false);
    const accent = normalizeHex(branding?.accentColor);
    this._accent.set(accent);
    storeAccent(accent);
    const logos: Partial<Record<BrandLogoSlot, string>> = {};
    for (const slot of ['wordmark', 'imagemark', 'favicon'] as const) {
      const url = branding?.logos?.[slot]?.url;
      if (url) logos[slot] = url;
    }
    this._logos.set(logos);
  }

  /**
   * Call once at app start. Loads the active branding config and ignores failures: a failed
   * load keeps everything empty, so the i18n default fallbacks stay.
   */
  init(): void {
    this.injector.get(ApiClient).publicSiteConfig().subscribe({
      next: (cfg) => {
        this.applyBranding(cfg.branding);
        if (typeof cfg.confirmTtlHours === 'number' && cfg.confirmTtlHours > 0) {
          this._confirmTtlHours.set(cfg.confirmTtlHours);
        }
        if (typeof cfg.linkTtlDays === 'number' && cfg.linkTtlDays > 0) {
          this._linkTtlDays.set(cfg.linkTtlDays);
        }
        if (cfg.attachmentLimits) this._attachmentLimits.set(cfg.attachmentLimits);
        if (cfg.help?.wikiUrl) this._wikiUrl.set(cfg.help.wikiUrl);
        this._ticketsPublic.set(cfg.tickets?.publicEnabled === true);
        this._loaded.set(true);
      },
      error: () => {},
    });
  }
}

function readStoredAccent(): string | null {
  try {
    return normalizeHex(localStorage.getItem(ACCENT_KEY));
  } catch {
    return null;
  }
}

function storeAccent(accent: string | null): void {
  try {
    if (accent) localStorage.setItem(ACCENT_KEY, accent);
    else localStorage.removeItem(ACCENT_KEY);
  } catch {
    /* ignore */
  }
}
