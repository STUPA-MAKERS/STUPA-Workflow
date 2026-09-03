import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { McpSetup, OAuthGrant } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  IconComponent,
} from '@stupa-makers/ui-kit';
import { downloadBlob } from '@shared/download.util';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';

/**
 * Account API access page.
 *
 * The user lists their own OAuth grants, which are the agent and MCP tokens. They can
 * revoke one grant or all grants. With the `mcp.use` permission the user also downloads
 * the preconfigured MCP package and the setup snippet.
 */
@Component({
  selector: 'app-account-grants',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    BadgeComponent,
    ButtonComponent,
    CellDirective,
    DataTableComponent,
    IconComponent,
    LocalizedDatePipe,
    PageHeaderComponent,
    TranslatePipe,
  ],
  templateUrl: './grants.component.html',
  styleUrl: './grants.component.scss',
})
export class AccountGrantsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  readonly auth = inject(AuthService);

  readonly grants = signal<OAuthGrant[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly setup = signal<McpSetup | null>(null);

  /** The MCP download and setup actions need `mcp.use`. An admin always holds it. */
  readonly canUseMcp = computed(() => this.auth.canAny('mcp.use'));

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'scope', label: this.i18n.translate('account.grants.scope') },
    { key: 'created', label: this.i18n.translate('account.grants.created'), width: '12rem' },
    { key: 'expires', label: this.i18n.translate('account.grants.expires'), width: '12rem' },
    { key: 'actions', label: '', align: 'end', width: '4rem' },
  ]);

  /** Track by the grant id, so a reload does not re-create the rows. */
  readonly rowId = (row: unknown): unknown => (row as OAuthGrant).id;

  /**
   * A grant carries its scopes as one space-separated string. Split it, so each scope
   * reads as its own badge instead of one long run-on line.
   */
  scopes(grant: OAuthGrant): string[] {
    return (grant.scope ?? '').split(/\s+/).filter(Boolean);
  }

  constructor() {
    this.reload();
    if (this.canUseMcp()) {
      this.api.mcpConfig().subscribe({
        next: (s) => this.setup.set(s),
        error: () => {
          /* The setup snippet is optional. */
        },
      });
    }
  }

  reload(): void {
    this.loading.set(true);
    this.api.listGrants().subscribe({
      next: (g) => {
        this.grants.set(g);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('account.grants.error');
        this.loading.set(false);
      },
    });
  }

  revoke(id: string): void {
    this.api.revokeGrant(id).subscribe({ next: () => this.reload() });
  }

  revokeAll(): void {
    this.api.revokeAllGrants().subscribe({ next: () => this.reload() });
  }

  downloadPackage(): void {
    this.api.downloadMcpPackage().subscribe({
      next: (blob) => downloadBlob(blob, 'antragsplattform-mcp.tar.gz'),
    });
  }

  readonly setupJson = computed(() => {
    const s = this.setup();
    return s ? JSON.stringify({ mcpServers: s.mcpServers }, null, 2) : '';
  });

  copySetup(): void {
    const json = this.setupJson();
    if (json) void navigator.clipboard?.writeText(json);
  }
}
