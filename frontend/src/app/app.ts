import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { FileOpenHostComponent } from '@shared/viewer/file-open-host.component';

/**
 * Root component. It holds the router outlet and the file viewer of the download buttons
 * (spec 001080). ShellComponent provides the layout.
 */
@Component({
  selector: 'app-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, FileOpenHostComponent],
  template: `<router-outlet /><app-file-open-host />`,
})
export class App {}
