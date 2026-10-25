import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { from } from 'rxjs';
import { concatMap } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { API_BASE_URL } from '@core/api/api.config';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Attachment, ScanState, Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CheckboxComponent,
  DropOverlayComponent,
  EmptyStateComponent,
  FileDropDirective,
  FileViewerComponent,
  type FileViewerItem,
  IconComponent,
  matchesMedia,
  MEDIA,
  SelectionBarComponent,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { scanStatus } from '@shared/status-kind.util';
import {
  ImageThumbComponent,
  inlineUrl,
  isThumbImage,
} from '@shared/ui/image-thumb/image-thumb.component';
import { chatFileUrl } from '@shared/ui/chat/chat.util';
import { formatBytes } from './applications.util';

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
 * The preview opens the full-screen kit viewer over every file of the panel that can
 * preview (a clean image or PDF), so its arrows step through them. The panel fetches the
 * URL of a file when the viewer reaches it, with the same 409/410 handling as a download.
 *
 * Two upload paths exist: the file picker for several files at once, and drag
 * and drop onto the panel (`appFileDrop`, with `app-drop-overlay`). A page that takes a
 * drop on a larger area turns the panel's own target off (`dropTarget`) and hands the
 * files to `upload`.
 * Several files upload one after the other (concatMap), so parallel requests do
 * not trip the rate limit (429). Every row carries a checkbox, next to an "all"
 * checkbox, for bulk delete.
 */
@Component({
  selector: 'app-attachments-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DropOverlayComponent,
    EmptyStateComponent,
    FileDropDirective,
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    FileViewerComponent,
    IconComponent,
    ImageThumbComponent,
    SelectionBarComponent,
    StatusTextComponent,
  ],
  templateUrl: './attachments-panel.component.html',
  styleUrl: './attachments-panel.component.scss',
})
export class AttachmentsPanelComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly apiBase = inject(API_BASE_URL);

  readonly applicationId = input.required<Uuid>();
  readonly canUpload = input(false);
  /** Show the heading "Anhänge". A side sheet that has the same title hides it (it stays
   *  for screen readers). */
  readonly titled = input(true);
  /**
   * Delete is a data change. The backend refuses it for an applicant in a locked state
   * (409), although an upload works there. Without this input the panel uses
   * `canUpload`.
   */
  readonly canDelete = input<boolean | undefined>(undefined);
  readonly deleteAllowed = computed(() => this.canDelete() ?? this.canUpload());
  /** The panel is the drop target. False: the page around it takes the drop. */
  readonly dropTarget = input(true);
  /** The number of attachments, after the first load and after each change. */
  readonly countChange = output<number>();

  readonly attachments = signal<Attachment[]>([]);
  readonly uploading = signal(false);
  readonly downloadingId = signal<Uuid | null>(null);
  readonly removingId = signal<Uuid | null>(null);

  /** The full-screen viewer over the files that preview. */
  readonly viewerOpen = signal(false);
  readonly viewerIndex = signal(0);
  readonly previewLoadingId = signal<Uuid | null>(null);
  /** The inline URLs the viewer fetched since it opened, by attachment. */
  private readonly previewUrls = signal<ReadonlyMap<Uuid, string>>(new Map());
  /** The URL requests in flight while the viewer moves. */
  private readonly fetching = new Set<Uuid>();
  /** False on a coarse pointer: there a PDF goes to the system viewer, not into the frame. */
  private readonly pdfInViewer = signal(true);
  /** The files the viewer steps through, in the order of the list. */
  readonly viewable = computed(() =>
    this.attachments().filter(
      (a) => this.canPreview(a) && (this.pdfInViewer() || a.mime !== 'application/pdf'),
    ),
  );
  /** A file whose URL is not fetched yet has an empty URL: the viewer shows its loading state. */
  readonly viewerItems = computed<FileViewerItem[]>(() => {
    const urls = this.previewUrls();
    return this.viewable().map((a) => ({ name: a.filename, mime: a.mime, url: urls.get(a.id) ?? '' }));
  });
  /** The file the viewer shows, for its download action. */
  readonly viewerFile = computed<Attachment | null>(() => {
    const list = this.viewable();
    return list[Math.min(Math.max(0, this.viewerIndex()), list.length - 1)] ?? null;
  });

  readonly selected = signal<ReadonlySet<Uuid>>(new Set());
  readonly bulkDeleting = signal(false);
  readonly selectedCount = computed(() => this.selected().size);

  /** The scan state as coloured text. */
  readonly scan = scanStatus;
  /** The list arrived (or failed): from then on the count is true. */
  private readonly loaded = signal(false);

  constructor() {
    effect(() => {
      const id = this.applicationId();
      if (!id) return;
      this.selected.set(new Set());
      this.api.listAttachments(id).subscribe({
        next: (list) => {
          this.attachments.set(list);
          this.loaded.set(true);
        },
        error: () => {
          this.loaded.set(true);
        },
      });
    });
    effect(() => {
      const count = this.attachments().length;
      if (this.loaded()) this.countChange.emit(count);
    });
  }

  size(att: Attachment): string {
    return formatBytes(att.size, this.i18n.locale());
  }

  /** The input resets, so the same file can be picked again; `change` would not fire otherwise. */
  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.upload(Array.from(input.files ?? []));
    input.value = '';
  }

  /** Upload several files one after the other (concatMap), so parallel requests do
   *  not trip the 429 rate limit. The method counts the files that succeed and
   *  shows one summary toast at the end. The picker, a drop on the panel and a drop on
   *  the page around it end here. */
  upload(files: File[]): void {
    if (!this.canUpload() || this.uploading() || !files.length) return;
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

  isSelected(id: Uuid): boolean {
    return this.selected().has(id);
  }

  clearSelection(): void {
    this.selected.set(new Set());
  }

  toggleSelect(id: Uuid, checked: boolean): void {
    this.selected.update((cur) => {
      const next = new Set(cur);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  /** Delete the selected attachments sequentially (concatMap), then clear the selection. */
  bulkDelete(): void {
    const ids = [...this.selected()];
    if (!this.deleteAllowed() || !ids.length || this.bulkDeleting()) return;
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

  /** A clean raster image shows a small thumbnail in its row. */
  isImage(att: Attachment): boolean {
    return isThumbImage(att);
  }

  /** The thumbnail streams through the session-gated download route as an inline
   *  preview. It needs no signed URL. */
  thumbUrl(att: Attachment): string {
    return inlineUrl(chatFileUrl(this.apiBase, att.id));
  }

  /** Preview only a clean image or PDF. The browser can render those two inline. */
  canPreview(att: Attachment): boolean {
    return (
      att.scanState === 'clean' &&
      (att.mime.startsWith('image/') || att.mime === 'application/pdf')
    );
  }

  /** Open the viewer at this file. The URL request comes first, so a quarantined or
   *  removed file shows its toast instead of the viewer.
   *
   * Mobile browsers such as Android Chrome cannot render a PDF in an iframe, so the PDF goes to the
   * system viewer instead.
   */
  openPreview(att: Attachment): void {
    if (this.previewLoadingId()) return;
    const pdfInViewer = !this.coarsePointer();
    this.previewLoadingId.set(att.id);
    this.api.attachmentUrl(att.id).subscribe({
      next: (signed) => {
        this.previewLoadingId.set(null);
        const url = inlineUrl(signed.url);
        if (att.mime === 'application/pdf' && !pdfInViewer) {
          this.openUrl(url);
          return;
        }
        this.pdfInViewer.set(pdfInViewer);
        const index = this.viewable().findIndex((a) => a.id === att.id);
        if (index < 0) return;
        this.previewUrls.set(new Map([[att.id, url]]));
        this.viewerIndex.set(index);
        this.viewerOpen.set(true);
      },
      error: (err: { status?: number }) => {
        this.previewLoadingId.set(null);
        this.urlFailed(att, err.status);
      },
    });
  }

  /** The arrows moved the viewer: fetch the URL of the file it shows now. */
  onViewerIndex(index: number): void {
    this.viewerIndex.set(index);
    this.fetchViewerUrl();
  }

  closePreview(): void {
    this.viewerOpen.set(false);
    this.previewUrls.set(new Map());
    this.fetching.clear();
  }

  /** A failed request closes the viewer with the toast of a failed download. */
  private fetchViewerUrl(): void {
    const att = this.viewerFile();
    if (!att || this.previewUrls().has(att.id) || this.fetching.has(att.id)) return;
    this.fetching.add(att.id);
    this.api.attachmentUrl(att.id).subscribe({
      next: (signed) => {
        if (!this.fetching.delete(att.id)) return;
        this.previewUrls.update((urls) => new Map(urls).set(att.id, inlineUrl(signed.url)));
      },
      error: (err: { status?: number }) => {
        if (!this.fetching.delete(att.id)) return;
        this.closePreview();
        this.urlFailed(att, err.status);
      },
    });
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
        this.urlFailed(att, err.status);
      },
    });
  }

  /** 409: the scan found something, so the row is quarantined for good. 410: the link
   *  expired. Anything else: a generic error. */
  private urlFailed(att: Attachment, status?: number): void {
    if (status === 409) {
      this.attachments.update((list) =>
        list.map((a) => (a.id === att.id ? { ...a, scanState: 'quarantined' as ScanState } : a)),
      );
      this.toast.error(this.i18n.translate('applications.attachments.download.conflict'));
    } else if (status === 410) {
      this.toast.error(this.i18n.translate('applications.attachments.download.gone'));
    } else {
      this.toast.error(this.i18n.translate('applications.attachments.download.error'));
    }
  }

  remove(att: Attachment): void {
    if (!this.deleteAllowed() || this.removingId()) return;
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
    return matchesMedia(MEDIA.coarse);
  }
}
