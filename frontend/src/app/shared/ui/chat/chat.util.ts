import type { MessageAttachment, ScanState } from '@core/api/models';
import type { ChatAttachment } from './chat.models';

/** The download of a message file: streamed through the API (`base` = `API_BASE_URL`). */
export function chatFileUrl(base: string, id: string): string {
  return `${base}/attachments/${id}/download`;
}

/** The files of a message on the wire, as the chat shows them. */
export function toChatAttachments(
  base: string,
  files: readonly MessageAttachment[] | null | undefined,
): ChatAttachment[] {
  return (files ?? []).map((f) => ({
    id: f.id,
    filename: f.filename,
    mime: f.mime,
    size: f.size,
    scanState: f.scanState,
    url: chatFileUrl(base, f.id),
  }));
}

/** A message on the wire with files: a comment, a note or a card comment. */
interface WithFiles {
  readonly id: string;
  readonly attachments?: readonly MessageAttachment[] | null;
}

/**
 * The scan states of a background read (`refresh`), put into the list on screen. The
 * read can be older than a send, an edit or a delete that ended while it was in flight,
 * so the list keeps its own messages and only the scan state of their files changes.
 */
export function withScanStates<T extends WithFiles>(current: readonly T[], fresh: readonly WithFiles[]): T[] {
  const states = new Map<string, ScanState>(
    fresh.flatMap((m) => (m.attachments ?? []).map((f) => [f.id, f.scanState] as const)),
  );
  return current.map((m) => {
    const files = m.attachments ?? [];
    if (!files.some((f) => (states.get(f.id) ?? f.scanState) !== f.scanState)) return m;
    return { ...m, attachments: files.map((f) => ({ ...f, scanState: states.get(f.id) ?? f.scanState })) };
  });
}

/** A delivered message joins the list once; a message with its id already there is replaced. */
export function appendOnce<T extends { readonly id: string }>(list: readonly T[], item: T): T[] {
  return list.some((x) => x.id === item.id) ? list.map((x) => (x.id === item.id ? item : x)) : [...list, item];
}
