import { Injectable, signal } from '@angular/core';
import { type FileViewerItem, fileViewerKind, MEDIA, mediaQuery } from '@stupa-makers/ui-kit';
import { inlineUrl } from '@shared/ui/image-thumb/image-thumb.component';

/**
 * A file that a download button gives. `url` is a same-origin API route that answers the
 * file as a download and, with `?inline=true`, as the sandboxed preview (spec 001083).
 * Never a URL from user input or file content.
 */
export interface OpenableFile {
  /** The name in the top bar of the viewer. The download keeps the name of the server. */
  readonly name: string;
  readonly url: string;
  /** The type, when the caller knows it. Else the viewer reads the extension of `name`. */
  readonly mime?: string;
  readonly kind?: FileViewerItem['kind'];
}

/** What the viewer shows now: the item and the plain download URL of the bar. */
export interface ShownFile {
  readonly item: FileViewerItem;
  readonly downloadUrl: string;
}

/**
 * Opens a file of a download button (spec 001080). A PDF or a raster image opens in the
 * file viewer of the kit, which `FileOpenHostComponent` in the root shows above
 * everything (001079). Every other type downloads as before. On a coarse pointer a PDF
 * opens its inline preview in a new tab, because a phone browser shows no PDF in a frame
 * (001081).
 */
@Injectable({ providedIn: 'root' })
export class FileOpenService {
  private readonly coarse = mediaQuery(MEDIA.coarse);
  private readonly shownFile = signal<ShownFile | null>(null);

  /** The file in the viewer; null while it is closed. */
  readonly shown = this.shownFile.asReadonly();

  /** The viewer can show the file: a PDF or a raster image. */
  canView(file: OpenableFile): boolean {
    return fileViewerKind(this.item(file, file.url)) !== 'other';
  }

  /**
   * A click on a download button or link. A click with a modifier or another button
   * keeps the default of the browser (a new tab, a download). Returns true when the
   * service handled the click.
   */
  click(event: MouseEvent, file: OpenableFile): boolean {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
      return false;
    }
    event.preventDefault();
    this.open(file);
    return true;
  }

  /** Open a viewable file in the viewer, else download it. */
  open(file: OpenableFile): void {
    if (!this.canView(file)) {
      this.download(file.url);
      return;
    }
    const preview = inlineUrl(file.url);
    const item = this.item(file, preview);
    if (fileViewerKind(item) === 'pdf' && this.coarse()) {
      this.newTab(preview);
      return;
    }
    this.shownFile.set({ item, downloadUrl: file.url });
  }

  close(): void {
    this.shownFile.set(null);
  }

  private item(file: OpenableFile, url: string): FileViewerItem {
    return { name: file.name, url, mime: file.mime, kind: file.kind };
  }

  /** A link click: the server names the file with its `Content-Disposition`. */
  private download(url: string): void {
    clickLink({ href: url, download: '', rel: 'noopener' });
  }

  private newTab(url: string): void {
    clickLink({ href: url, target: '_blank', rel: 'noopener' });
  }
}

/** Click a link that is not in the page. A popup blocker lets it pass after a user click. */
function clickLink(attrs: Readonly<Record<string, string>>): void {
  const a = document.createElement('a');
  Object.entries(attrs).forEach(([name, value]) => a.setAttribute(name, value));
  document.body.appendChild(a);
  a.click();
  a.remove();
}
