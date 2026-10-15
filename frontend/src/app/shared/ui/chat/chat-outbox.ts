import { signal } from '@angular/core';
import type { Observable } from 'rxjs';
import type { ChatMessage, ChatSend } from './chat.models';

/**
 * The optimistic send of a thread. A sent message shows at once as "wird gesendet …".
 * On success it leaves the outbox and `delivered` gets the server answer, which the
 * consumer puts into its list. On an error it stays as "Nicht gesendet" until `retry`.
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
      error: () => this.setState(id, 'failed'),
    });
  }

  private setState(id: string, state: 'sending' | 'failed'): void {
    this.items.update((list) => list.map((m) => (m.id === id ? { ...m, state } : m)));
  }
}
