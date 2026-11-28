import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { type PretixConnection, type PretixConnectionIn, SalesApiService } from '@core/api/sales.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { InputComponent } from '@stupa-makers/ui-kit';
import {
  ScreenGroupDirective,
  SettingsScreenComponent,
  type SettingsGroup,
  type SettingsNotice,
  type SettingsState,
} from '@stupa-makers/ui-kit/screens';
import { type Observable, tap } from 'rxjs';
import { isPaperlessUrl } from '../paperless/paperless.component';
import { salesAdmin } from '../sales-admin';

/** What the form edits; an empty token keeps the stored one. */
export interface PretixDraft {
  readonly baseUrl: string;
  readonly organizer: string;
  readonly token: string;
  readonly showSales: boolean;
  readonly bookIncome: boolean;
}

/** The switch of each part (003082). */
const SWITCHES = [
  { key: 'showSales', label: 'admin.pretix.showSales' },
  { key: 'bookIncome', label: 'admin.pretix.bookIncome' },
] as const satisfies readonly {
  readonly key: keyof PretixDraft;
  readonly label: TranslationKey;
}[];

/**
 * "Pretix" (permission `admin.pretix`, spec 003080): the address of a pretix instance, the
 * organizer, the team token and the switches `Verkaufszahlen zeigen` and `Einnahmen buchen`
 * (003082). The server never returns the token, refuses a host outside
 * `PRETIX_HOST_ALLOWLIST` (422 `pretix_host_not_allowed`) and needs the token again for a
 * new address. "Verbindung testen" reads the organizer. "Fehlgeschlagene Buchungen" lists
 * each order or refund the platform could not book, with its cause (003086). The switch
 * `Einnahmen buchen` also books the Mollie money (003097, 003103).
 */
@Component({
  selector: 'app-admin-pretix',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, SettingsScreenComponent, ScreenGroupDirective, InputComponent],
  templateUrl: './pretix.component.html',
})
export class PretixComponent {
  private readonly api = inject(SalesApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly shared = salesAdmin({
    forbidden: 'admin.pretix.forbidden',
    loadError: 'admin.pretix.loadError',
    test: 'admin.pretix.test',
    testOk: 'admin.pretix.testOk',
    failed: 'admin.pretix.failed',
  });

  /** The server refused the host of this address at the last save. */
  private readonly refusedUrl = signal<string | null>(null);

  protected readonly form: SettingsForm<PretixConnection, PretixDraft> = settingsForm<
    PretixConnection,
    PretixDraft,
    PretixConnectionIn
  >({
    allowed: () => this.auth.can('admin.pretix'),
    load: () => this.api.getPretix(),
    put: (body) => this.put(body),
    draftOf: (s) => ({
      baseUrl: s.baseUrl ?? '',
      organizer: s.organizer ?? '',
      token: '',
      showSales: s.showSales,
      bookIncome: s.bookIncome,
    }),
    initial: { baseUrl: '', organizer: '', token: '', showSales: false, bookIncome: false },
    body: () => {
      const d = this.draft();
      if (this.urlError() || this.tokenError()) return null;
      return {
        baseUrl: d.baseUrl.trim() || null,
        organizer: d.organizer.trim() || null,
        ...(d.token ? { token: d.token } : {}),
        showSales: d.showSales,
        bookIncome: d.bookIncome,
      };
    },
    dirty: (s) => {
      const d = this.draft();
      return (
        d.baseUrl.trim() !== (s.baseUrl ?? '') ||
        d.organizer.trim() !== (s.organizer ?? '') ||
        d.token !== '' ||
        SWITCHES.some(({ key }) => d[key] !== s[key])
      );
    },
  });
  protected readonly draft = this.form.draft;
  protected readonly saving = this.form.saving;
  protected readonly dirty = this.form.dirty;
  protected readonly tokenSet = computed(() => !!this.form.saved()?.tokenSet);

  protected readonly urlError = computed(() => {
    const url = this.draft().baseUrl.trim();
    if (url && !isPaperlessUrl(url)) return this.i18n.translate('admin.pretix.urlInvalid');
    if (url && url === this.refusedUrl()) {
      return this.i18n.translate('admin.pretix.hostNotAllowed', {
        hosts: (this.form.saved()?.allowedHosts ?? []).join(', ') || '–',
      });
    }
    return '';
  });

  /** A new address with a stored token needs the token again. */
  protected readonly tokenError = computed(() => {
    const saved = this.form.saved();
    const d = this.draft();
    const url = d.baseUrl.trim().replace(/\/+$/, '');
    const moved = !!url && url !== (saved?.baseUrl ?? '');
    return saved?.tokenSet && moved && !d.token ? this.i18n.translate('admin.pretix.tokenAgain') : '';
  });

  protected readonly screenState = computed<SettingsState>(() =>
    this.shared.screenState(this.form.state(), () => this.form.reload()),
  );

  protected readonly notice = computed<SettingsNotice | null>(() =>
    this.shared.failedError() ? { kind: 'error', text: this.i18n.translate('admin.pretix.failedLoadError') } : null,
  );

  protected readonly groups = computed<SettingsGroup[]>(() => {
    const d = this.draft();
    const s = this.form.saved();
    const idle = !(s?.baseUrl && s.organizer && s.tokenSet) || this.dirty();
    return [
      { key: 'connection', label: this.i18n.translate('admin.pretix.connection'), rows: [] },
      {
        key: 'parts',
        label: this.i18n.translate('admin.pretix.parts'),
        rows: SWITCHES.map(({ key, label }) => ({
          key,
          label: this.i18n.translate(label),
          control: 'switch' as const,
          value: d[key],
        })),
      },
      { key: 'actions', rows: [this.shared.testRow(idle)] },
      ...this.shared.failedGroups(),
    ];
  });

  constructor() {
    if (this.auth.can('admin.pretix')) this.shared.loadFailed(this.api.pretixFailed());
  }

  private put(body: PretixConnectionIn): Observable<PretixConnection> {
    return this.api.putPretix(body).pipe(
      tap({
        next: () => this.refusedUrl.set(null),
        error: (err: { error?: { code?: string } } | null) => {
          if (err?.error?.code === 'pretix_host_not_allowed') this.refusedUrl.set(body.baseUrl);
        },
      }),
    );
  }

  protected patch(change: Partial<PretixDraft>): void {
    this.form.patch(change);
  }

  protected set(key: string, value: boolean): void {
    const found = SWITCHES.find((s) => s.key === key);
    if (found) this.patch({ [found.key]: value });
  }

  protected act(key: string): void {
    if (key === 'test') this.shared.test(this.api.testPretix());
  }

  protected discard(): void {
    this.refusedUrl.set(null);
    this.form.reset();
  }

  protected save(): void {
    this.form.save();
  }
}
