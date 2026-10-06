import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { NoteComponent } from '@shared/ui/note/note.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { type StatusView, webhookDeliveryStatus } from '@shared/status-kind.util';
import {
  ButtonComponent,
  CheckboxComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import {
  EVENT_NAMES,
  type EventName,
  type WebhookConfig,
  type WebhookDeliveryState,
  type WebhookDeliveryStatus,
} from '../admin.models';

function emptyHook(): WebhookConfig {
  return { id: '', name: '', url: '', events: [], active: true };
}

/**
 * Webhook config UI at `/admin/webhooks` (board Admin-Webhooks). One card per webhook:
 * the name with the state of its newest delivery as status text (Zugestellt,
 * Fehlgeschlagen, Läuft, Noch nie), the whole target URL, the real event keys as tags,
 * the "Aktiv" switch (it saves at once), "Zustellstatus" (the diagnosis below the card:
 * state, HTTP code, attempts, last attempt, failure class and the dead-letter note),
 * edit and delete.
 *
 * Create and edit run in a dialog. The client validation asks for a valid http or https
 * URL. The event selection stays optional. Delete runs through a confirm dialog. Every
 * change needs P(`webhook.manage`), which the backend enforces.
 */
@Component({
  selector: 'app-webhooks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    CheckboxComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    PageHeaderComponent,
    SkeletonComponent,
    StatusTextComponent,
    SwitchComponent,
  ],
  templateUrl: './webhooks.component.html',
  styleUrl: './webhooks.component.scss',
})
export class WebhooksComponent {
  private readonly api = inject(AdminApiService);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);

  /**
   * True until the first answer. Without it the table shows its empty text while the
   * request is still out, which asserts there is nothing when nothing has arrived yet.
   */
  protected readonly loading = signal(true);

  protected readonly allEvents = EVENT_NAMES;
  protected readonly hooks = signal<WebhookConfig[]>([]);
  protected readonly draft = signal<WebhookConfig | null>(null);
  protected readonly editingIndex = signal<number | null>(null);
  /** The webhook whose delete the user confirms now. */
  protected readonly confirmDelete = signal<WebhookConfig | null>(null);
  /** The webhook whose delivery diagnosis is open. */
  protected readonly statusDetail = signal<WebhookConfig | null>(null);
  /**
   * The webhooks whose active flag is being saved. Each webhook saves on its own, so a
   * switch stays usable while the save of another webhook runs.
   */
  protected readonly toggling = signal<ReadonlySet<string>>(new Set());
  /** Delivery state per webhook id, from `GET /admin/webhooks/delivery-status`. */
  protected readonly delivery = signal<ReadonlyMap<string, WebhookDeliveryStatus>>(new Map());

  /** `webhook.manage` as a front-end gate. The backend stays authoritative. The value
   *  is reactive, because the principal loads asynchronously. */
  protected readonly canManage = computed(() => this.auth.can('webhook.manage'));
  /** The delivery status loads one time, as soon as the permission is known. */
  private statusRequested = false;

  protected readonly errors = computed(() => {
    const d = this.draft();
    if (!d) return [] as string[];
    const errs: string[] = [];
    if (!/^https?:\/\/.+/i.test(d.url)) errs.push('admin.webhook.badUrl');
    // Triggers are optional. They usually come from the flow graph.
    return errs;
  });

  constructor() {
    this.api.listWebhooks().subscribe({
      next: (h) => {
        this.hooks.set(h);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
    // The diagnosis route needs webhook.manage. Ask for it only once the principal
    // shows the permission, so a user without it never triggers a 403.
    effect(() => {
      if (!this.canManage() || this.statusRequested) return;
      this.statusRequested = true;
      this.loadDeliveryStatus();
    });
  }

  private loadDeliveryStatus(): void {
    this.api.listWebhookDeliveryStatus().subscribe({
      next: (list) => this.delivery.set(new Map(list.map((s) => [s.webhookId, s]))),
      // A failure here must not hide the list itself. The rows then show no state.
      error: () => this.delivery.set(new Map()),
    });
  }

  protected tr(key: string): string {
    return this.i18n.translate(key as TranslationKey);
  }

  /** Delivery state of one webhook, or `null` while none is loaded. */
  protected statusOf(id: string): WebhookDeliveryStatus | null {
    return this.delivery().get(id) ?? null;
  }

  /** The delivery state as status text: sent accent, dead error, the rest neutral. */
  protected deliveryStatus(state: WebhookDeliveryState): StatusView {
    return webhookDeliveryStatus(state);
  }

  /** Localized failure class. An unknown class from a newer backend reads raw. */
  protected reasonLabel(reason: string): string {
    const key = `admin.webhook.delivery.reason.${reason}`;
    const label = this.tr(key);
    return label === key ? reason : label;
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
        // A new webhook has no delivery yet. The backend reports it as "never", so show
        // that state at once instead of waiting for a reload.
        if (idx === null && !this.delivery().has(saved.id)) {
          this.delivery.update((m) =>
            new Map(m).set(saved.id, {
              webhookId: saved.id,
              lastState: 'never',
              reasonClass: 'no_deliveries',
              responseCode: null,
              attempts: 0,
              lastAt: null,
            }),
          );
        }
        this.toast.success(this.i18n.translate('admin.common.saved'));
        this.close();
      },
      error: () => this.toast.error(this.i18n.translate('admin.common.saveFailed')),
    });
  }

  /** Open the diagnosis of a webhook below its card, or close it again. */
  protected toggleStatus(hook: WebhookConfig): void {
    this.statusDetail.update((cur) => (cur?.id === hook.id ? null : hook));
  }

  /** True while the active flag of this webhook is being saved. */
  protected isToggling(id: string): boolean {
    return this.toggling().has(id);
  }

  private setToggling(id: string, on: boolean): void {
    this.toggling.update((cur) => {
      const next = new Set(cur);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  /**
   * The "Aktiv" switch saves the webhook at once; a failure puts the switch back. The
   * switch of a webhook is disabled while its own save runs. Other webhooks save in
   * parallel.
   */
  protected setActive(hook: WebhookConfig, active: boolean): void {
    if (this.isToggling(hook.id)) return;
    const before = hook.active;
    this.setToggling(hook.id, true);
    this.hooks.update((list) => list.map((h) => (h.id === hook.id ? { ...h, active } : h)));
    this.api.saveWebhook({ ...hook, events: [...hook.events], active }).subscribe({
      next: (saved) => {
        this.setToggling(hook.id, false);
        this.hooks.update((list) => list.map((h) => (h.id === saved.id ? saved : h)));
      },
      error: () => {
        this.setToggling(hook.id, false);
        this.hooks.update((list) => list.map((h) => (h.id === hook.id ? { ...h, active: before } : h)));
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }

  protected askDelete(hook: WebhookConfig): void {
    this.confirmDelete.set(hook);
  }

  protected doDelete(): void {
    const hook = this.confirmDelete();
    if (!hook) return;
    this.api.deleteWebhook(hook.id).subscribe({
      next: () => {
        this.hooks.update((list) => list.filter((h) => h.id !== hook.id));
        this.delivery.update((m) => {
          const next = new Map(m);
          next.delete(hook.id);
          return next;
        });
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.webhook.deleted'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.webhook.deleteFailed')),
    });
  }
}
