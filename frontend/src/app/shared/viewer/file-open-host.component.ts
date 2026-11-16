import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FileViewerComponent, type FileViewerItem, IconComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FileOpenService } from './file-open.service';

/**
 * The one file viewer of the download buttons (spec 001080), in the root of the app. The
 * kit puts it into the top layer, so it covers the rail, the heads and every sheet
 * (001079). The bar has the download button of the shown file.
 */
@Component({
  selector: 'app-file-open-host',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FileViewerComponent, IconComponent, TranslatePipe],
  template: `
    <app-file-viewer [items]="items()" [open]="!!files.shown()" (openChange)="$event || files.close()">
      @if (files.shown(); as f) {
        <a
          viewerActions
          class="fv__btn"
          [href]="f.downloadUrl"
          download
          [attr.aria-label]="'viewer.download' | t"
          [title]="'viewer.download' | t"
        >
          <app-icon name="download" [size]="20" />
        </a>
      }
    </app-file-viewer>
  `,
})
export class FileOpenHostComponent {
  protected readonly files = inject(FileOpenService);
  protected readonly items = computed<readonly FileViewerItem[]>(() => {
    const f = this.files.shown();
    return f ? [f.item] : [];
  });
}
