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
} from '@shared/ui';
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
  template: `
    <section class="cfg">
      <header class="cfg__head">
        <div>
          <h1>{{ 'admin.webhook.title' | t }}</h1>
          <p class="cfg__desc">{{ 'admin.webhook.desc' | t }}</p>
        </div>
        <app-button size="sm" (click)="openAdd()">{{ 'admin.webhook.add' | t }}</app-button>
      </header>

      <app-data-table [columns]="columns()" [rows]="hooks()" [emptyText]="'admin.webhook.none' | t">
        <ng-template appCell="active" let-h>
          @if ($any(h).active) {
            <span class="cfg__yes" aria-label="✓">✓</span>
          } @else {
            <span class="cfg__no" aria-label="✗">✗</span>
          }
        </ng-template>
        <ng-template appCell="events" let-h>
          <app-badge variant="neutral">{{ $any(h).events.length }}</app-badge>
        </ng-template>
        <ng-template appCell="actions" let-h let-i="index">
          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'admin.common.edit' | t" (click)="openEdit(i)">
            <app-icon name="edit" />
          </app-button>
        </ng-template>
      </app-data-table>
    </section>

    <app-dialog
      [open]="draft() !== null"
      [title]="(editingIndex() === null ? 'admin.webhook.add' : 'admin.common.edit') | t"
      [closeLabel]="'action.cancel' | t"
      (closed)="close()"
    >
      @if (draft(); as d) {
        <form class="cfg__form" (submit)="$event.preventDefault(); save()">
          <label class="field">
            <span class="field__label">{{ 'admin.webhook.name' | t }}</span>
            <input class="field__control" [ngModel]="d.name" (ngModelChange)="patch('name', $event)" name="name" />
          </label>
          <label class="field">
            <span class="field__label">{{ 'admin.webhook.url' | t }}</span>
            <input class="field__control" [ngModel]="d.url" (ngModelChange)="patch('url', $event)" name="url" placeholder="https://" />
          </label>
          <app-checkbox [ngModel]="d.active" (ngModelChange)="patch('active', $event)" name="active">
            {{ 'admin.webhook.active' | t }}
          </app-checkbox>
          <fieldset class="cfg__events">
            <legend>{{ 'admin.webhook.events' | t }}</legend>
            @for (ev of allEvents; track ev) {
              <app-checkbox [ngModel]="d.events.includes(ev)" (ngModelChange)="toggleEvent(ev)" [name]="'ev-' + ev">
                {{ ev }}
              </app-checkbox>
            }
          </fieldset>
          @if (errors().length > 0) {
            <ul class="cfg__errors" role="alert">
              @for (e of errors(); track e) {
                <li>{{ tr(e) }}</li>
              }
            </ul>
          }
        </form>
      }
      <div dialog-footer class="cfg__dialog-foot">
        <app-button variant="ghost" (click)="close()">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="errors().length > 0" (click)="save()">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>
  `,
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
    if (d.events.length === 0) errs.push('admin.webhook.noEvents');
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
