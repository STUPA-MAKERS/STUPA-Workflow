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
import { ExpandRowComponent } from '@shared/ui/expand-row/expand-row.component';
import {
  FabComponent,
  ButtonComponent,
  ConfirmDialogComponent,
  DialogComponent,
  EmptyStateComponent,
  InputComponent,
  RowMenuComponent,
  type RowMenuSection,
  SkeletonComponent,
  StatusTextComponent,
  SwitchComponent,
  ToastService,
  PageHeaderComponent,
  SectionComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { type StatusView, webhookDeliveryStatus } from '@shared/status-kind.util';
import { withEntry } from '@shared/util/immutable';
import { AdminApiService } from '../admin-api.service';
import {
  type WebhookConfig,
  type WebhookDeliveryState,
  type WebhookDeliveryStatus,
} from '../admin.models';
import { LoadStateComponent, loadStateOf } from '@shared/ui/load-state/load-state.component';

function emptyHook(): WebhookConfig {
  return { id: '', name: '', url: '', active: true };
}

/** The client check of a target URL: http or https with something after the scheme. */
const HTTP_URL = /^https?:\/\/.+/i;

/** The delivery state of a webhook that has never sent anything. */
function neverDelivered(webhookId: string): WebhookDeliveryStatus {
  return {
    webhookId,
    lastState: 'never',
    reasonClass: 'no_deliveries',
    responseCode: null,
    attempts: 0,
    lastAt: null,
  };
}

/** Returns `list` with `saved` appended (`idx` null) or in place of the entry at `idx`. */
function withSaved(
  list: readonly WebhookConfig[],
  idx: number | null,
  saved: WebhookConfig,
): readonly WebhookConfig[] {
  return idx === null ? [...list, saved] : list.map((h, i) => (i === idx ? saved : h));
}

/** Returns `list` with the active flag of webhook `id` set to `active`. */
function withActive(
  list: readonly WebhookConfig[],
  id: string,
  active: boolean,
): readonly WebhookConfig[] {
  return list.map((h) => (h.id === id ? { ...h, active } : h));
}

/** Returns a new set that holds `id` when `on` is true and lacks it otherwise. */
function withMember(set: ReadonlySet<string>, id: string, on: boolean): ReadonlySet<string> {
  const rest = [...set].filter((x) => x !== id);
  return new Set(on ? [...rest, id] : rest);
}

/**
 * Webhook config UI at `/admin/webhooks`. One expand row per webhook: the name with the
 * state of its newest delivery as status text (Zugestellt, Fehlgeschlagen, Läuft, Noch nie),
 * the whole target URL as the sub line, the "Aktiv" switch (it saves at once) and the ⋮
 * menu with delete. A press on the row opens the edit. The chevron opens the body:
 * "Zustellstatus" (state, HTTP code, attempts, last attempt, failure
 * class and the dead-letter note). An inactive webhook carries "Inaktiv" beside its name.
 * Without P(`webhook.manage`) a press on the row opens the body, because there is no edit.
 *
 * Create and edit run in a dialog. The client validation asks for a valid http or https
 * URL. A webhook has no event list: it sends only through the `webhook` action of a flow
 * transition (§F/integrations/webhooks/000402). Delete runs through a confirm dialog. Every
 * change needs P(`webhook.manage`), which the backend enforces.
 */
@Component({
  selector: 'app-webhooks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    LoadStateComponent,
    SectionComponent,
    ExpandRowComponent,
    FabComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    DialogComponent,
    InputComponent,
    PageHeaderComponent,
    BreadcrumbsComponent,
    RowMenuComponent,
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
  /** The read of the webhooks failed (§ 000576). */
  protected readonly loadError = signal(false);
  protected readonly loadState = loadStateOf(this.loading, this.loadError);

  protected readonly hooks = signal<readonly WebhookConfig[]>([]);
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
  /** The ⋮ menu of a webhook: delete is its only action. */
  protected readonly rowMenu = computed<readonly RowMenuSection[]>(() => [
    { items: [{ id: 'delete', label: this.i18n.translate('admin.common.remove'), icon: 'trash', danger: true }] },
  ]);
  /** The delivery status loads one time, as soon as the permission is known. */
  private statusRequested = false;

  protected readonly errors = computed<readonly string[]>(() => {
    const d = this.draft();
    return d && !HTTP_URL.test(d.url) ? ['admin.webhook.badUrl'] : [];
  });

  /**
   * The diagnosis route needs webhook.manage, so it is requested only once the principal shows the
   * permission and a user without it never triggers a 403.
   */
  constructor() {
    this.load();
    effect(() => {
      if (!this.canManage() || this.statusRequested) return;
      this.statusRequested = true;
      this.loadDeliveryStatus();
    });
  }

  /** Read the webhooks; also the retry of the load error. */
  protected load(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.listWebhooks().subscribe({
      next: (h) => {
        this.hooks.set(h);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** A failure of the delivery status must not hide the list itself. */
  private loadDeliveryStatus(): void {
    this.api.listWebhookDeliveryStatus().subscribe({
      next: (list) => this.delivery.set(new Map(list.map((s) => [s.webhookId, s]))),
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
    this.draft.set({ ...this.hooks()[i] });
  }

  protected close(): void {
    this.draft.set(null);
    this.editingIndex.set(null);
  }

  protected patch<K extends keyof WebhookConfig>(key: K, value: WebhookConfig[K]): void {
    this.draft.update((d) => (d ? { ...d, [key]: value } : d));
  }

  protected save(): void {
    const d = this.draft();
    if (!d || this.errors().length > 0) return;
    const idx = this.editingIndex();
    this.api.saveWebhook(d).subscribe({
      next: (saved) => {
        this.hooks.update((list) => withSaved(list, idx, saved));
        if (idx === null && !this.delivery().has(saved.id)) {
          this.delivery.update((m) => withEntry(m, saved.id, neverDelivered(saved.id)));
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
    this.toggling.update((cur) => withMember(cur, id, on));
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
    this.hooks.update((list) => withActive(list, hook.id, active));
    this.api.saveWebhook({ ...hook, active }).subscribe({
      next: (saved) => {
        this.setToggling(hook.id, false);
        this.hooks.update((list) => list.map((h) => (h.id === saved.id ? saved : h)));
      },
      error: () => {
        this.setToggling(hook.id, false);
        this.hooks.update((list) => withActive(list, hook.id, before));
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
        this.delivery.update((m) => new Map([...m].filter(([id]) => id !== hook.id)));
        this.confirmDelete.set(null);
        this.toast.success(this.i18n.translate('admin.webhook.deleted'));
      },
      error: () => this.toast.error(this.i18n.translate('admin.webhook.deleteFailed')),
    });
  }
}
