import { DestroyRef, Directive, ElementRef, Injector, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { from, of } from 'rxjs';
import { catchError, concatMap, finalize, map } from 'rxjs/operators';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { ToastService } from '@stupa-makers/ui-kit';
import { MEDIA_IMAGE_TYPES, MediaApiService, markdownImage } from './media-api.service';

/** The file name without its extension, as the alt text of the image. */
function altOf(file: File): string {
  return file.name.replace(/\.[^.]*$/, '');
}

/** The i18n key of an upload error, from the HTTP status of the problem response. */
export function imageUploadErrorKey(status?: number): TranslationKey {
  switch (status) {
    case 413:
      return 'markdown.image.error.tooLarge';
    case 415:
      return 'markdown.image.error.type';
    case 429:
      return 'markdown.image.error.rate';
    case 503:
      return 'markdown.image.error.storage';
    default:
      return 'markdown.image.error.upload';
  }
}

let placeholderSeq = 0;

/**
 * Image upload for a Markdown `<textarea>`. A paste or a drop of image files (PNG, JPEG,
 * GIF, WebP) uploads each file to `POST /api/media/images` and inserts
 * `![name](/api/media/images/<id>)` at the caret. A placeholder holds the place while the
 * upload runs. On an error the placeholder goes away and a toast names the cause.
 * `pick()` opens a file dialog for an explicit "insert image" button.
 *
 * The directive writes the textarea value and then dispatches an `input` event, so
 * `ngModel` and `(input)` bindings get the new text. Files upload one after the other,
 * so parallel requests do not trip the rate limit (429). Use it only where the user is a
 * principal, because the server refuses other sessions.
 */
@Directive({
  selector: 'textarea[appMarkdownImageUpload]',
  standalone: true,
  exportAs: 'mdImageUpload',
  host: {
    '(paste)': 'onPaste($event)',
    '(dragover)': 'onDragOver($event)',
    '(drop)': 'onDrop($event)',
  },
})
export class MarkdownImageUploadDirective {
  private readonly el = inject<ElementRef<HTMLTextAreaElement>>(ElementRef);
  /**
   * The service resolves on the first upload, so a host without HttpClient (a test of the
   * host) does not need it.
   */
  private readonly injector = inject(Injector);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);
  private readonly destroyRef = inject(DestroyRef);

  /** The number of uploads that still run. */
  readonly uploading = signal(0);

  /** Open the file dialog of the browser for image files. */
  pick(): void {
    if (this.locked()) return;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = MEDIA_IMAGE_TYPES.join(',');
    input.multiple = true;
    input.addEventListener('change', () => this.upload(Array.from(input.files ?? [])));
    input.click();
  }

  onPaste(event: ClipboardEvent): void {
    const files = imagesOf(event.clipboardData?.files);
    if (!files.length || this.locked()) return;
    event.preventDefault();
    this.upload(files);
  }

  onDragOver(event: DragEvent): void {
    if (Array.from(event.dataTransfer?.items ?? []).some((i) => isImageType(i.type))) {
      event.preventDefault();
    }
  }

  onDrop(event: DragEvent): void {
    const files = imagesOf(event.dataTransfer?.files);
    if (!files.length || this.locked()) return;
    event.preventDefault();
    this.upload(files);
  }

  /** Upload the image files and insert a reference for each. Other files are ignored. */
  upload(files: readonly File[]): void {
    const images = files.filter((f) => isImageType(f.type));
    if (!images.length || this.locked()) return;
    const slots = images.map((file) => ({ file, mark: this.insertPlaceholder() }));
    this.uploading.update((n) => n + slots.length);
    const media = this.injector.get(MediaApiService);
    from(slots)
      .pipe(
        concatMap((slot) =>
          media.uploadImage(slot.file).pipe(
            map((image) => markdownImage(altOf(slot.file), image.id)),
            catchError((err: { status?: number } | null) => {
              this.toast.error(this.i18n.translate(imageUploadErrorKey(err?.status)));
              return of('');
            }),
            map((text) => this.replace(slot.mark, text)),
            finalize(() => this.uploading.update((n) => n - 1)),
          ),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe();
  }

  /** A read-only or disabled textarea takes no image: the text must not change. */
  private locked(): boolean {
    const area = this.el.nativeElement;
    return area.readOnly || area.disabled;
  }

  /** Put a unique placeholder over the selection. It sits on a line of its own. */
  private insertPlaceholder(): string {
    const area = this.el.nativeElement;
    const mark = `![${this.i18n.translate('markdown.image.uploading')} #${++placeholderSeq}]()`;
    const value = area.value;
    const start = area.selectionStart ?? value.length;
    const end = area.selectionEnd ?? start;
    const before = value.slice(0, start);
    const after = value.slice(end);
    const lead = before && !before.endsWith('\n') ? '\n' : '';
    const tail = after.startsWith('\n') ? '' : '\n';
    const text = `${lead}${mark}${tail}`;
    this.write(before + text + after, before.length + text.length);
    return mark;
  }

  /**
   * Replace the placeholder. When the placeholder is gone, the result is dropped: the user
   * deleted it or the textarea now shows another text, and the image must not go into
   * that text.
   */
  private replace(mark: string, text: string): void {
    const area = this.el.nativeElement;
    const value = area.value;
    const at = value.indexOf(mark);
    if (at < 0) return;
    let end = at + mark.length;
    if (!text && value[end] === '\n') end++;
    this.write(value.slice(0, at) + text + value.slice(end), at + text.length);
  }

  private write(value: string, caret: number | null): void {
    const area = this.el.nativeElement;
    area.value = value;
    if (caret !== null && document.activeElement === area) {
      area.setSelectionRange(caret, caret);
    }
    area.dispatchEvent(new Event('input', { bubbles: true }));
  }
}

function isImageType(type: string): boolean {
  return MEDIA_IMAGE_TYPES.includes(type);
}

function imagesOf(list: FileList | null | undefined): File[] {
  return Array.from(list ?? []).filter((f) => isImageType(f.type));
}
