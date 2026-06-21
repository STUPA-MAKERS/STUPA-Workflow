import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { EVENT_NAMES, type EventName, type WebhookConfig } from '../admin.models';

function emptyHook(): WebhookConfig {
  return { id: '', name: '', url: '', events: [], active: true };
}

/**
 * Webhook-Config-UI (T-34, api.md `/admin/webhooks`). Header mit Anlegen-Button,
 * Liste als geteilte {@link DataTableComponent}, Anlegen/Bearbeiten über einen
 * **Dialog** (#19/#39). Client-Validierung: gültige http(s)-URL + mind. ein Ereignis.
 */
@Component({
  selector: 'app-webhooks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    BadgeComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
  ],
  templateUrl: './webhooks.component.html',
  styleUrl: './config.shared.scss',
})
export class WebhooksComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly allEvents = EVENT_NAMES;
  protected readonly hooks = signal<WebhookConfig[]>([]);
  protected readonly draft = signal<WebhookConfig | null>(null);
  protected readonly editingIndex = signal<number | null>(null);

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'name', label: this.i18n.translate('admin.webhook.name') },
    { key: 'url', label: this.i18n.translate('admin.webhook.url') },
    { key: 'events', label: this.i18n.translate('admin.webhook.events'), align: 'start', width: '7rem' },
    { key: 'active', label: this.i18n.translate('admin.webhook.active'), align: 'start', width: '6rem' },
    { key: 'actions', label: this.i18n.translate('admin.common.actions'), align: 'end', width: '6rem' },
  ]);

  protected readonly errors = computed(() => {
    const d = this.draft();
    if (!d) return [] as string[];
    const errs: string[] = [];
    if (!/^https?:\/\/.+/i.test(d.url)) errs.push('admin.webhook.badUrl');
    // Trigger sind optional (TASKS #6) — sie kommen i. d. R. aus dem Flow-Graph.
    return errs;
  });

  constructor() {
    this.api.listWebhooks().subscribe((h) => this.hooks.set(h));
  }

  protected tr(key: string): string {
    return this.i18n.translate(key as TranslationKey);
  }

  protected openAdd(): void {
    this.editingIndex.set(null);
    this.draft.set(emptyHook());
  }

  protected openEdit(i: number): void {
    this.editingIndex.set(i);
    this.draft.set({ ...this.hooks()[i], events: [...this.hooks()[i].events] });
  }

  protected close(): void {
    this.draft.set(null);
    this.editingIndex.set(null);
  }

  protected patch<K extends keyof WebhookConfig>(key: K, value: WebhookConfig[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected toggleEvent(ev: EventName): void {
    this.draft.update((d) => {
      if (!d) return d;
      const events = d.events.includes(ev)
        ? d.events.filter((e) => e !== ev)
        : [...d.events, ev];
      return { ...d, events };
    });
  }

  protected save(): void {
    const d = this.draft();
    if (!d || this.errors().length > 0) return;
    const idx = this.editingIndex();
    this.api.saveWebhook(d).subscribe({
      next: (saved) => {
        this.hooks.update((list) =>
          idx === null ? [...list, saved] : list.map((h, i) => (i === idx ? saved : h)),
        );
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.close();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
