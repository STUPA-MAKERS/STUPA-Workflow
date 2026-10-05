import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import type { AuditChainCheck, AuditVerification, Backup, BackupList } from '../admin.models';
import { checkedAt, formatBytes, formatCount, formatWhen } from './admin-health.util';

/** The colour of a tile: the icon, and the title for an error. */
export type HealthKind = 'ok' | 'warn' | 'error' | 'muted';

/** One tile of "Zustand". */
export interface HealthTile {
  key: 'audit' | 'backup' | 'erasure';
  link: string;
  icon: IconName;
  kind: HealthKind;
  /** Null while the data loads: the tile shows a placeholder line. */
  title: string | null;
  sub: string;
}

/** The state of the audit tile. */
type AuditState =
  | { status: 'loading' }
  | { status: 'stored'; check: AuditVerification }
  | { status: 'live'; check: AuditChainCheck }
  | { status: 'never' }
  | { status: 'error' };

type BackupState = { status: 'loading' } | { status: 'ok'; list: BackupList } | { status: 'error' };

type ErasureState = { status: 'loading' } | { status: 'ok'; open: number } | { status: 'error' };

/**
 * "Zustand" on the admin home page (board Verwaltung): three tiles that each link to
 * their page.
 *
 * - Audit chain (`audit.read`): the newest stored check. Before the first stored check
 *   the tile checks the chain live, when the principal holds `audit.verify`.
 * - Last backup (`backup.manage`): time, kind, status and size of the newest archive.
 * - Open erasure requests (`privacy.manage`).
 *
 * Each tile shows only with its permission. A failed request gives a muted line, never
 * an alarm, because the tile cannot know the state.
 */
@Component({
  selector: 'app-admin-health',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent],
  templateUrl: './admin-health.component.html',
  styleUrl: './admin-health.component.scss',
})
export class AdminHealthComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  private readonly canAudit = this.auth.can('audit.read');
  private readonly canBackup = this.auth.can('backup.manage');
  private readonly canPrivacy = this.auth.can('privacy.manage');

  private readonly audit = signal<AuditState>({ status: 'loading' });
  private readonly backup = signal<BackupState>({ status: 'loading' });
  private readonly erasure = signal<ErasureState>({ status: 'loading' });

  readonly tiles = computed<HealthTile[]>(() => {
    const out: HealthTile[] = [];
    if (this.canAudit) out.push(this.auditTile(this.audit()));
    if (this.canBackup) out.push(this.backupTile(this.backup()));
    if (this.canPrivacy) out.push(this.erasureTile(this.erasure()));
    return out;
  });

  constructor() {
    if (this.canAudit) this.loadAudit();
    if (this.canBackup) {
      this.api.listBackups().subscribe({
        next: (list) => this.backup.set({ status: 'ok', list }),
        error: () => this.backup.set({ status: 'error' }),
      });
    }
    if (this.canPrivacy) {
      this.api.listErasures('open').subscribe({
        next: (rows) => this.erasure.set({ status: 'ok', open: rows.length }),
        error: () => this.erasure.set({ status: 'error' }),
      });
    }
  }

  private loadAudit(): void {
    this.api.latestAuditVerification().subscribe({
      next: (check) => {
        if (check) {
          this.audit.set({ status: 'stored', check });
        } else if (this.auth.can('audit.verify')) {
          // No stored check yet (a fresh installation before the nightly job): check live.
          this.api.verifyAuditChain().subscribe({
            next: (live) => this.audit.set({ status: 'live', check: live }),
            error: () => this.audit.set({ status: 'error' }),
          });
        } else {
          this.audit.set({ status: 'never' });
        }
      },
      error: () => this.audit.set({ status: 'error' }),
    });
  }

  private t(key: TranslationKey, params?: Record<string, string | number>): string {
    return this.i18n.translate(key, params);
  }

  private auditTile(state: AuditState): HealthTile {
    const tile: HealthTile = { key: 'audit', link: '/admin/audit', icon: 'shield', kind: 'muted', title: null, sub: '' };
    switch (state.status) {
      case 'loading':
        return tile;
      case 'never':
        return { ...tile, title: this.t('admin.health.audit.never') };
      case 'error':
        return { ...tile, title: this.t('admin.health.audit.failed') };
      case 'live':
      case 'stored': {
        const check = state.check;
        const count = this.t('admin.health.entries', { count: formatCount(check.checked, this.i18n) });
        const when =
          state.status === 'stored'
            ? this.t('admin.health.audit.checkedAt', { when: formatWhen(checkedAt(state.check), this.i18n) })
            : this.t('admin.health.audit.checkedNow');
        const broken =
          check.brokenAt != null ? this.t('admin.health.audit.brokenAt', { id: check.brokenAt }) : null;
        const sub = [broken, when, count].filter((x): x is string => !!x).join(' · ');
        return check.valid
          ? { ...tile, icon: 'shieldok', kind: 'ok', title: this.t('admin.health.audit.ok'), sub }
          : { ...tile, icon: 'alert', kind: 'error', title: this.t('admin.health.audit.broken'), sub };
      }
    }
  }

  private backupTile(state: BackupState): HealthTile {
    const tile: HealthTile = { key: 'backup', link: '/admin/backups', icon: 'db', kind: 'muted', title: null, sub: '' };
    if (state.status === 'loading') return tile;
    if (state.status === 'error') return { ...tile, title: this.t('admin.health.backup.failed') };
    const newest = newestBackup(state.list.items);
    if (!newest) {
      const key = state.list.enabled ? 'admin.health.backup.none' : 'admin.health.backup.off';
      return { ...tile, title: this.t(key) };
    }
    const parts = [
      this.t(`admin.backups.kind.${newest.kind}` as TranslationKey),
      this.t(`admin.backups.status.${newest.status}` as TranslationKey),
    ];
    if (newest.sizeBytes != null) parts.push(formatBytes(newest.sizeBytes, this.i18n));
    const kind: HealthKind =
      newest.status === 'done' ? 'ok' : newest.status === 'failed' ? 'error' : 'muted';
    return {
      ...tile,
      kind,
      title: this.t('admin.health.backup.last', { when: formatWhen(newest.createdAt, this.i18n) }),
      sub: parts.join(' · '),
    };
  }

  private erasureTile(state: ErasureState): HealthTile {
    const tile: HealthTile = {
      key: 'erasure',
      link: '/admin/privacy',
      icon: 'lock',
      kind: 'muted',
      title: null,
      sub: this.t('admin.health.erasure.sub'),
    };
    if (state.status === 'loading') return tile;
    if (state.status === 'error') return { ...tile, title: this.t('admin.health.erasure.failed') };
    if (state.open === 0) return { ...tile, title: this.t('admin.health.erasure.none') };
    const title =
      state.open === 1
        ? this.t('admin.health.erasure.openOne')
        : this.t('admin.health.erasure.open', { count: state.open });
    return { ...tile, kind: 'warn', title };
  }
}

/** The newest archive by creation time. The list order of the server is not relied on. */
function newestBackup(items: Backup[]): Backup | null {
  let best: Backup | null = null;
  for (const b of items) {
    if (!best || new Date(b.createdAt).getTime() > new Date(best.createdAt).getTime()) best = b;
  }
  return best;
}
