import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import { ButtonComponent } from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
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
  template: `
    <header class="mt__head">
      <h1 class="mt__title">{{ 'admin.mailTemplates.title' | t }}</h1>
      <p class="mt__subtitle">{{ 'admin.mailTemplates.subtitle' | t }}</p>
    </header>

    <div class="mt__layout">
      <nav class="mt__list" [attr.aria-label]="'admin.mailTemplates.title' | t">
        @for (tpl of templates(); track tpl.id) {
          <button
            type="button"
            class="mt__listItem"
            [class.mt__listItem--sel]="selectedId() === tpl.id"
            (click)="select(tpl.id)"
          >
            {{ tpl.key }}
          </button>
        } @empty {
          <p class="mt__muted">{{ 'admin.mailTemplates.empty' | t }}</p>
        }
      </nav>

      @if (draft(); as d) {
        <section class="mt__editor">
          <div class="mt__tabs" role="tablist">
            @for (l of langs; track l) {
              <button
                type="button"
                role="tab"
                class="mt__tab"
                [class.mt__tab--sel]="lang() === l"
                [attr.aria-selected]="lang() === l"
                (click)="lang.set(l)"
              >
                {{ l.toUpperCase() }}
              </button>
            }
          </div>

          <label class="mt__lbl" for="mt-subj">{{ 'admin.mailTemplates.subject' | t }}</label>
          <input
            id="mt-subj"
            class="mt__control"
            [ngModel]="d.subjectI18n[lang()]"
            (ngModelChange)="patch('subjectI18n', $event)"
            name="subject"
          />

          <label class="mt__lbl" for="mt-body">{{ 'admin.mailTemplates.body' | t }}</label>
          <textarea
            id="mt-body"
            class="mt__control mt__area"
            rows="8"
            [ngModel]="d.bodyI18n[lang()]"
            (ngModelChange)="patch('bodyI18n', $event)"
            name="body"
          ></textarea>

          <label class="mt__lbl" for="mt-html">{{ 'admin.mailTemplates.bodyHtml' | t }}</label>
          <textarea
            id="mt-html"
            class="mt__control mt__area"
            rows="6"
            [ngModel]="d.bodyHtmlI18n[lang()]"
            (ngModelChange)="patch('bodyHtmlI18n', $event)"
            name="bodyHtml"
            [placeholder]="'admin.mailTemplates.bodyHtmlPlaceholder' | t"
          ></textarea>

          @if (placeholderList().length) {
            <div class="mt__ph">
              <span class="mt__phHead">{{ 'admin.mailTemplates.placeholders' | t }}:</span>
              @for (p of placeholderList(); track p.key) {
                <code class="mt__chip" [title]="p.desc">{{ p.token }}</code>
              }
            </div>
          }

          <div class="mt__actions">
            <app-button [loading]="saving()" (click)="save()">{{ 'action.save' | t }}</app-button>
            <app-button variant="secondary" [loading]="previewing()" (click)="runPreview()">{{ 'admin.mailTemplates.preview' | t }}</app-button>
          </div>

          @if (preview(); as pv) {
            <div class="mt__preview">
              <h2 class="mt__previewH">{{ 'admin.mailTemplates.previewHeading' | t }} ({{ pv.lang }})</h2>
              <p class="mt__previewSubj"><strong>{{ 'admin.mailTemplates.subject' | t }}:</strong> {{ pv.subject }}</p>
              <pre class="mt__previewText">{{ pv.text }}</pre>
              @if (pv.html) {
                <div class="mt__previewHtml" [innerHTML]="pv.html"></div>
              }
            </div>
          }
        </section>
      } @else {
        <section class="mt__editor mt__muted">{{ 'admin.mailTemplates.selectHint' | t }}</section>
      }
    </div>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .mt__title {
        margin: 0;
      }
      .mt__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .mt__muted {
        color: var(--color-text-muted);
      }
      .mt__layout {
        display: grid;
        grid-template-columns: minmax(10rem, 14rem) 1fr;
        gap: var(--space-5);
        align-items: start;
      }
      @media (max-width: 48rem) {
        .mt__layout {
          grid-template-columns: 1fr;
        }
      }
      .mt__list {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .mt__listItem {
        text-align: start;
        padding: var(--space-2) var(--space-3);
        background: transparent;
        border: var(--border-width) solid transparent;
        border-radius: var(--radius-md);
        cursor: pointer;
        color: var(--color-text);
        font: inherit;
        font-variant-numeric: tabular-nums;
      }
      .mt__listItem:hover {
        background: var(--color-surface-sunken);
      }
      .mt__listItem--sel {
        background: var(--color-surface-sunken);
        border-color: var(--color-border);
        font-weight: var(--fw-semibold);
      }
      .mt__editor {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
        min-width: 0;
      }
      .mt__tabs {
        display: inline-flex;
        gap: var(--space-1);
        margin-bottom: var(--space-2);
      }
      .mt__tab {
        padding: var(--space-1) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        cursor: pointer;
        font: inherit;
        color: var(--color-text-muted);
      }
      .mt__tab--sel {
        background: var(--color-primary);
        color: var(--color-on-primary, #fff);
        border-color: var(--color-primary);
      }
      .mt__lbl {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        margin-top: var(--space-2);
      }
      .mt__control {
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        color: var(--color-text);
        font: inherit;
        width: 100%;
        box-sizing: border-box;
      }
      .mt__area {
        resize: vertical;
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-sm);
      }
      .mt__ph {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--space-2);
        margin-top: var(--space-2);
      }
      .mt__phHead {
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
      .mt__chip {
        font-size: var(--fs-xs);
        padding: 2px var(--space-2);
        background: var(--color-surface-sunken);
        border-radius: var(--radius-sm);
        cursor: help;
      }
      .mt__actions {
        display: flex;
        gap: var(--space-3);
        margin-top: var(--space-3);
      }
      .mt__preview {
        margin-top: var(--space-4);
        padding: var(--space-4);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
      }
      .mt__previewH {
        margin: 0 0 var(--space-2);
        font-size: var(--fs-md);
      }
      .mt__previewSubj {
        margin: 0 0 var(--space-2);
      }
      .mt__previewText {
        white-space: pre-wrap;
        font-family: var(--font-mono, monospace);
        font-size: var(--fs-sm);
        margin: 0;
      }
      .mt__previewHtml {
        margin-top: var(--space-3);
        padding-top: var(--space-3);
        border-top: var(--border-width) solid var(--color-border);
      }
    `,
  ],
})
export class MailTemplatesComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly langs = LANGS;
  private readonly templates_ = signal<MailTemplate[]>([]);
  readonly templates = this.templates_.asReadonly();
  readonly selectedId = signal<string | null>(null);
  readonly draft = signal<MailTemplate | null>(null);
  readonly lang = signal<Lang>('de');
  readonly saving = signal(false);
  readonly previewing = signal(false);
  readonly preview = signal<MailPreview | null>(null);

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
        if (t.length && !this.selectedId()) this.select(t[0].id);
      },
      error: () => this.toast.error(this.i18n.translate('admin.mailTemplates.loadFailed')),
    });
  }

  select(id: string): void {
    const tpl = this.templates_().find((t) => t.id === id);
    if (!tpl) return;
    this.selectedId.set(id);
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
    this.api
      .updateMailTemplate(d.id as Uuid, {
        subjectI18n: d.subjectI18n,
        bodyI18n: d.bodyI18n,
        bodyHtmlI18n: d.bodyHtmlI18n,
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.templates_.update((list) => list.map((t) => (t.id === updated.id ? updated : t)));
          this.toast.success(this.i18n.translate('admin.mailTemplates.saved'));
        },
        error: () => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate('admin.mailTemplates.failed'));
        },
      });
  }

  runPreview(): void {
    const d = this.draft();
    if (!d || this.previewing()) return;
    this.previewing.set(true);
    // Beispiel-Kontext aus den Platzhaltern (Wert = Beschreibung als Platzhaltertext).
    const context: Record<string, unknown> = {};
    for (const [key, desc] of Object.entries(d.placeholders)) context[key] = desc || key;
    this.api.previewMailTemplate(d.id as Uuid, { lang: this.lang(), context }).subscribe({
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
