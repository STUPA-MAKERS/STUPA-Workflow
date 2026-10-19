/**
 * Copy a text to the clipboard. Resolves `true` when it worked and `false` when the
 * browser has no clipboard (an insecure origin) or refused the write, so the caller can
 * toast the result ("Link kopiert" or "Link konnte nicht kopiert werden").
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  const clip = typeof navigator === 'undefined' ? undefined : navigator.clipboard;
  if (!clip) return false;
  try {
    await clip.writeText(text);
    return true;
  } catch {
    return false;
  }
}
