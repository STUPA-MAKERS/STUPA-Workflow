import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent } from '@stupa-makers/ui-kit';

/**
 * The detail pane of `/admin` before an admin page is open: the empty sheet of every
 * list/detail page ("Keine Seite geöffnet", spec 000665). Only the side-by-side layout
 * shows it; one pane at a time, the list of Verwaltung fills the screen.
 */
@Component({
  selector: 'app-admin-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DetailNoneComponent],
  template: `<app-detail-none icon="shield" [heading]="'admin.home.none' | t" />`,
  styles: `
    @use 'detail-none-host' as dnh;
    :host {
      @include dnh.host;
    }
  `,
})
export class AdminHomeComponent {}
