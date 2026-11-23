import { Injectable, signal } from '@angular/core';
import { Subject } from 'rxjs';
import type { Uuid } from '@core/api/models';
import type { TicketArea } from '@core/api/tickets.service';

/**
 * The link between the list pane and the detail pane of `/tickets`, provided by the
 * list page.
 *
 * - `split`: the list and the detail sit side by side; the detail then shows its two
 *   columns, otherwise the tabs "Verlauf" and "Details".
 * - `changed$`: the detail changed a ticket (state, assignee, kind). The list loads
 *   again, so its groups and the rail count follow.
 * - `areas`: every Bereich, read once by the list page; null until the read ends. The
 *   detail takes the names, the Kategorien and the targets of a move from it.
 */
@Injectable()
export class TicketsPageService {
  readonly split = signal(false);
  readonly areas = signal<readonly TicketArea[] | null>(null);

  private readonly changes = new Subject<Uuid>();
  readonly changed$ = this.changes.asObservable();

  notify(id: Uuid): void {
    this.changes.next(id);
  }
}
