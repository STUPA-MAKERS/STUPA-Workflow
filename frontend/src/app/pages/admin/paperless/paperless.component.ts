import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { formatMoment } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { InputComponent, ToastService } from '@stupa-makers/ui-kit';
import {
  ScreenGroupDirective,
  SettingsScreenComponent,
  type SettingsGroup,
  type SettingsNotice,
  type SettingsState,
} from '@stupa-makers/ui-kit/screens';
import { type Observable, tap } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type {
  PaperlessConnection,
  PaperlessConnectionIn,
  PaperlessFailedFiling,
  PaperlessFilingKind,
} from '../admin.models';

/**
 * What the form edits: the address, the address for links, a new token and the switch of
 * each filing part.
 */
export interface PaperlessDraft {
  readonly baseUrl: string;
  /** Empty: the links use the address (§F/integrations/paperless/002844). */
  readonly publicUrl: string;
  /** Empty: the stored token stays. */
  readonly token: string;
  readonly fileProtocols: boolean;
  readonly fileApplications: boolean;
  readonly filePlans: boolean;
  readonly insertEnabled: boolean;
  readonly linkEnabled: boolean;
}

/** The switch of each part of the integration, with its label and its group. */
const SWITCHES = [
  { key: 'fileProtocols', label: 'admin.paperless.fileProtocols', group: 'filing' },
  { key: 'fileApplications', label: 'admin.paperless.fileApplications', group: 'filing' },
  { key: 'filePlans', label: 'admin.paperless.filePlans', group: 'filing' },
  { key: 'insertEnabled', label: 'admin.paperless.insertEnabled', group: 'insert' },
  { key: 'linkEnabled', label: 'admin.paperless.linkEnabled', group: 'link' },
] as const satisfies readonly {
  readonly key: keyof PaperlessDraft;
  readonly label: TranslationKey;
  readonly group: 'filing' | 'insert' | 'link';
}[];

type SwitchKey = (typeof SWITCHES)[number]['key'];

/** The sentence of each cause code of a failed call or a failed filing. */
const ERROR_TEXT: Readonly<Record<string, TranslationKey>> = {
  not_configured: 'admin.paperless.error.notConfigured',
  blocked: 'admin.paperless.error.blocked',
  timeout: 'admin.paperless.error.timeout',
  unreachable: 'admin.paperless.error.unreachable',
  redirect: 'admin.paperless.error.redirect',
  unauthorized: 'admin.paperless.error.unauthorized',
  status: 'admin.paperless.error.status',
  format: 'admin.paperless.error.format',
  rejected: 'admin.paperless.error.rejected',
  consume_timeout: 'admin.paperless.error.consumeTimeout',
  source_missing: 'admin.paperless.error.sourceMissing',
  render: 'admin.paperless.error.render',
  storage: 'admin.paperless.error.storage',
};

/** The name of each kind of filed file. */
const KIND_TEXT: Readonly<Record<PaperlessFilingKind, TranslationKey>> = {
  protocol: 'admin.paperless.kind.protocol',
  protocol_public: 'admin.paperless.kind.protocolPublic',
  application: 'admin.paperless.kind.application',
  attachment: 'admin.paperless.kind.attachment',
  plan: 'admin.paperless.kind.plan',
  ticket_file: 'admin.paperless.kind.ticketFile',
};

/** The prefix of the action key of "Erneut versuchen"; the id of the filing follows. */
const RETRY = 'retry:';

/** An absolute http(s) URL, as the address for links needs (§F/integrations/paperless/002844). */
export function isWebUrl(text: string): boolean {
  try {
    const url = new URL(text.trim());
    return (url.protocol === 'http:' || url.protocol === 'https:') && !!url.hostname;
  } catch {
    return false;
  }
}

/** An absolute http(s) URL without a user part. */
export function isPaperlessUrl(text: string): boolean {
  try {
    const url = new URL(text.trim());
    return (
      (url.protocol === 'http:' || url.protocol === 'https:') && !!url.hostname && !url.username
    );
  } catch {
    return false;
  }
}

/**
 * "Paperless" (permission `admin.paperless`): the connection to one Paperless-ngx instance
 * and the switch of each part that files documents (§F/integrations/paperless/002511, 002512).
 *
 * `GET/PUT /admin/paperless` reads and saves the address, the token and the switches. The
 * server never returns the token: an empty token field keeps the stored one. The server
 * refuses an address whose host is not in the deploy setting `PAPERLESS_HOST_ALLOWLIST`
 * (422 `paperless_host_not_allowed`); the address field then shows the error. A new
 * address needs the token again while a token is stored (§F/integrations/paperless/002813).
 * The address for links is what each browser link to Paperless names; the server never calls
 * it, so it needs neither an allowed host nor the token (§F/integrations/paperless/002844).
 *
 * "Verbindung testen" calls Paperless with the stored connection and shows the result as a
 * toast. "Bestehende Dokumente ablegen" starts a job for each final document without one,
 * after a question (§F/integrations/paperless/002530). "Fehlgeschlagene Ablagen" lists each
 * filing whose job failed for the last time; a press on its row asks and then starts the job
 * again (§F/integrations/paperless/002526). The group shows only while a filing is failed.
 *
 * The page has no style of its own (§ui-kit:S/framework/architecture/002213): the settings
 * screen of the kit draws every row.
 */
@Component({
  selector: 'app-admin-paperless',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    SettingsScreenComponent,
    ScreenGroupDirective,
    InputComponent,
  ],
  templateUrl: './paperless.component.html',
})
export class PaperlessComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The server refused the host of this address at the last save. */
  private readonly refusedUrl = signal<string | null>(null);

  protected readonly form: SettingsForm<PaperlessConnection, PaperlessDraft> = settingsForm<
    PaperlessConnection,
    PaperlessDraft,
    PaperlessConnectionIn
  >({
    allowed: () => this.auth.can('admin.paperless'),
    load: () => this.api.getPaperless(),
    put: (body) => this.put(body),
    draftOf: (s) => ({
      baseUrl: s.baseUrl ?? '',
      publicUrl: s.publicUrl ?? '',
      token: '',
      fileProtocols: s.fileProtocols,
      fileApplications: s.fileApplications,
      filePlans: s.filePlans,
      insertEnabled: s.insertEnabled,
      linkEnabled: s.linkEnabled,
    }),
    initial: {
      baseUrl: '',
      publicUrl: '',
      token: '',
      fileProtocols: false,
      fileApplications: false,
      filePlans: false,
      insertEnabled: false,
      linkEnabled: false,
    },
    body: () => {
      const d = this.draft();
      if (this.urlError() || this.publicUrlError() || this.tokenError()) return null;
      return {
        baseUrl: d.baseUrl.trim() || null,
        publicUrl: d.publicUrl.trim() || null,
        ...(d.token ? { token: d.token } : {}),
        fileProtocols: d.fileProtocols,
        fileApplications: d.fileApplications,
        filePlans: d.filePlans,
        insertEnabled: d.insertEnabled,
        linkEnabled: d.linkEnabled,
      };
    },
    dirty: (s) => {
      const d = this.draft();
      return (
        d.baseUrl.trim() !== (s.baseUrl ?? '') ||
        d.publicUrl.trim() !== (s.publicUrl ?? '') ||
        d.token !== '' ||
        SWITCHES.some(({ key }) => d[key] !== s[key])
      );
    },
  });
  protected readonly draft = this.form.draft;
  protected readonly saving = this.form.saving;
  protected readonly dirty = this.form.dirty;

  /** The stored connection has an address and a token, so the actions can call Paperless. */
  protected readonly connected = computed(() => {
    const s = this.form.saved();
    return !!s?.baseUrl && s.tokenSet;
  });

  protected readonly tokenLabel = computed(() =>
    this.i18n.translate(
      this.form.saved()?.tokenSet ? 'admin.paperless.tokenNew' : 'admin.paperless.token',
    ),
  );

  protected readonly urlError = computed(() => {
    const url = this.draft().baseUrl.trim();
    if (url && !isPaperlessUrl(url)) return this.i18n.translate('admin.paperless.urlInvalid');
    if (url && url === this.refusedUrl()) {
      return this.i18n.translate('admin.paperless.hostNotAllowed', {
        hosts: (this.form.saved()?.allowedHosts ?? []).join(', ') || '–',
      });
    }
    return '';
  });

  /**
   * The address for links is only for the browser, so it needs only the form of a web
   * address: no allowlist, no token (§F/integrations/paperless/002844).
   */
  protected readonly publicUrlError = computed(() => {
    const url = this.draft().publicUrl.trim();
    return url && !isWebUrl(url) ? this.i18n.translate('admin.paperless.urlInvalid') : '';
  });

  /**
   * A new address with a stored token needs the token again, because the stored token
   * must not follow a new address (§F/integrations/paperless/002813).
   */
  protected readonly tokenError = computed(() => {
    const saved = this.form.saved();
    const d = this.draft();
    const url = d.baseUrl.trim();
    const moved = !!url && url.replace(/\/+$/, '') !== (saved?.baseUrl ?? '');
    return saved?.tokenSet && moved && !d.token
      ? this.i18n.translate('admin.paperless.tokenAgain')
      : '';
  });

  protected readonly testing = signal(false);
  protected readonly backfilling = signal(false);

  protected readonly screenState = computed<SettingsState>(() => {
    switch (this.form.state()) {
      case 'loading':
        return { state: 'loading' };
      case 'forbidden':
        return { state: 'forbidden', message: this.i18n.translate('admin.paperless.forbidden') };
      case 'error':
        return {
          state: 'error',
          message: this.i18n.translate('admin.paperless.loadError'),
          retry: () => this.form.reload(),
        };
      default:
        return { state: 'ready' };
    }
  });

  protected readonly groups = computed<SettingsGroup[]>(() => {
    const d = this.draft();
    const idle = !this.connected() || this.dirty();
    const failed = this.failed();
    return [
      { key: 'connection', label: this.i18n.translate('admin.paperless.connection'), rows: [] },
      { key: 'token', rows: [] },
      {
        key: 'filing',
        label: this.i18n.translate('admin.paperless.filing'),
        rows: this.switchRows('filing', d),
      },
      {
        key: 'insert',
        label: this.i18n.translate('admin.paperless.insert'),
        rows: this.switchRows('insert', d),
      },
      {
        key: 'link',
        label: this.i18n.translate('admin.paperless.link'),
        rows: this.switchRows('link', d),
      },
      {
        key: 'actions',
        rows: [
          {
            key: 'test',
            label: this.i18n.translate('admin.paperless.test'),
            control: 'action' as const,
            disabled: idle || this.testing(),
            action: { key: 'test', label: this.i18n.translate('admin.paperless.test') },
          },
          {
            key: 'backfill',
            label: this.i18n.translate('admin.paperless.backfill'),
            control: 'action' as const,
            disabled: idle || this.backfilling(),
            action: {
              key: 'backfill',
              label: this.i18n.translate('admin.paperless.backfill'),
              confirm: {
                title: this.i18n.translate('admin.paperless.backfillTitle'),
                text: this.i18n.translate('admin.paperless.backfillText'),
                confirmLabel: this.i18n.translate('admin.paperless.backfillConfirm'),
              },
            },
          },
        ],
      },
      ...(failed.length
        ? [
            {
              key: 'failed',
              label: this.i18n.translate('admin.paperless.failed'),
              rows: failed.map((f) => ({
                key: f.id,
                label: f.title,
                meta: this.metaText(f),
                control: 'action' as const,
                disabled: this.retrying() !== null,
                action: {
                  key: `${RETRY}${f.id}`,
                  label: this.i18n.translate('admin.paperless.retry'),
                  icon: 'reload' as const,
                  confirm: {
                    title: this.i18n.translate('admin.paperless.retryTitle'),
                    text: f.title,
                    confirmLabel: this.i18n.translate('admin.paperless.retry'),
                  },
                },
              })),
            },
          ]
        : []),
    ];
  });

  /** The failed filings; empty until the read answers. */
  protected readonly failed = signal<readonly PaperlessFailedFiling[]>([]);
  private readonly failedError = signal(false);
  /** The read of the failed filings failed: a note under the head says so. */
  protected readonly notice = computed<SettingsNotice | null>(() =>
    this.failedError()
      ? { kind: 'error', text: this.i18n.translate('admin.paperless.failedLoadError') }
      : null,
  );
  /** The filing whose retry is in flight. */
  protected readonly retrying = signal<string | null>(null);

  constructor() {
    if (this.auth.can('admin.paperless')) this.loadFailed();
  }

  /** Save, and keep the address that the server refused, so its field shows the cause. */
  private put(body: PaperlessConnectionIn): Observable<PaperlessConnection> {
    return this.api.putPaperless(body).pipe(
      tap({
        next: () => this.refusedUrl.set(null),
        error: (err: { error?: { code?: string } } | null) => {
          if (err?.error?.code === 'paperless_host_not_allowed') this.refusedUrl.set(body.baseUrl);
        },
      }),
    );
  }

  private loadFailed(): void {
    this.api.listPaperlessFailed().subscribe({
      next: (list) => this.failed.set(list),
      error: () => this.failedError.set(true),
    });
  }

  /** The line under the title of a failed filing: its kind, the time and the cause. */
  private metaText(f: PaperlessFailedFiling): string {
    return [
      this.i18n.translate(KIND_TEXT[f.kind]),
      formatMoment(f.failedAt, this.i18n.formatLocale()),
      this.errorText(f.error),
    ]
      .filter(Boolean)
      .join(' · ');
  }

  /** The switch rows of one group (§F/integrations/paperless/002512). */
  private switchRows(group: 'filing' | 'insert' | 'link', d: PaperlessDraft) {
    return SWITCHES.filter((s) => s.group === group).map(({ key, label }) => ({
      key,
      label: this.i18n.translate(label),
      control: 'switch' as const,
      value: d[key],
    }));
  }

  protected errorText(code: string | null): string {
    return this.i18n.translate(ERROR_TEXT[code ?? ''] ?? 'admin.paperless.error.unknown');
  }

  protected patch(change: Partial<PaperlessDraft>): void {
    this.form.patch(change);
  }

  protected set(key: string, value: boolean): void {
    const found = SWITCHES.find((s) => s.key === key);
    if (found) this.patch({ [found.key]: value } as Partial<Record<SwitchKey, boolean>>);
  }

  protected act(key: string): void {
    if (key === 'test') this.test();
    if (key === 'backfill') this.backfill();
    const filing = key.startsWith(RETRY)
      ? this.failed().find((f) => f.id === key.slice(RETRY.length))
      : null;
    if (filing) this.retry(filing);
  }

  private test(): void {
    if (this.testing()) return;
    this.testing.set(true);
    this.api.testPaperless().subscribe({
      next: (result) => {
        this.testing.set(false);
        if (result.ok) this.toast.show(this.i18n.translate('admin.paperless.testOk'), 'success');
        else this.toast.show(this.errorText(result.error), 'error');
      },
      error: () => {
        this.testing.set(false);
        this.toast.show(this.i18n.translate('admin.paperless.error.unknown'), 'error');
      },
    });
  }

  private backfill(): void {
    if (this.backfilling()) return;
    this.backfilling.set(true);
    this.api.backfillPaperless().subscribe({
      next: ({ started }) => {
        this.backfilling.set(false);
        this.toast.show(
          started === 1
            ? this.i18n.translate('admin.paperless.backfillStarted.one')
            : this.i18n.translate('admin.paperless.backfillStarted.other', { count: started }),
          'success',
        );
      },
      error: () => {
        this.backfilling.set(false);
        this.toast.show(this.i18n.translate('admin.paperless.backfillFailed'), 'error');
      },
    });
  }

  /** A 404 says the filing is no longer failed, so its row leaves as on a success. */
  protected retry(filing: PaperlessFailedFiling): void {
    if (this.retrying()) return;
    this.retrying.set(filing.id);
    const drop = (): void => {
      this.retrying.set(null);
      this.failed.update((list) => list.filter((f) => f.id !== filing.id));
      this.toast.show(this.i18n.translate('admin.paperless.retried'), 'success');
    };
    this.api.retryPaperlessFiling(filing.id).subscribe({
      next: drop,
      error: (err: { status?: number }) => {
        if (err.status === 404) return drop();
        this.retrying.set(null);
        this.toast.show(this.i18n.translate('admin.paperless.retryFailed'), 'error');
      },
    });
  }

  protected discard(): void {
    this.refusedUrl.set(null);
    this.form.reset();
  }

  protected save(): void {
    this.form.save();
  }
}
