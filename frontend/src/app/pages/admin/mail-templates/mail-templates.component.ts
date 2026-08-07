import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { MailPreview, MailTemplate } from '../admin.models';

const LANGS = ['de', 'en'] as const;
type Lang = (typeof LANGS)[number];

/**
 * Mail-template editor at `/admin/mail-templates`. Needs the `admin.notifications` permission.
 *
 * The page shows the template list on the left and the editor on the right. The editor has
 * language tabs for subject, text and HTML, a placeholder reference and a live preview.
 */
@Component({
  selector: 'app-mail-templates',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, PageHeaderComponent],
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
  // Select by key, not by ID. A builtin template has no database ID.
  readonly selectedKey = signal<string | null>(null);
  readonly draft = signal<MailTemplate | null>(null);
  readonly lang = signal<Lang>('de');
  readonly saving = signal(false);
  readonly resetting = signal(false);
  readonly previewing = signal(false);
  readonly preview = signal<MailPreview | null>(null);

  /**
   * Localize a template key: `deadline_approaching` becomes "Deadline reminder".
   *
   * An unknown key returns the raw key.
   */
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
    // Copy the i18n maps so that an edit does not mutate the original template.
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
    // Upsert by key. The server creates an override, also for a builtin default.
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

  private applyUpdate(tpl: MailTemplate): void {
    this.templates_.update((list) => list.map((t) => (t.key === tpl.key ? tpl : t)));
    if (this.selectedKey() === tpl.key) this.select(tpl.key);
  }

  runPreview(): void {
    const d = this.draft();
    if (!d || this.previewing()) return;
    this.previewing.set(true);
    // No real values exist at preview time. Use the placeholder description as the sample value.
    const context: Record<string, unknown> = {};
    for (const [key, desc] of Object.entries(d.placeholders)) context[key] = desc || key;
    // Render the draft without an ID. This works for builtin templates and for overrides.
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
