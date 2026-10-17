import { ChangeDetectionStrategy, Component, input, signal } from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';

/** The raster types that a browser shows inline and the download route previews. */
const THUMB_MIMES: ReadonlySet<string> = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
]);

/** A file shows as an image: a raster type, and the scan found it clean (absent: clean). */
export function isThumbImage(file: { mime: string; scanState?: string | null }): boolean {
  return THUMB_MIMES.has(file.mime) && (file.scanState ?? 'clean') === 'clean';
}

/** The inline preview of a download URL (`?inline=1`). An existing query keeps its place. */
export function inlineUrl(url: string): string {
  return `${url}${url.includes('?') ? '&' : '?'}inline=1`;
}

/**
 * A small image of an attachment: a chat file or a row of the attachments panel. The
 * image loads lazily. When it fails to load, the image icon takes its place.
 */
@Component({
  selector: 'app-image-thumb',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  host: { class: 'thumb', '[class.thumb--sm]': "size() === 'sm'" },
  template: `
    @if (failed()) {
      <app-icon class="thumb__icon" name="image" [size]="size() === 'sm' ? 17 : 24" />
    } @else {
      <img
        class="thumb__img"
        [src]="src()"
        [alt]="alt()"
        loading="lazy"
        decoding="async"
        (error)="failed.set(true)"
      />
    }
  `,
  styleUrl: './image-thumb.component.scss',
})
export class ImageThumbComponent {
  /** The URL of the image, already with `?inline=1`. */
  readonly src = input.required<string>();
  readonly alt = input('');
  /** `sm` fits a list row; `md` fits a chat bubble. */
  readonly size = input<'sm' | 'md'>('md');
  protected readonly failed = signal(false);
}
