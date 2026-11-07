import type { IsoDateTime, PersonRef, ScanState } from '@core/api/models';

/** The visibility of a message where a thread knows two (application comments). */
export type ChatVisibility = 'internal' | 'public';

/** The delivery state of a message. A message without a state counts as sent. */
export type ChatMessageState = 'sent' | 'sending' | 'failed';

/** A file on a message. The url streams through the API, never a presigned URL. */
export interface ChatAttachment {
  readonly id: string;
  readonly filename: string;
  readonly mime: string;
  readonly size: number;
  readonly url: string;
  /** Only a clean file is a link. Absent: clean. */
  readonly scanState?: ScanState;
  /** The send named the draft as missing (422): the server no longer has it. */
  readonly lost?: boolean;
}

/** One message of a thread. */
export interface ChatMessage {
  /** The server id, or a client id while the message is pending. */
  readonly id: string;
  /** null: the applicant or the system, shown without an avatar. */
  readonly author: PersonRef | null;
  /** Overrides the name, for example the Gremium in the applicant view. */
  readonly authorLabel?: string | null;
  /** Markdown. */
  readonly body: string;
  readonly at: IsoDateTime;
  readonly editedAt?: IsoDateTime | null;
  readonly own: boolean;
  /**
   * May the viewer edit and delete the message. Unset: only an own message. A
   * moderator (`application.manage` on application comments) also changes others.
   */
  readonly canEdit?: boolean;
  readonly visibility?: ChatVisibility | null;
  readonly attachments?: readonly ChatAttachment[];
  readonly state?: ChatMessageState;
  /** The people the message mentions: their "@Name" is marked in the text. */
  readonly mentions?: readonly PersonRef[];
}

/** A status change or another event: small text in the middle of the thread. */
export interface ChatEvent {
  readonly id: string;
  readonly at: IsoDateTime;
  readonly text: string;
}

/** The `send` output. `visibility` is set only when the thread offers a choice. */
export interface ChatSend {
  /** May be '' when the message has files. */
  readonly body: string;
  visibility?: ChatVisibility;
  /** The ids of the people the text names as "@Name"; set only when it names someone. */
  readonly mentions?: string[];
  /** The draft ids of the composer files; set only when the composer holds files. */
  readonly attachmentIds?: string[];
  /** The draft token of those files. */
  readonly draftToken?: string | null;
  /** The composer files, for the pending bubble of `ChatOutbox`. */
  readonly files?: readonly ChatAttachment[];
}

/**
 * The `edit` output. The edit closes when it goes out; a consumer whose request fails
 * calls `restore`, which opens the edit again with the new text.
 */
export interface ChatEdit {
  readonly id: string;
  readonly body: string;
  /** The ids of the people the new text names as "@Name"; unset where the chat has no list. */
  readonly mentions?: string[];
  readonly restore?: () => void;
}

/** The `delete` and `retry` outputs. */
export interface ChatRef {
  readonly id: string;
}
