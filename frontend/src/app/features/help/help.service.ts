import { Injectable, signal } from '@angular/core';
import type { TicketKind } from '@core/api/tickets.service';

/**
 * Opens and closes the dialog "Problem melden".
 *
 * The dialog lives once in the shell (a deferred block, so its code loads on the first
 * opening). The help menu of the rail, of the "Mehr" sheet and of the public header
 * opens it through here, so no caller needs a reference to the component.
 */
@Injectable({ providedIn: 'root' })
export class HelpService {
  private readonly _reportOpen = signal(false);
  /** True while the dialog shows. */
  readonly reportOpen = this._reportOpen.asReadonly();
  /** True after the first opening: the shell keeps the loaded dialog from then on. */
  private readonly _reportUsed = signal(false);
  readonly reportUsed = this._reportUsed.asReadonly();

  /** The kind the dialog starts with; `null` keeps the kind of the last draft. */
  private readonly _presetKind = signal<TicketKind | null>(null);
  readonly presetKind = this._presetKind.asReadonly();

  /**
   * Open the dialog. `kind` picks the kind, e.g. `barrier` from the accessibility
   * statement (spec 000497).
   */
  openReport(kind: TicketKind | null = null): void {
    this._presetKind.set(kind);
    this._reportUsed.set(true);
    this._reportOpen.set(true);
  }

  closeReport(): void {
    this._reportOpen.set(false);
  }
}
