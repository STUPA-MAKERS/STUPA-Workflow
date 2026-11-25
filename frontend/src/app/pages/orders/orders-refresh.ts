import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';

/**
 * Tells the list of the page "Bestellungen" that the pane created, changed or deleted a
 * Bestellung, so the list reads its rows again.
 */
@Injectable({ providedIn: 'root' })
export class OrdersRefresh {
  private readonly source = new Subject<void>();
  readonly changed = this.source.asObservable();

  touch(): void {
    this.source.next();
  }
}
