import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { McpSetup, OAuthGrant } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { downloadBlob } from '@shared/download.util';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, CopyButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { scopeLabel } from './scope-labels';
import { ConfirmDialogComponent } from '@shared/ui/confirm-dialog/confirm-dialog.component';

/** What the confirmation dialog asks: revoke one grant, or all of them. */
type Confirm = { kind: 'one'; grant: OAuthGrant } | { kind: 'all' };

/**
 * Account page "API-Zugang" (board Konto-API-Zugang).
 *
 * - "MCP-Server" (only with `mcp.use`): the package download, the steps to install it,
 *   the `mcpServers` entry with "Kopieren", and the platform URL the package is wired to.
 * - "Aktive Zugriffe · n": the own OAuth grants (agent and MCP tokens), newest first. A
 *   row shows the scopes by their labels, "Erstellt" and "Läuft ab". Every token expires
 *   (90 days at most), so there is no "Läuft nie ab": a missing time shows a dash.
 * - "Widerrufen" (one grant) and "Alle widerrufen" are destructive and ask first.
 */
@Component({
  selector: 'app-account-grants',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ConfirmDialogComponent,
    ButtonComponent,
    CopyButtonComponent,
    EmptyStateComponent,
    IconComponent,
    LocalizedDatePipe,
    NoteComponent,
    PageHeaderComponent,
    SkeletonComponent,
    TranslatePipe,
  ],
  templateUrl: './grants.component.html',
  styleUrl: './grants.component.scss',
})
export class AccountGrantsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);

  readonly grants = signal<OAuthGrant[]>([]);
  readonly loading = signal(true);
  /** The list loaded once. Until then the heading shows no count. */
  readonly loaded = signal(false);
  /** The list could not load. */
  readonly loadError = signal(false);
  /** A revoke or the download failed. */
  readonly actionError = signal<TranslationKey | null>(null);
  readonly setup = signal<McpSetup | null>(null);
  readonly downloading = signal(false);

  /** The open confirmation, or null. */
  readonly confirm = signal<Confirm | null>(null);
  /** The text of the revoke confirmation: the scopes of one grant, or all grants. */
  readonly confirmText = computed(() => {
    const c = this.confirm();
    if (!c) return '';
    return c.kind === 'one'
      ? this.i18n.translate('account.grants.revokeConfirm', { scopes: this.scopeLabels(c.grant) })
      : this.i18n.translate('account.grants.revokeAllConfirm');
  });
  readonly revoking = signal(false);

  /** The MCP download and setup need `mcp.use`. An admin always holds it. */
  readonly canUseMcp = computed(() => this.auth.canAny('mcp.use'));

  /**
   * The install command without the shell comment the server adds ("pip install -e .").
   * The step says where to run it.
   */
  readonly installCommand = computed(() => (this.setup()?.install ?? '').split('#')[0].trim());

  /** The `mcpServers` entry to paste into the MCP client. */
  readonly setupJson = computed(() => {
    const s = this.setup();
    return s ? JSON.stringify({ mcpServers: s.mcpServers }, null, 2) : '';
  });


  constructor() {
    this.reload();
    if (this.canUseMcp()) {
      this.api.mcpConfig().subscribe({
        next: (s) => this.setup.set(s),
        error: () => {
          /* Without the snippet the card keeps the download. */
        },
      });
    }
  }

  reload(): void {
    this.loading.set(true);
    this.api.listGrants().subscribe({
      next: (g) => {
        this.grants.set(g);
        this.loaded.set(true);
        this.loadError.set(false);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** The granted scopes by their labels, in the order of the grant. */
  scopeLabels(grant: OAuthGrant): string {
    return (grant.scope ?? '')
      .split(/\s+/)
      .filter(Boolean)
      .map((key) => scopeLabel(this.i18n, key))
      .join(', ');
  }

  askRevoke(grant: OAuthGrant): void {
    this.actionError.set(null);
    this.confirm.set({ kind: 'one', grant });
  }

  askRevokeAll(): void {
    this.actionError.set(null);
    this.confirm.set({ kind: 'all' });
  }

  /** Revoke what the dialog asked for, then load the list again. */
  doRevoke(): void {
    const c = this.confirm();
    if (!c || this.revoking()) return;
    this.revoking.set(true);
    const call = c.kind === 'one' ? this.api.revokeGrant(c.grant.id) : this.api.revokeAllGrants();
    call.subscribe({
      next: () => {
        this.revoking.set(false);
        this.confirm.set(null);
        this.reload();
      },
      error: () => {
        this.revoking.set(false);
        this.confirm.set(null);
        this.actionError.set('account.grants.revokeError');
      },
    });
  }

  downloadPackage(): void {
    if (this.downloading()) return;
    this.downloading.set(true);
    this.actionError.set(null);
    this.api.downloadMcpPackage().subscribe({
      next: (blob) => {
        this.downloading.set(false);
        downloadBlob(blob, 'antragsplattform-mcp.tar.gz');
      },
      error: () => {
        this.downloading.set(false);
        this.actionError.set('account.mcp.downloadError');
      },
    });
  }
}
