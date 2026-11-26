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
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  DialogComponent,
  EmptyStateComponent,
  InputComponent,
  type Action,
  type ListRow,
  type LoadState,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  type FilterSelectOption,
  FilterSelectComponent,
  filterChipText,
  CheckboxComponent,
  StatusTextComponent,
  SwitchComponent,
  ToastService,
  SectionComponent,
  ErrorTextComponent,
  FactsComponent,
  DialogBodyDirective,
  FieldGroupComponent,
  SearchPillComponent,
} from '@stupa-makers/ui-kit';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { RecordsScreenComponent, ScreenRecordDirective, ScreenSearchDirective } from '@stupa-makers/ui-kit/screens';
import { type StatusView, webhookDeliveryStatus } from '@shared/status-kind.util';
import { withEntry } from '@shared/util/immutable';
import { AdminApiService } from '../admin-api.service';
import { stateDisplayLabel } from '../flow/flow-label.util';
import {
  type WebhookCatalogEvent,
  type WebhookConfig,
  type WebhookDeliveryState,
  type WebhookDeliveryStatus,
  type WebhookEventGroup,
  type WebhookSubscription,
} from '../admin.models';
import { hitCount, listSearch, searchedRows } from '../list-search';

function emptyHook(): WebhookConfig {
  return {
    id: '',
    name: '',
    url: '',
    active: true,
    subscriptions: [],
    gremiumIds: [],
    typeIds: [],
    stateKeys: [],
  };
}

/** The order of the event groups in the dialog. */
const GROUPS: readonly WebhookEventGroup[] = [
  'applications',
  'votes',
  'meetings',
  'protocols',
  'budget',
  'events',
  'tickets',
];

/** The event whose subscription takes the target status filter. */
const TRANSITION = 'application.transition';

/** The example ID of the payload preview. */
const EXAMPLE_ID = '3f6c1d2e-8a4b-4c5d-9e6f-7a8b9c0d1e2f';

/** The fields of a new subscription: every field that is not personal (§F/integrations/webhooks/002413). */
function defaultFields(event: WebhookCatalogEvent): readonly string[] {
  return event.fields.filter((f) => !f.personal).map((f) => f.key);
}

/** Returns `subs` with the subscription of `event` set to `fields`, or removed for `null`. */
export function withSubscription(
  subs: readonly WebhookSubscription[],
  event: string,
  fields: readonly string[] | null,
): readonly WebhookSubscription[] {
  const rest = subs.filter((s) => s.event !== event);
  return fields === null ? rest : [...rest, { event, fields }];
}

/**
 * The example body of one event with the chosen fields, as the receiver gets it
 * (§F/integrations/webhooks/002415, P/integrations/webhooks/000963).
 */
export function previewBody(event: WebhookCatalogEvent, fields: readonly string[]): string {
  const chosen = new Set(fields);
  const body = {
    event: event.name,
    occurredAt: '2026-11-23T09:00:00+00:00',
    ...Object.fromEntries(event.idKeys.map((key) => [key, EXAMPLE_ID])),
    data: Object.fromEntries(
      event.fields.filter((f) => chosen.has(f.key)).map((f) => [f.key, f.example]),
    ),
  };
  return JSON.stringify(body, null, 2);
}

/** Time until the delivery status reads again after a test delivery, in ms. */
const TEST_RELOAD_MS = 15_000;

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
 * URL. The dialog lists the events of the catalog by group (§F/integrations/webhooks/002410,
 * 002411). A checked event shows its fields as checkboxes; a personal field carries the mark
 * "personenbezogen" and a new subscription starts with it off (002412, 002413). The filters
 * Gremien, Antragsarten and (with a subscribed status change) Ziel-Status narrow the events
 * (002414). The preview shows the body of each subscribed event with example values (002415).
 * The ⋮ menu sends a test delivery (002416) and deletes through a confirm dialog. Every
 * change needs P(`webhook.manage`), which the backend enforces.
 */
@Component({
  selector: 'app-webhooks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    SearchPillComponent,
    ScreenSearchDirective,
    DialogBodyDirective,
    FactsComponent,
    ErrorTextComponent,
    SectionComponent,
    ExpandRowComponent,
    ConfirmDialogComponent,
    EmptyStateComponent,
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    DialogComponent,
    InputComponent,
    RowMenuComponent,
    StatusTextComponent,
    SwitchComponent,
    RecordsScreenComponent,
    ScreenRecordDirective,
    FilterSelectComponent,
    CheckboxComponent,
    FieldGroupComponent,
    MarkdownViewComponent,
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
  /** The read of the webhooks failed (§ui-kit:000576). */
  protected readonly loadError = signal(false);

  protected readonly hooks = signal<readonly WebhookConfig[]>([]);
  /** The search of the list (§002690, §002691). */
  protected readonly search = listSearch();
  /** The hits of the search for the pill. */
  protected readonly hits = computed(() => hitCount(this.rows(), this.search));

  /** The rows of the records screen (§ui-kit:002257). */
  protected readonly rows = computed<LoadState<readonly ListRow[]>>(() => {
    if (this.loading()) return { state: 'loading' };
    if (this.loadError())
      return {
        state: 'error',
        message: this.i18n.translate('admin.webhook.error'),
        retry: () => this.load(),
      };
    const rows = this.search
      .filter(this.hooks(), (h) => [h.name, h.url])
      .map((h) => ({ id: h.id, title: h.name || h.url }));
    return searchedRows(
      rows.length
        ? { state: 'ready', data: rows }
        : { state: 'empty', icon: 'webhook', heading: this.i18n.translate('admin.webhook.none') },
      this.search,
      this.i18n.translate('admin.list.noHits'),
    );
  });
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
  /** The ⋮ menu of a webhook: the test delivery, then delete. */
  protected readonly rowMenu = computed<readonly RowMenuSection[]>(() => [
    { items: [{ id: 'test', label: this.i18n.translate('admin.webhook.test'), icon: 'send' }] },
    { items: [{ id: 'delete', label: this.i18n.translate('admin.common.remove'), icon: 'trash', danger: true }] },
  ]);

  /** The event catalog, loaded with the permission. */
  protected readonly catalog = signal<readonly WebhookCatalogEvent[]>([]);
  /** The catalog by group, in the order of `GROUPS`. */
  protected readonly groups = computed(() =>
    GROUPS.map((group) => ({
      group,
      events: this.catalog().filter((e) => e.group === group),
    })).filter((g) => g.events.length > 0),
  );
  /** The choices of the Gremium filter. */
  protected readonly gremiumOptions = signal<readonly FilterSelectOption[]>([]);
  /** The choices of the Antragsart filter. */
  protected readonly typeOptions = signal<readonly FilterSelectOption[]>([]);
  /** The choices of the target status filter: the states of the global flow. */
  protected readonly stateOptions = signal<readonly FilterSelectOption[]>([]);
  /**
   * The text of a filter select in the dialog: its name alone while no value is chosen, else
   * the name and the chosen values ("Gremien: AStA, StuPa"), so the dialog shows what the
   * webhook filters (spec 002581).
   */
  protected filterText(
    label: TranslationKey,
    options: readonly FilterSelectOption[],
    values: readonly string[],
  ): string {
    const names = values.map((v) => options.find((o) => o.value === v)?.label ?? v);
    return filterChipText(this.i18n.translate(label), names.join(', '));
  }
  /** The subscribed events of the draft with their catalog entry, for the preview. */
  protected readonly previews = computed(() => {
    const d = this.draft();
    if (!d) return [];
    return d.subscriptions.flatMap((sub) => {
      const event = this.catalog().find((e) => e.name === sub.event);
      return event
        ? [
            {
              name: event.name,
              body: previewBody(event, sub.fields),
              markdown: `**${this.eventLabel(event.name)}**\n\n\`\`\`json\n${previewBody(event, sub.fields)}\n\`\`\``,
            },
          ]
        : [];
    });
  });
  /** "Webhook hinzufügen" as the FAB, with `webhook.manage`. */
  protected readonly actions = computed<readonly Action[]>(() =>
    this.canManage()
      ? [{ key: 'add', label: this.i18n.translate('fab.webhook'), priority: 'fab' }]
      : [],
  );

  /** The webhook of a row of the records screen. */
  protected hookOf(id: string): WebhookConfig {
    return this.hooks().find((h) => h.id === id)!;
  }

  /** The place of a webhook in the list, for the edit dialog. */
  protected indexOf(id: string): number {
    return this.hooks().findIndex((h) => h.id === id);
  }

  /** The delivery status loads one time, as soon as the permission is known. */
  private statusRequested = false;

  protected readonly errors = computed<readonly string[]>(() => {
    const d = this.draft();
    return d && !HTTP_URL.test(d.url) ? ['admin.webhook.badUrl'] : [];
  });

  /** The save needs a name and a valid URL, because the server refuses a webhook without them (spec 002582). */
  protected readonly canSave = computed(() => {
    const d = this.draft();
    return !!d && d.name.trim().length > 0 && this.errors().length === 0;
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
      this.loadChoices();
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

  /** Read the catalog and the choices of the filters; a failed read leaves a list empty. */
  private loadChoices(): void {
    this.api.getWebhookCatalog().subscribe({
      next: (c) => this.catalog.set(c),
      error: () => this.catalog.set([]),
    });
    this.api.listGremienOptions().subscribe({
      next: (list) => this.gremiumOptions.set(list.map((g) => ({ value: g.id, label: g.name }))),
      error: () => this.gremiumOptions.set([]),
    });
    this.api.listApplicationTypes().subscribe({
      next: (list) => this.typeOptions.set(list.map((t) => ({ value: t.id, label: t.name }))),
      error: () => this.typeOptions.set([]),
    });
    this.api.getGlobalFlow().subscribe({
      next: (flow) =>
        this.stateOptions.set(
          (flow?.states ?? []).map((st) => ({ value: st.key, label: stateDisplayLabel(st) })),
        ),
      error: () => this.stateOptions.set([]),
    });
  }

  /** The subscription of `event` in the draft, or null. */
  protected subscriptionOf(event: string): WebhookSubscription | null {
    return this.draft()?.subscriptions.find((s) => s.event === event) ?? null;
  }

  /** Subscribe to an event with its default fields, or end the subscription. */
  protected setEvent(event: WebhookCatalogEvent, on: boolean): void {
    const d = this.draft();
    if (!d) return;
    this.patch(
      'subscriptions',
      withSubscription(d.subscriptions, event.name, on ? defaultFields(event) : null),
    );
  }

  /** Put one field into the payload of an event, or take it out. */
  protected setField(event: WebhookCatalogEvent, key: string, on: boolean): void {
    const sub = this.subscriptionOf(event.name);
    const d = this.draft();
    if (!d || !sub) return;
    const fields = event.fields
      .map((f) => f.key)
      .filter((k) => (k === key ? on : sub.fields.includes(k)));
    this.patch('subscriptions', withSubscription(d.subscriptions, event.name, fields));
  }

  /** True while the draft subscribes to a status change, which shows the status filter. */
  protected readonly hasTransition = computed(() => this.subscriptionOf(TRANSITION) !== null);

  /** The label of an event, a group or a field. */
  protected eventLabel(name: string): string {
    return this.tr(`admin.webhook.event.${name}`);
  }

  protected groupLabel(group: WebhookEventGroup): string {
    return this.tr(`admin.webhook.group.${group}`);
  }

  protected fieldLabel(key: string): string {
    return this.tr(`admin.webhook.field.${key}`);
  }

  /** The ⋮ menu: the test delivery or the delete. */
  protected onMenu(hook: WebhookConfig, item: RowMenuItem): void {
    if (item.id === 'test') this.sendTest(hook);
    else this.askDelete(hook);
  }

  /** Queue a test delivery; the delivery status reads again after the worker had time. */
  protected sendTest(hook: WebhookConfig): void {
    this.api.sendWebhookTest(hook.id).subscribe({
      next: () => {
        this.toast.show(this.i18n.translate('admin.webhook.testSent'), 'success');
        setTimeout(() => this.loadDeliveryStatus(), TEST_RELOAD_MS);
      },
      error: () => this.toast.show(this.i18n.translate('admin.webhook.testFailed'), 'error'),
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
    if (!d || !this.canSave()) return;
    const idx = this.editingIndex();
    this.api.saveWebhook(d).subscribe({
      next: (saved) => {
        this.hooks.update((list) => withSaved(list, idx, saved));
        if (idx === null && !this.delivery().has(saved.id)) {
          this.delivery.update((m) => withEntry(m, saved.id, neverDelivered(saved.id)));
        }
        this.toast.show(this.i18n.translate('admin.common.saved'), 'success');
        this.close();
      },
      error: () => this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error'),
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
        this.toast.show(this.i18n.translate('admin.common.saveFailed'), 'error');
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
        this.toast.show(this.i18n.translate('admin.webhook.deleted'), 'success');
      },
      error: () => this.toast.show(this.i18n.translate('admin.webhook.deleteFailed'), 'error'),
    });
  }
}
