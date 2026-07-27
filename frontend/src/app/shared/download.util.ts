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
