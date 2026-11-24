import { ChangeDetectionStrategy, Component, type OnDestroy, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe, formatMoment } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { backupStatus } from '@shared/ui';
import {
  ButtonComponent,
  ButtonGroupComponent,
  ConfirmDialogComponent,
  DialogComponent,
  downloadBlob,
  FilePickerComponent,
  formatBytes,
  IconComponent,
  InputComponent,
  NoteComponent,
  type RowMenuItem,
  type RowMenuSection,
  ToastService,
  SectionComponent,
  DialogBodyDirective,
  type Action,
  type ListRow,
  type LoadState as ListState,
} from '@stupa-makers/ui-kit';
import { RecordSectionComponent, SectionsScreenComponent } from '@stupa-makers/ui-kit/screens';
import { AdminApiService } from '../admin-api.service';
import type { Backup, BackupKind } from '../admin.models';

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
 * Backups (permission `backup.manage`).
 *
 * The page creates an archive (with an optional note), imports a `.tar.age` file, and
 * lists every archive with its kind, status, size, contents and note. A row downloads,
 * pins, restores and deletes an archive. The archive itself never passes through this
 * component as a URL: the download streams through the API, and an upload goes straight
 * to the API as multipart.
 *
 * Two things here are deliberately awkward for the user, because both are destructive:
 * a restore needs the confirmation word typed in its own dialog, and a pinned archive
 * has to be unpinned before it can be deleted. Retention keeps the newest archives; a
 * pinned archive and a copy taken before a restore do not count.
 *
 * A disabled import shows its reason, because a dead control with no reason reads as a broken page:
 * an import decrypts the archive to verify it and needs the private key, which the API does not
 * have here.
 */
@Component({
  selector: 'app-admin-backups',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DialogBodyDirective,
    SectionComponent,
    FilePickerComponent,
    ConfirmDialogComponent,
    RecordSectionComponent,
    SectionsScreenComponent,
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    ButtonComponent,
    ButtonGroupComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
  ],
  templateUrl: './backups.component.html',
  styleUrl: './backups.component.scss',
})
export class BackupsComponent implements OnDestroy {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  protected readonly rows = signal<readonly Backup[]>([]);
  /** False without an age recipient: this installation cannot create an archive. */
  protected readonly enabled = signal(true);
  /** False without the private key: it cannot read one either, so no restore, no import. */
  protected readonly restoreEnabled = signal(true);
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

  /**
   * The columns. The note stands under the kind and a failure under the status, so the
   * seven values fit the width of the admin sheet without a sideways scroll.
   * Every column but the kind has a width floor; the kind takes the slack.
   */
  /** The read of the list failed (002405). */
  protected readonly loadError = signal(false);
  /** The backups as the list state of the record section (002258). */
  protected readonly list = computed<ListState<readonly ListRow[]>>(() => {
    if (this.loading()) return { state: 'loading' };
    if (this.loadError())
      return { state: 'error', message: this.i18n.translate('admin.backups.loadFailed'), retry: () => this.retry() };
    const rows = this.rows().map((r) => this.listRow(r));
    return rows.length
      ? { state: 'ready', data: rows }
      : { state: 'empty', icon: 'db', heading: this.i18n.translate('admin.backups.empty') };
  });
  private readonly byId = computed(() => new Map(this.rows().map((r) => [r.id, r])));

  /** One backup as a row: the time, the kind, the note, the size and the contents, the status, the menu. */
  private listRow(r: Backup): ListRow {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const st = backupStatus(r.status);
    const meta = [
      this.kindLabel(r.kind),
      r.pinned ? t('admin.backups.pinned') : null,
      r.note?.trim() || null,
      r.sizeBytes === null || r.sizeBytes === undefined ? null : this.sizeLabel(r.sizeBytes),
      r.objectCount === null || r.objectCount === undefined
        ? null
        : this.i18n.translate('admin.backups.objectCount', { count: r.objectCount }),
      r.status === 'failed' ? (r.error ?? null) : null,
    ].filter((x): x is string => !!x);
    const actions: Action[] =
      r.status === 'done'
        ? this.rowMenu(r)[0].items.map((i) => ({
            key: i.id,
            label: i.label,
            icon: i.icon,
            kind: i.danger ? 'danger' : undefined,
            disabled: !!i.disabledReason,
            disabledReason: i.disabledReason ?? undefined,
          }))
        : [];
    return {
      id: r.id,
      title: formatMoment(r.createdAt, this.i18n.formatLocale(), 'medium'),
      meta,
      status: { label: t(st.key), kind: st.kind },
      actions,
    };
  }

  /** An item of the row menu of a backup. */
  protected onRowAction(id: string, key: string): void {
    const row = this.byId().get(id);
    if (row) this.onRowMenu(row, { id: key, label: key });
  }

  /** The retry of a failed read. */
  protected retry(): void {
    this.loading.set(true);
    this.reload();
  }

  protected readonly anyRunning = computed(() =>
    this.rows().some((r) => r.status === 'pending' || r.status === 'running'),
  );

  protected kindLabel(kind: BackupKind): string {
    return this.i18n.translate(`admin.backups.kind.${kind}` as never);
  }

  /** Status of an archive as coloured text. */
  protected readonly backupStatus = backupStatus;

  /** Human-readable size. Archives are megabytes to gigabytes, so bytes help nobody. */
  protected sizeLabel(bytes: number | null | undefined): string {
    return formatBytes(bytes, this.i18n.formatLocale());
  }

  /** "Manuell · vor der Haushaltsabstimmung": the line under the restore title. */
  protected restoreSubtitle(row: Backup): string {
    return [this.kindLabel(row.kind), row.note?.trim()].filter((x): x is string => !!x).join(' · ');
  }

  protected reload(): void {
    this.api.listBackups().subscribe({
      next: (list) => {
        this.rows.set(list.items);
        this.enabled.set(list.enabled);
        this.restoreEnabled.set(list.restoreEnabled);
        this.loadError.set(false);
        this.loading.set(false);
        this.syncPolling();
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
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
            this.toast.show(this.i18n.translate('admin.backups.toast.failed'), 'error');
          }
          if (fresh.status === 'done') {
            this.toast.show(this.i18n.translate('admin.backups.toast.created'), 'success');
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
        this.toast.show(this.i18n.translate('admin.backups.toast.started'));
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
  /** The ⋮ menu of a finished archive. */
  protected rowMenu(row: Backup): RowMenuSection[] {
    const t = (key: TranslationKey): string => this.i18n.translate(key);
    const items: RowMenuItem[] = [
      { id: 'download', label: t('admin.backups.download'), icon: 'download' },
      {
        id: 'pin',
        label: t(row.pinned ? 'admin.backups.unpin' : 'admin.backups.pin'),
        icon: row.pinned ? 'pinslash' : 'pin',
      },
      ...(this.restoreEnabled()
        ? [
            {
              id: 'restore',
              label: t('admin.backups.restore'),
              icon: 'history',
            } satisfies RowMenuItem,
          ]
        : []),
      {
        id: 'delete',
        label: t('admin.common.delete'),
        icon: 'trash',
        danger: true,
        disabledReason: row.pinned ? t('admin.backups.pinnedHint') : null,
      },
    ];
    return [{ items }];
  }

  protected onRowMenu(row: Backup, item: RowMenuItem): void {
    if (item.id === 'download') this.download(row);
    else if (item.id === 'pin') this.togglePin(row);
    else if (item.id === 'restore') this.askRestore(row);
    else if (item.id === 'delete') this.askDelete(row);
  }

  protected download(row: Backup): void {
    this.api.exportBackup(row.id).subscribe({
      next: (blob) => downloadBlob(blob, archiveFileName(row.createdAt)),
    });
  }

  protected upload(files: File[]): void {
    const file = files[0];
    if (!file) return;
    this.busy.set(true);
    this.api.importBackup(file).subscribe({
      next: (row) => {
        this.rows.update((rows) => [row, ...rows]);
        this.busy.set(false);
        this.toast.show(this.i18n.translate('admin.backups.toast.imported'), 'success');
      },
      error: () => this.busy.set(false),
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

  /**
   * The restore replaces the session table, so this session dies with it. The page says so rather
   * than letting the next request fail with an unexplained 401.
   */
  protected doRestore(): void {
    const row = this.confirmRestore();
    if (!row || !this.restoreArmed()) return;
    this.busy.set(true);
    this.api.restoreBackup(row.id).subscribe({
      next: () => {
        this.confirmRestore.set(null);
        this.busy.set(false);
        this.toast.show(this.i18n.translate('admin.backups.toast.restoreStarted'), 'warning');
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
