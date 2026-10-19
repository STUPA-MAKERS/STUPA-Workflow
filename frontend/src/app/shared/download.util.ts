import type { WritableSignal } from '@angular/core';
import type { Observable } from 'rxjs';
import { downloadBlob } from '@stupa-makers/ui-kit';

/**
 * The export flow of a list page: fetch a file, download it, and keep the busy flag of the
 * button. A second click while `busy` is set does nothing, so `request` is a factory: the
 * page builds its query only for a real export. A failure clears the flag and calls
 * `onError` (the page shows its toast).
 */
export function exportDownload(
  busy: WritableSignal<boolean>,
  request: () => Observable<Blob>,
  filename: string,
  onError: (err: unknown) => void,
): void {
  if (busy()) return;
  busy.set(true);
  request().subscribe({
    next: (blob) => {
      downloadBlob(blob, filename);
      busy.set(false);
    },
    error: (err: unknown) => {
      busy.set(false);
      onError(err);
    },
  });
}
