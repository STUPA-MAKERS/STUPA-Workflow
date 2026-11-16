import { ChangeDetectionStrategy, Component, computed, model } from '@angular/core';
import { FileViewerComponent, type FileViewerItem, IconComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** An embedded PDF to show: its file name and its same-origin URL. */
export interface ShownDocument {
  readonly name: string;
  /** `/api/media/documents/<id>` or the public route; never a URL from user input. */
  readonly url: string;
}

/**
 * The overlay of an embedded PDF (spec 000863): the file viewer of the kit with the
 * framable preview (`?inline=true`) and a download button. `doc` null closes it.
 */
@Component({
  selector: 'app-document-viewer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FileViewerComponent, IconComponent, TranslatePipe],
  template: `
    <app-file-viewer [items]="items()" [open]="!!doc()" (openChange)="$event || doc.set(null)">
      @if (doc(); as d) {
        <a
          viewerActions
          class="fv__btn"
          [href]="d.url"
          download
          [attr.aria-label]="'markdown.document.download' | t"
          [title]="'markdown.document.download' | t"
        >
          <app-icon name="download" [size]="20" />
        </a>
      }
    </app-file-viewer>
  `,
})
export class DocumentViewerComponent {
  /** The shown PDF; two-way bindable, null when closed. */
  readonly doc = model<ShownDocument | null>(null);
  protected readonly items = computed<readonly FileViewerItem[]>(() => {
    const d = this.doc();
    return d ? [{ name: d.name, url: `${d.url}?inline=true`, kind: 'pdf' }] : [];
  });
}
