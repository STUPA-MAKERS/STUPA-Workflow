import type { WritableSignal } from '@angular/core';
import type { Observable } from 'rxjs';

/** Trigger a file download of a blob in the browser. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke the URL only after the click, which is safe for Safari and Firefox.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

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
