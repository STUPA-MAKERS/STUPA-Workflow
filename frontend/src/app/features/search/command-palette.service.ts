import { Injectable, signal } from '@angular/core';
import { Observable, Subject } from 'rxjs';

/**
 * Opens and closes the global search palette.
 *
 * The palette lives once in the shell. Everything else that opens it (the search pill of
 * the start page, the "Mehr" sheet of the phone bar, the shortcut) goes through here, so
 * no caller needs a reference to the component.
 */
@Injectable({ providedIn: 'root' })
export class CommandPaletteService {
  private readonly _open = signal(false);
  private readonly opening = new Subject<void>();

  readonly isOpen = this._open.asReadonly();
  /** Fires synchronously each time the palette goes from closed to open. */
  readonly opened$: Observable<void> = this.opening.asObservable();

  open(): void {
    if (this._open()) return;
    this._open.set(true);
    this.opening.next();
  }

  close(): void {
    this._open.set(false);
  }

  toggle(): void {
    if (this._open()) this.close();
    else this.open();
  }
}
