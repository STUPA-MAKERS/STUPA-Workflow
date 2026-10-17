import { Injectable, signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { Uuid } from '@core/api/models';

/**
 * The link between the list pane and the detail pane of `/tickets`, provided by the
 * list page.
 *
 * - `split`: the list and the detail sit side by side; the detail then shows its two
 *   columns, otherwise the tabs "Verlauf" and "Details".
 * - `changed$`: the detail changed a ticket (state, assignee, kind). The list loads
 *   again, so its groups and the rail count follow.
 */
@Injectable()
export class TicketsPageService {
  readonly split = signal(false);

  private readonly changes = new Subject<Uuid>();
  readonly changed$ = this.changes.asObservable();

  notify(id: Uuid): void {
    this.changes.next(id);
  }
}
