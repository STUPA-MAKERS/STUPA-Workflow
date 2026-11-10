import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent } from '@stupa-makers/ui-kit';

/**
 * The detail pane of `/my-applications` before a row is open. Only the side-by-side layout
 * shows it; one pane at a time, the list fills the screen.
 */
@Component({
  selector: 'app-my-applications-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DetailNoneComponent],
  template: `<app-detail-none icon="file" [heading]="'applications.list.none' | t" />`,
  styles: `
    @use 'detail-none-host' as dnh;
    :host {
      @include dnh.host;
    }
  `,
})
export class MyApplicationsNoneComponent {}
