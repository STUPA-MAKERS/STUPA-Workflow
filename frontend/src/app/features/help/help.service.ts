import { Injectable, signal } from '@angular/core';

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

  openReport(): void {
    this._reportUsed.set(true);
    this._reportOpen.set(true);
  }

  closeReport(): void {
    this._reportOpen.set(false);
  }
}
