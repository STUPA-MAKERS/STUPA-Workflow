import { signal } from '@angular/core';
import type { Observable } from 'rxjs';
import type { TranslationKey } from '@core/i18n/translations';
import type { ChatMessage, ChatSend } from './chat.models';

/**
 * The toast of a failed send: a body over the limit of the server (413 or 422) and a
 * missing right (403) name their reason, every other error the `fallback` of the thread.
 */
export function sendErrorKey(err: unknown, fallback: TranslationKey): TranslationKey {
  const status = (err as { status?: unknown } | null)?.status;
  if (status === 413 || status === 422) return 'chat.error.tooLong';
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
        state: 'sending',
      },
    ]);
    this.run(id, req);
  }

  /** Send a failed message again. An unknown id does nothing. */
  retry(id: string): void {
    const req = this.requests.get(id);
    if (!req) return;
    this.setState(id, 'sending');
    this.run(id, req);
  }

  /** Remove a failed message from the thread. An unknown id does nothing. */
  discard(id: string): void {
    if (!this.requests.delete(id)) return;
    this.items.update((list) => list.filter((m) => m.id !== id));
  }

  /** Forget every pending message, for example when the thread changes. */
  clear(): void {
    this.requests.clear();
    this.items.set([]);
  }

  private run(id: string, req: ChatSend): void {
    this.post(req).subscribe({
      next: (result) => {
        // A cleared outbox (another thread) drops a late answer.
        if (!this.requests.delete(id)) return;
        this.items.update((list) => list.filter((m) => m.id !== id));
        this.delivered(result);
      },
      error: (err: unknown) => {
        if (!this.requests.has(id)) return;
        this.setState(id, 'failed');
        this.failed(err);
      },
    });
  }

  private setState(id: string, state: 'sending' | 'failed'): void {
    this.items.update((list) => list.map((m) => (m.id === id ? { ...m, state } : m)));
  }
}
