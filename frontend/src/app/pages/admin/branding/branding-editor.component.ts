import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { BrandingService, DEFAULT_LOGOS } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CATALOG, type TranslationKey } from '@core/i18n/translations';
import { DEFAULT_ACCENT, normalizeHex } from '@core/theme/accent';
import { ThemeService } from '@core/theme/theme.service';
import type { I18nMap } from '@core/api/models';
import {
  defaultSubmittedText,
  SUBMITTED_FREETEXT,
  type SubmittedKind,
} from '@core/branding/submitted-texts';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { FabComponent } from '@shared/ui/fab/fab.component';
import {
  ButtonComponent,
  FilePickerComponent,
  formatBytes,
  IconComponent,
  InputComponent,
  MoveButtonsComponent,
  moveItem,
  NoteComponent,
  SkeletonComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import {
  type Branding,
  type FooterColumn,
  type FooterLink,
  LOGO_ACCEPT_MIME,
  LOGO_MAX_SIZE_MB,
  type LogoSlot,
} from '../admin.models';
import { brandingLinkErrors } from '../branding.util';
import { type ContentLang, ContentLangSwitchComponent } from '@shared/ui/content-lang-switch/content-lang-switch.component';
import { SectionHeaderComponent } from '@shared/ui/section-header/section-header.component';

/** The language of the texts in the editor. */
type TextLang = ContentLang;

/** The free texts in the order of the board. `applyInfo` takes Markdown. */
const FREETEXTS = ['welcome', 'loginHint', 'support', 'emailFooter', 'applyInfo'] as const;
type FreetextKey = (typeof FREETEXTS)[number];

/** The two admin pages of the site config: "Branding" and "Texte". */
export type BrandingSection = 'branding' | 'texts';

/**
 * Branding and site-config editor. One component serves two admin pages, picked by the
 * route data `section`; both save the same site config.
 *
 * - "Branding": the app name, the accent colour, the Gravatar switch and the three logo
 *   slots (Wortmarke, Bildmarke, Favicon; a file with a MIME and a size guard, by drop
 *   or by the file dialog). An empty slot shows the built-in logo. A change of the
 *   accent shows at once on the whole page, before the save.
 * - "Texte": the free texts, the texts after the submission, the footer columns with
 *   their links, the copyright line and the legal links. A text field shows the language
 *   that the switch DE | EN above them picks. An empty field shows the built-in text as its placeholder.
 *
 * The floating button "Speichern" shows only while the screen holds edits that the
 * server does not have. A save applies to everyone at once; there is no draft.
 * A link may carry `http:`, `https:` or `mailto:` only; another scheme blocks the save.
 * It works against `/api/admin/site-config`.
 */
@Component({
  selector: 'app-branding-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FilePickerComponent,
    MoveButtonsComponent,
    NgTemplateOutlet,
    SectionHeaderComponent,
    FabComponent,
    SkeletonComponent,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    ContentLangSwitchComponent,
    SwitchComponent,
    PageHeaderComponent,
  ],
  templateUrl: './branding-editor.component.html',
  styleUrl: './branding-editor.component.scss',
})
export class BrandingEditorComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly brand = inject(BrandingService);
  private readonly theme = inject(ThemeService);

  /** The page this instance shows. */
  protected readonly section: BrandingSection =
    inject(ActivatedRoute).snapshot.data['section'] === 'texts' ? 'texts' : 'branding';

  protected readonly accept = LOGO_ACCEPT_MIME.join(',');
  protected readonly logoSlots: readonly LogoSlot[] = ['wordmark', 'imagemark', 'favicon'];
  protected readonly freetexts = FREETEXTS;
  protected readonly submittedKinds: readonly SubmittedKind[] = ['internal', 'external'];

  /** The edited copy of the active branding. */
  protected readonly draft = signal<Branding | null>(null);
  /** The count of local edits. `patch()` increments it. */
  private readonly editRev = signal(0);
  /** The edit count that the server has. A save, a load or an activate sets it. */
  private readonly savedRev = signal(0);
  /** The screen holds edits that are not saved yet. */
  protected readonly dirty = computed(() => this.editRev() !== this.savedRev());
  /** The save runs. */
  protected readonly saving = signal(false);
  /** The slot a file is dragged over, for the drop look. */
  protected readonly dropSlot = signal<LogoSlot | null>(null);

  /** The language of the text fields. It starts with the language of the page. */
  protected readonly lang = signal<TextLang>(this.i18n.locale() === 'en' ? 'en' : 'de');

  /** Disallowed link URLs. Their scheme is not http, https or mailto. They block a save. */
  protected readonly linkErrors = computed(() => brandingLinkErrors(this.draft()));

  /** The built-in accent: the placeholder of the colour field. */
  protected readonly defaultAccent = DEFAULT_ACCENT;
  /** The accent of the edited copy, or the built-in one. */
  protected readonly accent = computed(() => normalizeHex(this.draft()?.accentColor) ?? DEFAULT_ACCENT);
  /** The edited copy carries an own accent. */
  protected readonly customAccent = computed(() => this.accent() !== DEFAULT_ACCENT);

  constructor() {
    this.loadConfig();
    // An accent that was not saved leaves with the page.
    inject(DestroyRef).onDestroy(() => this.brand.previewAccent(undefined));
  }

  /** Load the active branding. */
  protected loadConfig(): void {
    this.api.getSiteConfig().subscribe((cfg) => {
      this.draft.set(cfg.branding);
      this.markSaved(this.editRev());
      this.brand.applyBranding(cfg.branding);
      this.brand.previewAccent(undefined);
    });
  }

  /** Record that the server has the draft up to the edit count `rev`. */
  private markSaved(rev: number): void {
    this.savedRev.set(rev);
  }

  protected slotLabel(slot: LogoSlot): string {
    return this.i18n.translate(`admin.brand.logo.${slot}` as TranslationKey);
  }

  protected freetextLabel(key: FreetextKey): string {
    return this.i18n.translate(`admin.brand.text.${key}` as TranslationKey);
  }

  /** The field label with the language of the text: "Willkommenstext (DE)". */
  protected withLang(label: string): string {
    return `${label} (${this.lang().toUpperCase()})`;
  }

  protected size(bytes: number): string {
    return formatBytes(bytes, this.i18n.formatLocale());
  }

  /** The built-in logo of a slot, in the colours of the theme. */
  protected defaultLogo(slot: LogoSlot): string {
    const logo = DEFAULT_LOGOS[slot];
    return typeof logo === 'string' ? logo : logo[this.theme.resolved()];
  }

  /** The built-in copyright line in the picked language: the placeholder of the field. */
  protected copyrightDefault(): string {
    return this.builtIn('footer.coBranding');
  }

  /** The built-in app name: the placeholder of the name field. */
  protected appNameDefault(): string {
    return this.builtIn('app.title');
  }

  /** A built-in text in the picked language; German while that catalogue is not loaded. */
  private builtIn(key: TranslationKey): string {
    return CATALOG[this.lang()][key] ?? CATALOG.de[key] ?? '';
  }

  /** The text map of a free text. `applyInfo` is missing in an older config. */
  protected freetext(d: Branding, key: FreetextKey): I18nMap {
    if (key === 'applyInfo') {
      d.freetexts.applyInfo ??= {};
      return d.freetexts.applyInfo;
    }
    return d.freetexts[key];
  }

  protected submittedLabel(kind: SubmittedKind): string {
    return this.i18n.translate(`admin.brand.submitted.${kind}` as TranslationKey);
  }

  /** The text map of a kind. A config from before the feature has none. */
  protected submittedMap(d: Branding, kind: SubmittedKind): I18nMap {
    const key = SUBMITTED_FREETEXT[kind];
    d.freetexts[key] ??= {};
    return d.freetexts[key];
  }

  /** The built-in text in the picked language: the placeholder of the empty field. */
  protected submittedDefault(kind: SubmittedKind): string {
    return defaultSubmittedText(kind, this.lang());
  }

  /** Write the text of the picked language into a map and refresh the draft. */
  protected setText(map: I18nMap, value: string): void {
    this.patch(() => {
      map[this.lang()] = value;
    });
  }

  protected setUrl(link: FooterLink, value: string): void {
    this.patch(() => {
      link.url = value;
    });
  }

  protected setAppName(key: 'appName' | 'appShortName', value: string): void {
    this.patch((d) => {
      d[key] = value;
    });
  }

  protected isBadUrl(url: string): boolean {
    return this.linkErrors().includes(url);
  }

  protected onLogoSelected(slot: LogoSlot, files: File[]): void {
    const file = files[0];
    if (file) this.readLogo(slot, file);
  }

  protected onDragOver(slot: LogoSlot, event: DragEvent): void {
    event.preventDefault();
    this.dropSlot.set(slot);
  }

  protected onDragLeave(): void {
    this.dropSlot.set(null);
  }

  protected onDrop(slot: LogoSlot, event: DragEvent): void {
    event.preventDefault();
    this.dropSlot.set(null);
    const file = event.dataTransfer?.files?.[0];
    if (file) this.readLogo(slot, file);
  }

  /** Check the type and the size, then keep the file as a data URL in the draft. */
  private readLogo(slot: LogoSlot, file: File): void {
    if (!LOGO_ACCEPT_MIME.includes(file.type)) {
      this.toast.error(this.i18n.translate('admin.brand.badType'));
      return;
    }
    if (file.size > LOGO_MAX_SIZE_MB * 1024 * 1024) {
      this.toast.error(this.i18n.translate('admin.brand.tooLarge', { mb: LOGO_MAX_SIZE_MB }));
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
      d.footerColumns = moveItem(d.footerColumns, i, dir);
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

  /**
   * Set the accent colour, or the built-in one for null. The whole page shows it at
   * once; the save keeps it.
   */
  protected setAccent(value: string | null): void {
    const hex = value === null ? null : normalizeHex(value);
    if (value !== null && !hex) return;
    const accent = hex === DEFAULT_ACCENT ? null : hex;
    this.patch((d) => {
      d.accentColor = accent;
    });
    this.brand.previewAccent(accent);
  }

  /** Turn the Gravatar images of the avatars on or off (saved with the config). */
  protected setGravatar(on: boolean): void {
    this.patch((d) => {
      d.gravatarEnabled = on;
    });
  }

  /** Change the draft and emit the signal again, for the validation and the dirty mark. */
  protected patch(fn: (d: Branding) => void): void {
    const d = this.draft();
    if (!d) return;
    fn(d);
    this.draft.set({ ...d });
    this.editRev.update((n) => n + 1);
  }

  /** Save the branding. It applies to everyone at once. */
  protected save(): void {
    const d = this.draft();
    if (!d || this.saving()) return;
    if (this.linkErrors().length > 0) {
      this.toast.error(this.i18n.translate('admin.brand.badUrl'));
      return;
    }
    const rev = this.editRev();
    this.saving.set(true);
    this.api.saveSiteConfig(d).subscribe({
      next: (cfg) => {
        this.saving.set(false);
          this.markSaved(rev);
        this.brand.applyBranding(cfg.branding);
        this.brand.previewAccent(undefined);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }
}
