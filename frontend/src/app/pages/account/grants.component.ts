import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { McpSetup, OAuthGrant } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';
import { downloadBlob } from '@shared/download.util';

/**
 * Account API access: the user manages their own OAuth grants (agent/MCP tokens) —
 * list plus revoke individually or all — and (with `mcp.use`) downloads the
 * preconfigured MCP package including the setup snippet.
 */
@Component({
  selector: 'app-account-grants',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent],
  templateUrl: './grants.component.html',
  styleUrl: './grants.component.scss',
})
export class AccountGrantsComponent {
  private readonly api = inject(ApiClient);
  readonly auth = inject(AuthService);

  readonly grants = signal<OAuthGrant[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly setup = signal<McpSetup | null>(null);

  /** MCP actions (download/setup) only for entitled users; admin always has it. */
  readonly canUseMcp = computed(() => this.auth.canAny('mcp.use'));

  constructor() {
    this.reload();
    if (this.canUseMcp()) {
      this.api.mcpConfig().subscribe({
        next: (s) => this.setup.set(s),
        error: () => {
          /* setup snippet optional */
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

  /** Pretty-printed mcpServers snippet to copy. */
  readonly setupJson = computed(() => {
    const s = this.setup();
    return s ? JSON.stringify({ mcpServers: s.mcpServers }, null, 2) : '';
  });

  copySetup(): void {
    const json = this.setupJson();
    if (json) void navigator.clipboard?.writeText(json);
  }
}
