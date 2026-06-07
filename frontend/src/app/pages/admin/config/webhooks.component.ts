import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent } from '@shared/ui';
import { ToastService } from '@shared/ui';
import { AdminApiService } from '../admin-api.service';
import { EVENT_NAMES, type EventName, type WebhookConfig } from '../admin.models';

/**
 * Webhook-Config-UI (T-34, api.md `/admin/webhooks`). CRUD über die admin-API
 * (im Mock-Modus In-Memory). Client-Validierung: gültige http(s)-URL + mind. ein
 * Ereignis aus der Whitelist (`EventName`).
 */
@Component({
  selector: 'app-webhooks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent],
  template: `
    <section class="cfg">
      <header class="cfg__head">
        <h1>{{ 'admin.webhook.title' | t }}</h1>
        <app-button variant="secondary" size="sm" (click)="add()">{{ 'admin.webhook.add' | t }}</app-button>
      </header>

      @if (hooks().length === 0) {
        <p class="cfg__empty">{{ 'admin.webhook.none' | t }}</p>
      }

      @for (hook of hooks(); track $index; let i = $index) {
        <article class="cfg__card">
          <div class="cfg__grid">
            <label class="cfg__lbl">{{ 'admin.webhook.name' | t }}
              <input [(ngModel)]="hook.name" (ngModelChange)="touch()" /></label>
            <label class="cfg__lbl cfg__lbl--wide">{{ 'admin.webhook.url' | t }}
              <input [(ngModel)]="hook.url" (ngModelChange)="touch()" placeholder="https://" /></label>
            <label class="cfg__chk">
              <input type="checkbox" [(ngModel)]="hook.active" (ngModelChange)="touch()" />
              {{ 'admin.webhook.active' | t }}
            </label>
          </div>

          <fieldset class="cfg__events">
            <legend>{{ 'admin.webhook.events' | t }}</legend>
            @for (ev of allEvents; track ev) {
              <label class="cfg__chk">
                <input
                  type="checkbox"
                  [checked]="hook.events.includes(ev)"
                  (change)="toggleEvent(i, ev)"
                />
                {{ ev }}
              </label>
            }
          </fieldset>

          @if (errors()[i].length > 0) {
            <ul class="cfg__errors" role="alert">
              @for (e of errors()[i]; track e) {
                <li>{{ tr(e) }}</li>
              }
            </ul>
          }

          <div class="cfg__row-foot">
            <app-button variant="ghost" size="sm" (click)="remove(i)">{{ 'admin.common.remove' | t }}</app-button>
            <app-button size="sm" [disabled]="errors()[i].length > 0" (click)="save(i)">{{ 'action.save' | t }}</app-button>
          </div>
        </article>
      }
    </section>
  `,
  styleUrl: './config.shared.scss',
})
export class WebhooksComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  protected readonly allEvents = EVENT_NAMES;
  protected readonly hooks = signal<WebhookConfig[]>([]);

  /** i18n-Key (Validierungsmeldung) übersetzen — Keys sind statisch gepflegt. */
  protected tr(key: string): string {
    return this.i18n.translate(key as TranslationKey);
  }

  protected readonly errors = computed(() =>
    this.hooks().map((h) => {
      const errs: string[] = [];
      if (!/^https?:\/\/.+/i.test(h.url)) errs.push('admin.webhook.badUrl');
      if (h.events.length === 0) errs.push('admin.webhook.noEvents');
      return errs;
    }),
  );

  constructor() {
    this.api.listWebhooks().subscribe((h) => this.hooks.set(h));
  }

  protected add(): void {
    this.hooks.update((list) => [
      ...list,
      { id: '', name: '', url: '', events: [], active: true },
    ]);
  }

  protected remove(i: number): void {
    this.hooks.update((list) => list.filter((_, idx) => idx !== i));
  }

  protected toggleEvent(i: number, ev: EventName): void {
    this.hooks.update((list) =>
      list.map((h, idx) => {
        if (idx !== i) return h;
        const events = h.events.includes(ev)
          ? h.events.filter((e) => e !== ev)
          : [...h.events, ev];
        return { ...h, events };
      }),
    );
  }

  protected touch(): void {
    this.hooks.update((list) => [...list]);
  }

  protected save(i: number): void {
    if (this.errors()[i].length > 0) return;
    this.api.saveWebhook(this.hooks()[i]).subscribe({
      next: (saved) => {
        this.hooks.update((list) => list.map((h, idx) => (idx === i ? saved : h)));
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }
}
