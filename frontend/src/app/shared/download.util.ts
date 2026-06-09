/** Blob als Datei-Download im Browser auslösen (Excel-Export #2). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // URL erst nach dem Klick freigeben (Safari/Firefox-sicher).
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
