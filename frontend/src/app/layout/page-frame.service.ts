import { Injectable, signal } from '@angular/core';

/**
 * What the page tells the frame around it.
 *
 * `fill`: the page fills the viewport and scrolls only inside its own panes (the
 * applications page with the list and the detail side by side). The frame then leaves
 * the footer out and keeps only a small gap at the bottom, so the page itself does not
 * scroll. The page sets it and must clear it when it goes away.
 *
 * `crumbRoot`: see the field.
 */
@Injectable({ providedIn: 'root' })
export class PageFrameService {
  readonly fill = signal(false);

  /**
   * A parent path that a frame around the page already shows, for example `admin`
   * while the admin navigation stands beside the page. The breadcrumbs leave this
   * parent out. The frame sets it and must clear it when it goes away.
   */
  readonly crumbRoot = signal<string | null>(null);
}
