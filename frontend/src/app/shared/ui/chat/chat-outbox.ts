import { signal } from '@angular/core';
import type { Observable } from 'rxjs';
import type { ApiClient } from '@core/api/api-client.service';
import type { TranslationKey } from '@core/i18n/translations';
import type { ChatMessage, ChatSend } from './chat.models';

/**
 * The `dropDrafts` of a thread: delete the drafts of a discarded message (best effort,
 * the hourly purge takes what stays).
 */
export function draftDropper(
  api: Pick<ApiClient, 'deleteDraftAttachment'>,
): (ids: string[], token: string) => void {
  return (ids, token) => {
    for (const id of ids) api.deleteDraftAttachment(id, token).subscribe({ error: () => undefined });
  };
}

const FILES_MISSING = 'draft_attachments_missing';
/** The error of a retry that has nothing left to send. */
const FILES_GONE = { status: 422, error: { code: FILES_MISSING, errors: [] } };

/** The draft ids a 422 `draft_attachments_missing` names (`attachmentIds.<id>`), else null. */
export function missingFiles(err: unknown): Set<string> | null {
  const e = err as { status?: unknown; error?: { code?: unknown; errors?: unknown } } | null;
  if (e?.status !== 422 || e.error?.code !== FILES_MISSING) return null;
  const errors = Array.isArray(e.error.errors) ? (e.error.errors as { field?: unknown }[]) : [];
  const ids = errors
    .map((x) => (typeof x?.field === 'string' ? /^attachmentIds\.(.+)$/.exec(x.field)?.[1] : undefined))
    .filter((id): id is string => !!id);
  return new Set(ids);
}

/** The problem codes of a message whose thread takes no files any more (anonymized). */
const FILES_REFUSED: ReadonlySet<unknown> = new Set(['application_anonymized', 'ticket_anonymized']);

/** A 422 that refuses every file of the message: the application or the ticket is anonymized. */
export function filesRefused(err: unknown): boolean {
  const e = err as { status?: unknown; error?: { code?: unknown } } | null;
  return e?.status === 422 && FILES_REFUSED.has(e.error?.code);
}

/**
 * A body over the limit of the server: a 413, or a 422 whose errors name the field
 * `body` with a length message ("String should have at most 10000 characters").
 */
function bodyTooLong(err: unknown): boolean {
  const e = err as { status?: unknown; error?: { errors?: unknown } } | null;
  if (e?.status === 413) return true;
  if (e?.status !== 422 || !Array.isArray(e.error?.errors)) return false;
  return (e.error.errors as { field?: unknown; msg?: unknown }[]).some(
    (x) => typeof x?.field === 'string' && /(^|\.)body$/.test(x.field) && typeof x.msg === 'string' && /at most/i.test(x.msg),
  );
}

/** A 422 `mention_not_member`: the text names someone who cannot read the thread. */
export function mentionRefused(err: unknown): boolean {
  const e = err as { status?: unknown; error?: { code?: unknown } } | null;
  return e?.status === 422 && e.error?.code === 'mention_not_member';
}

/**
 * The toast of a failed send: a lost file names itself, a body over the limit of the
 * server, a mention of someone outside the thread and a missing right (403) name their
 * reason, every other error (another 422 too) the `fallback` of the thread.
 */
export function sendErrorKey(err: unknown, fallback: TranslationKey): TranslationKey {
  const status = (err as { status?: unknown } | null)?.status;
  if (missingFiles(err)) return 'chat.error.filesMissing';
  if (filesRefused(err)) return 'chat.error.filesRefused';
  if (bodyTooLong(err)) return 'chat.error.tooLong';
  if (mentionRefused(err)) return 'chat.error.mention';
  if (status === 403) return 'chat.error.forbidden';
  return fallback;
}

/**
 * The optimistic send of a thread. A sent message shows at once as "wird gesendet …".
 * On success it leaves the outbox and `delivered` gets the server answer, which the
 * consumer puts into its list. On an error it stays as "Nicht gesendet" until `retry` or
 * `discard`, and `failed` gets the error, so that the consumer can say why (a toast).
 *
 * The consumer passes `[...serverMessages, ...outbox.messages()]` to `app-chat`.
 *
 * Files: the pending bubble shows `req.files`. A 422 `draft_attachments_missing` marks
 * the named files lost, and `retry` sends the others with the same token. A message
 * with no text and no file left is not sent again: it stays failed and `failed` gets
 * the missing-files error again; "Bearbeiten" then offers its way out. `discard`
 * deletes the drafts of the message through `dropDrafts` (best effort). A 422
 * `application_anonymized` or `ticket_anonymized` refuses every file: all of them count
 * as lost, so a retry sends the text alone and "Bearbeiten" comes back.
 */
export class ChatOutbox<T> {
  private readonly items = signal<ChatMessage[]>([]);
  /** The pending and failed messages, in the order they were sent. */
  readonly messages = this.items.asReadonly();
  private readonly requests = new Map<string, ChatSend>();
  private seq = 0;

  constructor(
    private readonly post: (req: ChatSend) => Observable<T>,
    private readonly delivered: (result: T) => void,
    private readonly failed: (err: unknown) => void = () => undefined,
    private readonly dropDrafts: (ids: string[], token: string) => void = () => undefined,
  ) {}

  send(req: ChatSend): void {
    const id = `pending-${++this.seq}`;
    this.requests.set(id, req);
    this.items.update((list) => [
      ...list,
      {
        id,
        author: null,
        body: req.body,
        at: new Date().toISOString(),
        own: true,
        visibility: req.visibility ?? null,
        ...(req.files?.length ? { attachments: req.files } : {}),
        state: 'sending',
      },
    ]);
    this.run(id, req);
  }

  /** Send a failed message again. An unknown id does nothing. */
  retry(id: string): void {
    const req = this.requests.get(id);
    if (!req) return;
    if (!req.body.trim() && !req.attachmentIds?.length) {
      this.failed(FILES_GONE);
      return;
    }
    this.setState(id, 'sending');
    this.run(id, req);
  }

  /** Remove a failed message from the thread. An unknown id does nothing. */
  discard(id: string): void {
    const req = this.requests.get(id);
    if (!req) return;
    this.requests.delete(id);
    if (req.attachmentIds?.length && req.draftToken) this.dropDrafts(req.attachmentIds, req.draftToken);
    this.items.update((list) => list.filter((m) => m.id !== id));
  }

  /** Forget every pending message, for example when the thread changes. */
  clear(): void {
    this.requests.clear();
    this.items.set([]);
  }

  /**
   * A cleared outbox (another thread) drops a late answer. The server keeps refused drafts unbound,
   * so they go now, not at the hourly purge.
   */
  private run(id: string, req: ChatSend): void {
    this.post(req).subscribe({
      next: (result) => {
        if (!this.requests.delete(id)) return;
        this.items.update((list) => list.filter((m) => m.id !== id));
        this.delivered(result);
      },
      error: (err: unknown) => {
        if (!this.requests.has(id)) return;
        const refused = filesRefused(err);
        const lost = refused ? new Set(req.attachmentIds ?? []) : missingFiles(err);
        if (lost) this.markLost(id, req, lost);
        if (refused && lost?.size && req.draftToken) this.dropDrafts([...lost], req.draftToken);
        this.setState(id, 'failed');
        this.failed(err);
      },
    });
  }

  /** The server lost these files: the bubble marks them, a retry sends the others. */
  private markLost(id: string, req: ChatSend, lost: ReadonlySet<string>): void {
    const ids = (req.attachmentIds ?? []).filter((a) => !lost.has(a));
    this.requests.set(id, { ...req, attachmentIds: ids });
    this.items.update((list) =>
      list.map((m) =>
        m.id === id
          ? { ...m, attachments: m.attachments?.map((f) => (lost.has(f.id) ? { ...f, lost: true } : f)) }
          : m,
      ),
    );
  }

  private setState(id: string, state: 'sending' | 'failed'): void {
    this.items.update((list) => list.map((m) => (m.id === id ? { ...m, state } : m)));
  }
}
