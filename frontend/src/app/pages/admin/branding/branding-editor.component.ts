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
import type { I18nMap } from '@core/api/models';
import { NoteComponent } from '@shared/ui/note/note.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { RowMenuComponent, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import {
  ButtonComponent,
  IconComponent,
  InputComponent,
  MEDIA,
  SegmentedComponent,
  type SegmentedOption,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { AdminApiService } from '../admin-api.service';
import { formatBytes } from '../admin-health/admin-health.util';
import { VersionHistoryComponent } from '../version-history/version-history.component';
import {
  type Branding,
  type FooterColumn,
  type FooterLink,
  LOGO_ACCEPT_MIME,
  LOGO_MAX_SIZE_MB,
  type LogoSlot,
} from '../admin.models';
import { brandingLinkErrors } from '../branding.util';

/** The language of the texts in the editor. */
type TextLang = 'de' | 'en';

/** The free texts in the order of the board. `applyInfo` takes Markdown. */
const FREETEXTS = ['welcome', 'loginHint', 'support', 'emailFooter', 'applyInfo'] as const;
type FreetextKey = (typeof FREETEXTS)[number];

/**
 * Branding and site-config editor (board Admin-Branding).
 *
 * The header saves the draft ("Entwurf speichern") and activates it ("Entwurf
 * aktivieren"); the line under it names the active version and whether the draft holds
 * changes that are not active yet. The left column holds the app name, the three logo
 * slots (Wortmarke, Bildmarke, Favicon; a file with a MIME and a size guard, by drop or
 * by the file dialog) and the free texts, including the e-mail footer (gaps N43). The
 * right column holds the footer columns with their links (gaps N43), the copyright line
 * and the legal links. A text field shows the language that "Texte in" picks.
 *
 * A link may carry `http:`, `https:` or `mailto:` only; another scheme blocks the save.
 * The version list below restores an older version. It works against
 * `/api/admin/site-config`.
 */
@Component({
  selector: 'app-branding-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    RowMenuComponent,
    SegmentedComponent,
    SwitchComponent,
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
  protected readonly freetexts = FREETEXTS;

  protected readonly version = signal(0);
  protected readonly hasDraftChanges = signal(false);
  protected readonly draft = signal<Branding | null>(null);
  /** The slot a file is dragged over, for the drop look. */
  protected readonly dropSlot = signal<LogoSlot | null>(null);

  /** The language of the text fields. It starts with the language of the page. */
  protected readonly lang = signal<TextLang>(this.i18n.locale() === 'en' ? 'en' : 'de');
  protected readonly langOptions: SegmentedOption[] = [
    { value: 'de', label: 'DE' },
    { value: 'en', label: 'EN' },
  ];

  /** Disallowed link URLs. Their scheme is not http, https or mailto. They block a save. */
  protected readonly linkErrors = computed(() => brandingLinkErrors(this.draft()));

  /** Activate needs a saved draft with changes and valid links. */
  protected readonly canActivate = computed(() => this.hasDraftChanges() && this.linkErrors().length === 0);

  /** Phone: the header keeps "Entwurf speichern"; the activate is in a menu. */
  protected readonly phone = mediaQuerySignal(MEDIA.phone);
  protected readonly phoneMenu = computed<RowMenuSection[]>(() => [
    {
      items: [
        {
          id: 'activate',
          label: this.i18n.translate('admin.brand.activate'),
          icon: 'check',
          disabledReason: this.canActivate() ? null : this.i18n.translate('admin.brand.nothingToActivate'),
        },
      ],
    },
  ]);

  /** Version sidebar. Reload it after an activate or a restore. */
  protected readonly history = viewChild(VersionHistoryComponent);

  constructor() {
    this.loadConfig();
  }

  /** Load the active branding and the draft, also after a version restore. */
  protected loadConfig(): void {
    this.api.getSiteConfig().subscribe((cfg) => {
      this.version.set(cfg.version);
      this.hasDraftChanges.set(cfg.hasDraftChanges);
      this.draft.set(cfg.draft);
    });
  }

  protected setLang(value: string | null): void {
    this.lang.set(value === 'en' ? 'en' : 'de');
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
    return formatBytes(bytes, this.i18n);
  }

  /** The text map of a free text. `applyInfo` is missing in an older config. */
  protected freetext(d: Branding, key: FreetextKey): I18nMap {
    if (key === 'applyInfo') {
      d.freetexts.applyInfo ??= {};
      return d.freetexts.applyInfo;
    }
    return d.freetexts[key];
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

  /** The column heading in one language; both stand side by side. */
  protected setColumnLabel(col: FooterColumn, lang: TextLang, value: string): void {
    this.patch(() => {
      col.label[lang] = value;
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

  protected onLogoSelected(slot: LogoSlot, input: HTMLInputElement): void {
    const file = input.files?.[0];
    input.value = '';
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

  /** Turn the Gravatar images of the avatars on or off (saved with the draft). */
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
