import { Injectable, signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { Uuid } from '@core/api/models';

/** Which pane changed an application. A pane ignores its own notices. */
export type ApplicationsPane = 'list' | 'detail';

/** An application changed: its state, its data, its archive flag, or it is gone. */
export interface ApplicationChange {
  id: Uuid;
  kind: 'updated' | 'deleted';
  source: ApplicationsPane;
}

/**
 * The link between the list pane and the detail pane of the applications page.
 *
 * The list page provides it, so it lives as long as the page and the routed detail in its
 * outlet finds it. The detail also works without it (a test, or a route without the list).
 *
 * - `split`: the list and the detail sit side by side. The detail then shows its sections
 *   in two columns; otherwise in tabs.
 * - `changes$`: a pane changed an application (a transition, an archive, a delete, an
 *   edit). The other pane loads it again, so both show the same state.
 */
@Injectable()
export class ApplicationsPageService {
  readonly split = signal(false);

  private readonly changes = new Subject<ApplicationChange>();
  readonly changes$ = this.changes.asObservable();

  notify(change: ApplicationChange): void {
    this.changes.next(change);
  }
}
