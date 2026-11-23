import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import {
  ButtonComponent,
  ButtonGroupComponent,
  EmptyStateComponent,
  InputComponent,
  MetaLineComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  ScreenGroupDirective,
  ScreenSkeletonDirective,
  SettingsScreenComponent,
  type SettingsGroup,
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

/** What the form edits: the address, a new token and the switch of each filing part. */
export interface PaperlessDraft {
  readonly baseUrl: string;
  /** Empty: the stored token stays. */
  readonly token: string;
  readonly fileProtocols: boolean;
  readonly fileApplications: boolean;
  readonly filePlans: boolean;
}

/** The switch of each part that files documents, with its label. */
const SWITCHES = [
  { key: 'fileProtocols', label: 'admin.paperless.fileProtocols' },
  { key: 'fileApplications', label: 'admin.paperless.fileApplications' },
  { key: 'filePlans', label: 'admin.paperless.filePlans' },
] as const satisfies readonly { readonly key: keyof PaperlessDraft; readonly label: TranslationKey }[];

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
};

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
 * (422 `paperless_host_not_allowed`); the address field then shows the error.
 *
 * "Verbindung testen" calls Paperless with the stored connection and shows the result as a
 * toast. "Bestehende Dokumente ablegen" starts a job for each final document without one,
 * after a question (§F/integrations/paperless/002530). "Fehlgeschlagene Ablagen" lists each
 * filing whose job failed for the last time, with "Erneut versuchen"
 * (§F/integrations/paperless/002526).
 */
@Component({
  selector: 'app-admin-paperless',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    SettingsScreenComponent,
    ScreenGroupDirective,
    ScreenSkeletonDirective,
    ButtonComponent,
    ButtonGroupComponent,
    EmptyStateComponent,
    InputComponent,
    LoadStateComponent,
    MetaLineComponent,
  ],
  templateUrl: './paperless.component.html',
  styleUrl: './paperless.component.scss',
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
      token: '',
      fileProtocols: s.fileProtocols,
      fileApplications: s.fileApplications,
      filePlans: s.filePlans,
    }),
    initial: {
      baseUrl: '',
      token: '',
      fileProtocols: false,
      fileApplications: false,
      filePlans: false,
    },
    body: () => {
      const d = this.draft();
      const saved = this.form.saved();
      if (this.urlError()) return null;
      return {
        baseUrl: d.baseUrl.trim() || null,
        ...(d.token ? { token: d.token } : {}),
        fileProtocols: d.fileProtocols,
        fileApplications: d.fileApplications,
        filePlans: d.filePlans,
        insertEnabled: saved?.insertEnabled ?? false,
      };
    },
    dirty: (s) => {
      const d = this.draft();
      return (
        d.baseUrl.trim() !== (s.baseUrl ?? '') ||
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
    return [
      { key: 'connection', label: this.i18n.translate('admin.paperless.connection'), rows: [] },
      {
        key: 'filing',
        label: this.i18n.translate('admin.paperless.filing'),
        rows: SWITCHES.map(({ key, label }) => ({
          key,
          label: this.i18n.translate(label),
          control: 'switch' as const,
          value: d[key],
        })),
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
      ...(this.form.state() === 'ok'
        ? [
            {
              key: 'failed',
              label: this.i18n.translate('admin.paperless.failed'),
              rows: [],
              always: true,
            },
          ]
        : []),
    ];
  });

  /** null while loading; the read failed: `failedError`. */
  protected readonly failed = signal<PaperlessFailedFiling[] | null>(null);
  protected readonly failedError = signal(false);
  protected readonly failedState = computed<LoadState>(() =>
    this.failedError() ? 'error' : this.failed() === null ? 'loading' : 'ok',
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

  protected loadFailed(): void {
    this.failed.set(null);
    this.failedError.set(false);
    this.api.listPaperlessFailed().subscribe({
      next: (list) => this.failed.set(list),
      error: () => {
        this.failed.set([]);
        this.failedError.set(true);
      },
    });
  }

  protected errorText(code: string | null): string {
    return this.i18n.translate(ERROR_TEXT[code ?? ''] ?? 'admin.paperless.error.unknown');
  }

  protected kindText(kind: PaperlessFilingKind): string {
    return this.i18n.translate(KIND_TEXT[kind]);
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
      this.failed.update((list) => (list ?? []).filter((f) => f.id !== filing.id));
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
