import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationShareLink, Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  InputComponent,
  SelectComponent,
  ToastService,
  type SelectOption,
} from '@stupa-makers/ui-kit';

/**
 * The public share links of one application (`application.share`): mint a link, read it
 * once, revoke it.
 *
 * A share link is a read-only public link with its own lifetime (7 to 365 days; the
 * server has no "never"). It is not the applicant's magic link, so the guest settings
 * (`link_ttl_days`) do not apply here.
 *
 * The list and the detail both open it. `open` is two-way; the links load each time it
 * opens, and the fresh token is gone when it closes.
 */
@Component({
  selector: 'app-share-links-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    LocalizedDatePipe,
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    InputComponent,
    SelectComponent,
  ],
  templateUrl: './share-links-dialog.component.html',
  styleUrl: './share-links-dialog.component.scss',
})
export class ShareLinksDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The application whose links the dialog shows. */
  readonly applicationId = input<Uuid | null>(null);
  readonly open = model(false);

  readonly shares = signal<ApplicationShareLink[]>([]);
  readonly loading = signal(false);
  readonly creating = signal(false);
  readonly revoking = signal<Uuid | null>(null);
  readonly ttl = signal('30');
  readonly label = signal('');
  /**
   * The link that was just minted, held only while the dialog is open.
   *
   * This is the one moment the token exists outside the URL bar of whoever pastes it. The
   * server stores a hash; closing the dialog loses the plaintext for good. The whole row
   * is kept, so that a revoke can tell whether the link on screen just stopped working.
   */
  readonly fresh = signal<ApplicationShareLink | null>(null);
  readonly freshUrl = computed(() => this.fresh()?.url ?? null);
  readonly copied = signal(false);

  /** How long a new link lives. "Never" is deliberately not among the options. */
  readonly ttlOptions: SelectOption[] = [
    { value: '7', label: '7' },
    { value: '30', label: '30' },
    { value: '90', label: '90' },
    { value: '365', label: '365' },
  ];

  /** Drops a late answer for an application the dialog no longer shows. */
  private seq = 0;

  constructor() {
    effect(() => {
      const open = this.open();
      const id = this.applicationId();
      untracked(() => {
        if (open && id) this.reset(id);
      });
    });
  }

  close(): void {
    this.open.set(false);
    this.fresh.set(null);
  }

  private reset(id: Uuid): void {
    this.fresh.set(null);
    this.copied.set(false);
    this.label.set('');
    this.shares.set([]);
    this.loading.set(true);
    const seq = ++this.seq;
    this.api.applicationShares(id).subscribe({
      next: (rows) => {
        if (seq !== this.seq) return;
        this.shares.set(rows);
        this.loading.set(false);
      },
      error: () => {
        if (seq !== this.seq) return;
        this.shares.set([]);
        this.loading.set(false);
      },
    });
  }

  create(): void {
    const id = this.applicationId();
    if (!id || this.creating()) return;
    this.creating.set(true);
    this.copied.set(false);
    const label = this.label().trim();
    this.api
      .createApplicationShare(id, { ttlDays: Number(this.ttl()), ...(label ? { label } : {}) })
      .subscribe({
        next: (link) => {
          this.fresh.set(link);
          this.shares.update((rows) => [link, ...rows]);
          this.label.set('');
          this.creating.set(false);
        },
        error: () => {
          this.creating.set(false);
          this.toast.error(this.i18n.translate('applications.share.createError'));
        },
      });
  }

  revoke(shareId: Uuid): void {
    const id = this.applicationId();
    if (!id || this.revoking()) return;
    this.revoking.set(shareId);
    this.api.revokeApplicationShare(id, shareId).subscribe({
      next: (updated) => {
        this.shares.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
        this.revoking.set(null);
        // A link that was just revoked must not stay on screen as something to copy.
        if (updated.id === this.fresh()?.id) this.fresh.set(null);
        this.toast.success(this.i18n.translate('applications.share.revoked'));
      },
      error: () => {
        this.revoking.set(null);
        this.toast.error(this.i18n.translate('applications.share.revokeError'));
      },
    });
  }

  /** Copy the fresh link. The Clipboard API can be absent, so the write is optional. */
  copy(): void {
    const url = this.freshUrl();
    if (!url) return;
    void navigator.clipboard?.writeText(url)?.then(
      () => this.copied.set(true),
      () => this.copied.set(false),
    );
  }

  /** Whether a link still opens. Revoked and expired both read as dead. */
  protected isLive(share: ApplicationShareLink): boolean {
    return share.revokedAt === null && new Date(share.expiresAt).getTime() > Date.now();
  }
}
