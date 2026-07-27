import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, type SafeResourceUrl } from '@angular/platform-browser';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Attachment, ScanState, Uuid } from '@core/api/models';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';
import { CheckboxComponent } from '@stupa-makers/ui-kit';
import { DialogComponent } from '@stupa-makers/ui-kit';
import { IconComponent } from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { formatBytes, scanBadgeVariant } from './applications.util';

/**
 * Attachments panel.
 *
 * The panel uploads files (`POST /applications/{id}/attachments`, 10 MB limit,
 * async ClamAV scan). It downloads them through short-lived signed URLs
 * (`GET /attachments/{id}`).
 *
 * Scan status: `scanned=false` means "scanning" and blocks the download.
 * `scanned=true` means "scan done" only. The download shows the real result.
 * 200 means ready. 409 means quarantine, and the row becomes `quarantined`.
 * 410 means the link expired.
 *
 * Two upload paths exist: the file picker for several files at once, and drag
 * and drop onto the panel. The overlay follows the style of the invoices page.
 * Several files upload one after the other (concatMap), so parallel requests do
 * not trip the rate limit (429). Every row carries a checkbox, next to an "all"
 * checkbox, for bulk delete.
 */
@Component({
  selector: 'app-attachments-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    CheckboxComponent,
    DialogComponent,
    IconComponent,
  ],
  templateUrl: './attachments-panel.component.html',
  styleUrl: './attachments-panel.component.scss',
})
export class AttachmentsPanelComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly applicationId = input.required<Uuid>();
  readonly canUpload = input(false);

  readonly attachments = signal<Attachment[]>([]);
  readonly uploading = signal(false);
  readonly downloadingId = signal<Uuid | null>(null);
  readonly removingId = signal<Uuid | null>(null);

  /** Inline preview of an image or a PDF in a large dialog. It needs no download. */
  private readonly sanitizer = inject(DomSanitizer);
  readonly previewing = signal<Attachment | null>(null);
  readonly previewLoadingId = signal<Uuid | null>(null);
  /** Raw signed URL for the img binding. Angular sanitizes URL contexts itself. */
  readonly previewUrl = signal<string | null>(null);
  readonly previewIsImage = computed(() =>
    (this.previewing()?.mime ?? '').startsWith('image/'),
  );
  /** An iframe needs an explicitly trusted resource URL. The signed URL comes
   *  from our own API and stays app-relative, so the trust is safe. */
  readonly previewFrameUrl = computed<SafeResourceUrl | null>(() => {
    const url = this.previewUrl();
    return url === null ? null : this.sanitizer.bypassSecurityTrustResourceUrl(url);
  });

  readonly selected = signal<ReadonlySet<Uuid>>(new Set());
  readonly bulkDeleting = signal(false);
  readonly selectedCount = computed(() => this.selected().size);
  readonly allSelected = computed(() => {
    const list = this.attachments();
    return list.length > 0 && list.every((a) => this.selected().has(a.id));
  });

  /** Drag and drop overlay, styled like the invoices page. `dragDepth` counts the
   *  enter and leave events of nested children, so the overlay does not flicker. */
  readonly dragActive = signal(false);
  private dragDepth = 0;

  readonly scanVariant = scanBadgeVariant;

  constructor() {
    // Load existing attachments once the applicationId is set (hydration after reload).
    effect(() => {
      const id = this.applicationId();
      if (!id) return;
      this.selected.set(new Set());
      this.api.listAttachments(id).subscribe({
        next: (list) => this.attachments.set(list),
        error: () => {
          /* On an error keep the list empty. Uploads of this session still show. */
        },
      });
    });
  }

  size(att: Attachment): string {
    return formatBytes(att.size);
  }

  scanLabel(state: ScanState): TranslationKey {
    return `applications.attachments.scan.${state}` as TranslationKey;
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.upload(Array.from(input.files ?? []));
    // Reset so the same file can be picked again (change would not fire otherwise).
    input.value = '';
  }

  /** Upload several files one after the other (concatMap), so parallel requests do
   *  not trip the 429 rate limit. The method counts the files that succeed and
   *  shows one summary toast at the end. */
  private upload(files: File[]): void {
    if (this.uploading() || !files.length) return;
    this.uploading.set(true);
    let ok = 0;
    let failedStatus: number | undefined;
    from(files)
      .pipe(concatMap((file) => this.api.uploadAttachment(this.applicationId(), file)))
      .subscribe({
        next: (att) => {
          ok++;
          this.attachments.update((list) => [...list, att]);
        },
        error: (err: { status?: number }) => {
          failedStatus = err.status;
          this.uploading.set(false);
          if (ok > 0) this.toast.success(this.i18n.translate('applications.attachments.added'));
          this.toast.error(this.i18n.translate(this.uploadErrorKey(failedStatus)));
        },
        complete: () => {
          this.uploading.set(false);
          if (ok > 0) this.toast.success(this.i18n.translate('applications.attachments.added'));
        },
      });
  }

  onDragEnter(event: DragEvent): void {
    if (!this.canUpload() || !this.hasFiles(event)) return;
    event.preventDefault();
    this.dragDepth++;
    this.dragActive.set(true);
  }

  onDragOver(event: DragEvent): void {
    if (!this.canUpload() || !this.hasFiles(event)) return;
    event.preventDefault();
  }

  onDragLeave(event: DragEvent): void {
    if (!this.dragActive()) return;
    event.preventDefault();
    this.dragDepth = Math.max(0, this.dragDepth - 1);
    if (this.dragDepth === 0) this.dragActive.set(false);
  }

  onDrop(event: DragEvent): void {
    if (!this.canUpload()) return;
    event.preventDefault();
    this.dragDepth = 0;
    this.dragActive.set(false);
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) this.upload(files);
  }

  private hasFiles(event: DragEvent): boolean {
    return Array.from(event.dataTransfer?.types ?? []).includes('Files');
  }

  isSelected(id: Uuid): boolean {
    return this.selected().has(id);
  }

  toggleSelect(id: Uuid, checked: boolean): void {
    this.selected.update((cur) => {
      const next = new Set(cur);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  toggleSelectAll(checked: boolean): void {
    this.selected.set(checked ? new Set(this.attachments().map((a) => a.id)) : new Set());
  }

  /** Delete the selected attachments sequentially (concatMap), then clear the selection. */
  bulkDelete(): void {
    const ids = [...this.selected()];
    if (!ids.length || this.bulkDeleting()) return;
    this.bulkDeleting.set(true);
    let failed = false;
    from(ids)
      .pipe(concatMap((id) => this.api.deleteAttachment(id)))
      .subscribe({
        next: () => {},
        error: () => {
          failed = true;
          this.bulkDeleting.set(false);
          this.refreshAfterBulk(ids);
          this.toast.error(this.i18n.translate('applications.attachments.deleteError'));
        },
        complete: () => {
          if (failed) return;
          this.bulkDeleting.set(false);
          this.refreshAfterBulk(ids);
          this.toast.success(this.i18n.translate('applications.attachments.deleted'));
        },
      });
  }

  /** Drop the deleted attachments from the list and from the selection. DELETE is
   *  idempotent. After a partial failure the rest stays selected for a retry. */
  private refreshAfterBulk(attempted: Uuid[]): void {
    const id = this.applicationId();
    this.api.listAttachments(id).subscribe({
      next: (list) => {
        const remaining = new Set(list.map((a) => a.id));
        this.attachments.set(list);
        this.selected.update((cur) => new Set([...cur].filter((x) => remaining.has(x))));
      },
      error: () => {
        // Without a fresh list, remove the requested ids locally.
        const removed = new Set(attempted);
        this.attachments.update((list) => list.filter((a) => !removed.has(a.id)));
        this.selected.update((cur) => new Set([...cur].filter((x) => !removed.has(x))));
      },
    });
  }

  private uploadErrorKey(status?: number): TranslationKey {
    switch (status) {
      case 413:
        return 'applications.attachments.error.tooLarge';
      case 415:
        return 'applications.attachments.error.type';
      case 429:
        return 'applications.attachments.error.rate';
      case 503:
        return 'applications.attachments.error.storage';
      default:
        return 'applications.attachments.error.upload';
    }
  }

  /** Preview only a clean image or PDF. The browser can render those two inline. */
  canPreview(att: Attachment): boolean {
    return (
      att.scanState === 'clean' &&
      (att.mime.startsWith('image/') || att.mime === 'application/pdf')
    );
  }

  /** Open the large preview dialog. It fetches a signed URL and renders inline.
   *  The 409 and 410 handling matches download: quarantine and expired link. */
  openPreview(att: Attachment): void {
    if (this.previewLoadingId()) return;
    this.previewLoadingId.set(att.id);
    this.api.attachmentUrl(att.id).subscribe({
      next: (signed) => {
        this.previewLoadingId.set(null);
        // With `inline=1` the download route answers with `Content-Disposition:
        // inline`, so the iframe or img renders instead of starting a download.
        const sep = signed.url.includes('?') ? '&' : '?';
        const url = `${signed.url}${sep}inline=1`;
        // Mobile browsers such as Android Chrome cannot render a PDF in an iframe.
        // Hand the PDF to the system viewer instead of showing an empty dialog.
        if (att.mime === 'application/pdf' && this.coarsePointer()) {
          this.openUrl(url);
          return;
        }
        this.previewUrl.set(url);
        this.previewing.set(att);
      },
      error: (err: { status?: number }) => {
        this.previewLoadingId.set(null);
        if (err.status === 409) {
          this.attachments.update((list) =>
            list.map((a) => (a.id === att.id ? { ...a, scanState: 'quarantined' as ScanState } : a)),
          );
          this.toast.error(this.i18n.translate('applications.attachments.download.conflict'));
        } else if (err.status === 410) {
          this.toast.error(this.i18n.translate('applications.attachments.download.gone'));
        } else {
          this.toast.error(this.i18n.translate('applications.attachments.download.error'));
        }
      },
    });
  }

  closePreview(): void {
    this.previewing.set(null);
    this.previewUrl.set(null);
  }

  download(att: Attachment): void {
    if (this.downloadingId()) return;
    this.downloadingId.set(att.id);
    this.api.attachmentUrl(att.id).subscribe({
      next: (signed) => {
        this.downloadingId.set(null);
        this.openUrl(signed.url);
      },
      error: (err: { status?: number }) => {
        this.downloadingId.set(null);
        if (err.status === 409) {
          // The scan found something, so mark the row as quarantined for good.
          this.attachments.update((list) =>
            list.map((a) => (a.id === att.id ? { ...a, scanState: 'quarantined' as ScanState } : a)),
          );
          this.toast.error(this.i18n.translate('applications.attachments.download.conflict'));
        } else if (err.status === 410) {
          this.toast.error(this.i18n.translate('applications.attachments.download.gone'));
        } else {
          this.toast.error(this.i18n.translate('applications.attachments.download.error'));
        }
      },
    });
  }

  remove(att: Attachment): void {
    if (this.removingId()) return;
    this.removingId.set(att.id);
    this.api.deleteAttachment(att.id).subscribe({
      next: () => {
        this.attachments.update((list) => list.filter((a) => a.id !== att.id));
        this.removingId.set(null);
        this.toast.success(this.i18n.translate('applications.attachments.deleted'));
      },
      error: () => {
        this.removingId.set(null);
        this.toast.error(this.i18n.translate('applications.attachments.deleteError'));
      },
    });
  }

  /** Open the signed URL. A separate method makes it stubbable in tests. */
  protected openUrl(url: string): void {
    window.open(url, '_blank', 'noopener');
  }

  /** Touch-first device without an iframe PDF viewer. A separate method makes it
   *  stubbable in tests. */
  protected coarsePointer(): boolean {
    return window.matchMedia('(pointer: coarse)').matches;
  }
}
