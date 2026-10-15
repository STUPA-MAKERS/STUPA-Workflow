import type { IsoDateTime, PersonRef } from '@core/api/models';

/** The visibility of a message where a thread knows two (application comments). */
export type ChatVisibility = 'internal' | 'public';

/** The delivery state of a message. A message without a state counts as sent. */
export type ChatMessageState = 'sent' | 'sending' | 'failed';

/** A file on a message. The url streams through the API, never a presigned URL. */
export interface ChatAttachment {
  id: string;
  filename: string;
  mime: string;
  size: number;
  url: string;
}

/** One message of a thread. */
export interface ChatMessage {
  /** The server id, or a client id while the message is pending. */
  id: string;
  /** null: the applicant or the system, shown without an avatar. */
  author: PersonRef | null;
  /** Overrides the name, for example the Gremium in the applicant view. */
  authorLabel?: string | null;
  /** Markdown. */
  body: string;
  at: IsoDateTime;
  editedAt?: IsoDateTime | null;
  own: boolean;
  visibility?: ChatVisibility | null;
  attachments?: ChatAttachment[];
  state?: ChatMessageState;
}

/** A status change or another event: small text in the middle of the thread. */
export interface ChatEvent {
  id: string;
  at: IsoDateTime;
  text: string;
}

/** The `send` output. `visibility` is set only when the thread offers a choice. */
export interface ChatSend {
  body: string;
  visibility?: ChatVisibility;
  mentions?: string[];
}

/** The `edit` output. */
export interface ChatEdit {
  id: string;
  body: string;
}

/** The `delete` and `retry` outputs. */
export interface ChatRef {
  id: string;
}
