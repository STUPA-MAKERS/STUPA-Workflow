import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { FileOpenHostComponent } from '@shared/viewer/file-open-host.component';
import { FileOpenService } from '@shared/viewer/file-open.service';

/**
 * Root component. It holds the router outlet and the file viewer of the download buttons
 * (spec 001080). ShellComponent provides the layout. The viewer loads with the first file
 * that a person opens, so its code stays out of the start bundle (spec 002003).
 */
@Component({
  selector: 'app-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, FileOpenHostComponent],
  template: `
    <router-outlet />
    @defer (when files.shown()) {
      <app-file-open-host />
    }
  `,
})
export class App {
  protected readonly files = inject(FileOpenService);
}
