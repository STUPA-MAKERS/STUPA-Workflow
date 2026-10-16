import type { IsoDateTime, PersonRef, ScanState } from '@core/api/models';

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
  /** Only a clean file is a link. Absent: clean. */
  scanState?: ScanState;
  /** The send named the draft as missing (422): the server no longer has it. */
  lost?: boolean;
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
  /**
   * May the viewer edit and delete the message. Unset: only an own message. A
   * moderator (`application.manage` on application comments) also changes others.
   */
  canEdit?: boolean;
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
  /** May be '' when the message has files. */
  body: string;
  visibility?: ChatVisibility;
  mentions?: string[];
  /** The draft ids of the composer files; set only when the composer holds files. */
  attachmentIds?: string[];
  /** The draft token of those files. */
  draftToken?: string | null;
  /** The composer files, for the pending bubble of `ChatOutbox`. */
  files?: ChatAttachment[];
}

/**
 * The `edit` output. The edit closes when it goes out; a consumer whose request fails
 * calls `restore`, which opens the edit again with the new text.
 */
export interface ChatEdit {
  id: string;
  body: string;
  restore?: () => void;
}

/** The `delete` and `retry` outputs. */
export interface ChatRef {
  id: string;
}
