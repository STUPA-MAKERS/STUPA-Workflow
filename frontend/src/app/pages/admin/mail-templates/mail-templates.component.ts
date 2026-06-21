import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { MailPreview, MailTemplate } from '../admin.models';

const LANGS = ['de', 'en'] as const;
type Lang = (typeof LANGS)[number];

/**
 * Mail-Template-Editor (#5-4). Eigene Admin-Seite (`/admin/mail-templates`,
 * P `admin.notifications`): Liste der Templates links, Editor rechts mit
 * Sprach-Tabs für Betreff/Text/HTML, Platzhalter-Referenz und Live-Vorschau.
 */
@Component({
  selector: 'app-mail-templates',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent],
  templateUrl: './mail-templates.component.html',
  styleUrl: './mail-templates.component.scss',
})
export class MailTemplatesComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly langs = LANGS;
  private readonly templates_ = signal<MailTemplate[]>([]);
  readonly templates = this.templates_.asReadonly();
  // Auswahl per Key, nicht ID: Builtins (#12) haben keine DB-ID.
  readonly selectedKey = signal<string | null>(null);
  readonly draft = signal<MailTemplate | null>(null);
  readonly lang = signal<Lang>('de');
  readonly saving = signal(false);
  readonly resetting = signal(false);
  readonly previewing = signal(false);
  readonly preview = signal<MailPreview | null>(null);

  /** Template-Key lokalisiert (deadline_approaching → »Frist-Erinnerung« …);
   *  unbekannt → roher Key (#mail-template-keys). */
  keyLabel(key: string): string {
    const k = `admin.mailTemplates.key.${key}`;
    const label = this.i18n.translate(k as TranslationKey);
    return label === k ? key : label;
  }

  readonly placeholderList = computed<{ key: string; desc: string; token: string }[]>(() => {
    const d = this.draft();
    if (!d) return [];
    return Object.entries(d.placeholders).map(([key, desc]) => ({
      key,
      desc,
      token: `{{ ${key} }}`,
    }));
  });

  constructor() {
    this.api.listMailTemplates().subscribe({
      next: (t) => {
        this.templates_.set(t);
        if (t.length && !this.selectedKey()) this.select(t[0].key);
      },
      error: () => this.toast.error(this.i18n.translate('admin.mailTemplates.loadFailed')),
    });
  }

  select(key: string): void {
    const tpl = this.templates_().find((t) => t.key === key);
    if (!tpl) return;
    this.selectedKey.set(key);
    this.preview.set(null);
    // Tiefe Kopie der i18n-Maps, damit das Editieren das Original nicht mutiert.
    this.draft.set({
      ...tpl,
      subjectI18n: { ...tpl.subjectI18n },
      bodyI18n: { ...tpl.bodyI18n },
      bodyHtmlI18n: { ...tpl.bodyHtmlI18n },
      placeholders: { ...tpl.placeholders },
    });
  }

  patch(field: 'subjectI18n' | 'bodyI18n' | 'bodyHtmlI18n', value: string): void {
    const d = this.draft();
    if (!d) return;
    this.draft.set({ ...d, [field]: { ...d[field], [this.lang()]: value } });
  }

  save(): void {
    const d = this.draft();
    if (!d || this.saving()) return;
    this.saving.set(true);
    // Upsert per Key (#12): erzeugt eine Override, auch für Builtin-Defaults.
    this.api
      .upsertMailTemplate({
        key: d.key,
        subjectI18n: d.subjectI18n,
        bodyI18n: d.bodyI18n,
        bodyHtmlI18n: d.bodyHtmlI18n,
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.applyUpdate(updated);
          this.toast.success(this.i18n.translate('admin.mailTemplates.saved'));
        },
        error: () => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate('admin.mailTemplates.failed'));
        },
      });
  }

  reset(): void {
    const d = this.draft();
    if (!d || this.resetting()) return;
    this.resetting.set(true);
    this.api.resetMailTemplate(d.key).subscribe({
      next: (builtin) => {
        this.resetting.set(false);
        this.applyUpdate(builtin);
        this.toast.success(this.i18n.translate('admin.mailTemplates.resetDone'));
      },
      error: () => {
        this.resetting.set(false);
        this.toast.error(this.i18n.translate('admin.mailTemplates.failed'));
      },
    });
  }

  /** Aktualisierte/zurückgesetzte Version in Liste + Editor übernehmen. */
  private applyUpdate(tpl: MailTemplate): void {
    this.templates_.update((list) => list.map((t) => (t.key === tpl.key ? tpl : t)));
    if (this.selectedKey() === tpl.key) this.select(tpl.key);
  }

  runPreview(): void {
    const d = this.draft();
    if (!d || this.previewing()) return;
    this.previewing.set(true);
    // Beispiel-Kontext aus den Platzhaltern (Wert = Beschreibung als Platzhaltertext).
    const context: Record<string, unknown> = {};
    for (const [key, desc] of Object.entries(d.placeholders)) context[key] = desc || key;
    // Entwurf rendern (ohne ID): funktioniert für Builtins und Overrides (#12).
    this.api
      .previewMailPayload({
        subjectI18n: d.subjectI18n,
        bodyI18n: d.bodyI18n,
        bodyHtmlI18n: d.bodyHtmlI18n,
        lang: this.lang(),
        context,
      })
      .subscribe({
        next: (pv) => {
          this.previewing.set(false);
          this.preview.set(pv);
        },
        error: () => {
          this.previewing.set(false);
          this.toast.error(this.i18n.translate('admin.mailTemplates.previewFailed'));
        },
      });
  }
}
