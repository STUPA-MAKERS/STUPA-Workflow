import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';

/**
 * Tells the list of the page "Veranstaltungen" that the pane created, changed or deleted
 * an Event, so the list reads its rows again.
 */
@Injectable({ providedIn: 'root' })
export class EventsRefresh {
  private readonly source = new Subject<void>();
  readonly changed = this.source.asObservable();

  touch(): void {
    this.source.next();
  }
}
