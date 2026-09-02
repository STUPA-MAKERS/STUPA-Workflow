import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import {
  ButtonComponent,
  CardComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { downloadBlob } from '@shared/download.util';
import { AdminApiService } from '../admin-api.service';
import type { Backup, BackupKind, BackupStatus } from '../admin.models';

/** File name the browser saves an archive under. Mirrors the server-side name. */
function archiveFileName(createdAt: string): string {
  const stamp = new Date(createdAt).toISOString().replace(/[-:]/g, '').replace(/\..+$/, 'Z');
  return `antrag-${stamp}.tar.age`;
}

/** Poll interval while a backup job is still running, in milliseconds. */
const POLL_MS = 3000;

/** Stop polling after this long, so a stuck worker cannot poll for ever. */
const POLL_TIMEOUT_MS = 30 * 60 * 1000;

/**
 * Admin backup page (permission `backup.manage`).
 *
 * The page lists every archive, creates one, downloads one, uploads one, restores one
 * and deletes one. The archive itself never passes through this component: a download
 * is a short-lived signed URL, and an upload goes straight to the API as multipart.
 *
 * Two things here are deliberately awkward for the user, because both are destructive:
 * a restore needs the archive picked and then confirmed in its own dialog, and a pinned
 * archive has to be unpinned before it can be deleted.
 */
@Component({
  selector: 'app-admin-backups',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    CardComponent,
    DataTableComponent,
    CellDirective,
    DialogComponent,
    IconComponent,
    InputComponent,
    PageHeaderComponent,
  ],
  templateUrl: './backups.component.html',
  styleUrl: './backups.component.scss',
})
export class BackupsComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  protected readonly rows = signal<Backup[]>([]);
  /** False without an age recipient: this installation cannot create an archive. */
  protected readonly enabled = signal(true);
  /** False without the private key: it cannot read one either, so no restore, no import. */
  protected readonly restoreEnabled = signal(true);
  protected readonly retentionCount = signal(0);
  /** True until the first list response, so the table shows its loading state once. */
  protected readonly loading = signal(true);
  protected readonly busy = signal(false);

  protected readonly createNote = signal('');
  protected readonly creating = signal(false);
  protected readonly confirmRestore = signal<Backup | null>(null);
  protected readonly restoreConfirmText = signal('');
  protected readonly confirmDelete = signal<Backup | null>(null);

  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollStartedAt = 0;

  constructor() {
    this.reload();
  }

  protected readonly columns = computed<ColumnDef[]>(() => [
    { key: 'createdAt', label: this.i18n.translate('admin.backups.col.created') },
    { key: 'kind', label: this.i18n.translate('admin.backups.col.kind') },
    { key: 'status', label: this.i18n.translate('admin.backups.col.status') },
    { key: 'size', label: this.i18n.translate('admin.backups.col.size'), align: 'end' },
    { key: 'contents', label: this.i18n.translate('admin.backups.col.contents') },
    { key: 'note', label: this.i18n.translate('admin.backups.col.note') },
    {
      key: 'actions',
      label: this.i18n.translate('admin.common.actions'),
      align: 'end',
      width: '14rem',
    },
  ]);

  /** True while any archive is still being built, which is what drives the poll. */
  protected readonly anyRunning = computed(() =>
    this.rows().some((r) => r.status === 'pending' || r.status === 'running'),
  );

  protected kindLabel(kind: BackupKind): string {
    return this.i18n.translate(`admin.backups.kind.${kind}` as never);
  }

  protected statusLabel(status: BackupStatus): string {
    return this.i18n.translate(`admin.backups.status.${status}` as never);
  }

  /** Human-readable size. Archives are megabytes to gigabytes, so bytes help nobody. */
  protected sizeLabel(bytes: number | null | undefined): string {
    if (bytes == null) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
  }

  protected reload(): void {
    this.api.listBackups().subscribe({
      next: (list) => {
        this.rows.set(list.items);
        this.enabled.set(list.enabled);
        this.restoreEnabled.set(list.restoreEnabled);
        this.retentionCount.set(list.retentionCount);
        this.loading.set(false);
        this.syncPolling();
      },
      error: () => this.loading.set(false),
    });
  }

  /**
   * Start polling while a job runs, and stop as soon as none does.
   *
   * A backup of a real dataset takes minutes, so the page has to keep itself current
   * without the user reloading. The poll skips the global loading overlay, or the whole
   * page would flash every three seconds.
   */
  private syncPolling(): void {
    if (this.anyRunning() && this.pollTimer === null) {
      this.pollStartedAt = Date.now();
      this.pollTimer = setInterval(() => this.pollOnce(), POLL_MS);
      return;
    }
    if (!this.anyRunning()) this.stopPolling();
  }

  private pollOnce(): void {
    if (Date.now() - this.pollStartedAt > POLL_TIMEOUT_MS) {
      this.stopPolling();
      return;
    }
    const pending = this.rows().filter((r) => r.status === 'pending' || r.status === 'running');
    for (const row of pending) {
      this.api.getBackup(row.id).subscribe({
        next: (fresh) => {
          this.rows.update((rows) => rows.map((r) => (r.id === fresh.id ? fresh : r)));
          if (fresh.status === 'failed') {
            this.toast.error(this.i18n.translate('admin.backups.toast.failed'));
          }
          if (fresh.status === 'done') {
            this.toast.success(this.i18n.translate('admin.backups.toast.created'));
          }
          this.syncPolling();
        },
        error: () => this.stopPolling(),
      });
    }
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  protected create(): void {
    this.creating.set(true);
    this.api.createBackup(this.createNote().trim() || null).subscribe({
      next: (row) => {
        this.rows.update((rows) => [row, ...rows]);
        this.createNote.set('');
        this.creating.set(false);
        this.toast.show(this.i18n.translate('admin.backups.toast.started'), 'info');
        this.syncPolling();
      },
      error: () => this.creating.set(false),
    });
  }

  /**
   * Download one archive.
   *
   * The API streams the bytes. It deliberately does NOT hand out a presigned MinIO URL:
   * the object store sits on the internal Docker network, so such a URL names a host the
   * browser cannot resolve.
   */
  protected download(row: Backup): void {
    this.api.exportBackup(row.id).subscribe({
      next: (blob) => downloadBlob(blob, archiveFileName(row.createdAt)),
    });
  }

  protected upload(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    this.busy.set(true);
    this.api.importBackup(file).subscribe({
      next: (row) => {
        this.rows.update((rows) => [row, ...rows]);
        this.busy.set(false);
        this.toast.success(this.i18n.translate('admin.backups.toast.imported'));
        input.value = '';
      },
      error: () => {
        this.busy.set(false);
        input.value = '';
      },
    });
  }

  protected togglePin(row: Backup): void {
    this.api.updateBackup(row.id, { pinned: !row.pinned }).subscribe({
      next: (fresh) => this.rows.update((rows) => rows.map((r) => (r.id === fresh.id ? fresh : r))),
    });
  }

  protected askRestore(row: Backup): void {
    this.restoreConfirmText.set('');
    this.confirmRestore.set(row);
  }

  /**
   * True once the operator has typed the confirmation word.
   *
   * The API demands the same literal. Typing it is the point: a restore replaces the
   * whole platform, and a single mis-click must not be enough.
   */
  protected readonly restoreArmed = computed(
    () => this.restoreConfirmText().trim().toUpperCase() === 'RESTORE',
  );

  protected doRestore(): void {
    const row = this.confirmRestore();
    if (!row || !this.restoreArmed()) return;
    this.busy.set(true);
    this.api.restoreBackup(row.id).subscribe({
      next: () => {
        this.confirmRestore.set(null);
        this.busy.set(false);
        // The restore replaces the session table, so this session dies with it. Say so
        // rather than letting the next request fail with an unexplained 401.
        this.toast.show(
          this.i18n.translate('admin.backups.toast.restoreStarted'),
          'warning',
        );
      },
      error: () => this.busy.set(false),
    });
  }

  protected askDelete(row: Backup): void {
    this.confirmDelete.set(row);
  }

  protected doDelete(): void {
    const row = this.confirmDelete();
    if (!row) return;
    this.busy.set(true);
    this.api.deleteBackup(row.id).subscribe({
      next: () => {
        this.rows.update((rows) => rows.filter((r) => r.id !== row.id));
        this.confirmDelete.set(null);
        this.busy.set(false);
      },
      error: () => this.busy.set(false),
    });
  }
}
