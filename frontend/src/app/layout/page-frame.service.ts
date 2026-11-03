import { Injectable, signal } from '@angular/core';

/**
 * What the page and the frame around it tell the breadcrumbs: `crumbRoot` and
 * `crumbLabel`, see the fields. The fill of the page is `PageFrame.fill` of the kit.
 */
@Injectable({ providedIn: 'root' })
export class PageFrameService {
  /**
   * A parent path that a frame around the page already shows, for example `admin`
   * while the admin navigation stands beside the page. The breadcrumbs leave this
   * parent and every parent below it out. The frame sets it and must clear it when it
   * goes away.
   */
  readonly crumbRoot = signal<string | null>(null);

  /**
   * A label for the current crumb that only the page knows, for example the name of a
   * gremium that loads after the navigation. It applies only while the current crumb
   * has this `url`, so a stale label never shows on another page. The page sets it and
   * must clear it when it goes away.
   */
  readonly crumbLabel = signal<{ url: string; label: string } | null>(null);
}
