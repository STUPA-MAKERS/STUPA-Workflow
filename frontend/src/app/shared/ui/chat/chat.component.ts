import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { MEDIA, mediaQuery } from '@stupa-makers/ui-kit';
import {
  CHAT_FILES,
  ChatViewComponent,
  type ChatEdit as ViewEdit,
  type ChatFiles,
  type ChatMessage as ViewMessage,
  type ChatSend as ViewSend,
  type ChatUploadError,
  type ChatVisibilityOption,
} from '@stupa-makers/ui-kit/views/chat';
import { API_BASE_URL } from '@core/api/api.config';
import type { PersonRef } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { UPLOAD_ACCEPT } from '../../../features/apply/apply.util';
import { DRAFT_FILES_PERSIST, DraftAttachmentsService } from '../../../features/apply/draft-attachments.service';
import { ChatDrafts } from './chat-drafts';
import type { ChatPerson } from './chat-mentions';
import type {
  ChatEdit,
  ChatEvent,
  ChatMessage,
  ChatRef,
  ChatSend,
  ChatVisibility,
  ChatVisibilityGuard,
} from './chat.models';
import { chatFileUrl } from './chat.util';

export { SCAN_BACKOFF, CHAT_MAX_LENGTH } from '@stupa-makers/ui-kit/views/chat';

/** The chat reason of a refused upload, from the reason key of `DraftAttachmentsService`. */
export function chatUploadError(reason: TranslationKey): ChatUploadError {
  if (reason === 'apply.files.error.type') return 'type';
  if (reason === 'apply.files.error.tooLarge') return 'tooLarge';
  return 'other';
}

/**
 * The port `CHAT_FILES` of the kit chat over the drafts of the app (`POST /apply/attachments`).
 * `page` is the page's `ChatDrafts` when the chat holds them: a layout switch that re-creates the
 * chat keeps the files. Without it, the files belong to this chat and go with it.
 */
export function chatFilesPort(drafts: DraftAttachmentsService, page: ChatDrafts | null, apiBase: string): ChatFiles {
  const own: { key: string | null } = { key: null };
  const thread = page ?? own;
  return {
    files: drafts.files,
    pending: computed(() => drafts.pending().map((p) => ({ key: String(p.key), filename: p.filename }))),
    busy: drafts.busy,
    maxFileBytes: computed(() => drafts.limits().maxFileBytes),
    accept: UPLOAD_ACCEPT,
    usable: () => drafts.usable(),
    upload: async (files) => {
      const { failed } = await drafts.upload(files);
      return { failed: failed.map((f) => ({ filename: f.filename, reason: chatUploadError(f.reason) })) };
    },
    remove: (id) => drafts.remove(id),
    clear: () => drafts.clear(),
    discard: () => drafts.discard(),
    fileUrl: (id) => chatFileUrl(apiBase, id),
    threadKey: () => thread.key,
    setThreadKey: (key) => {
      // eslint-disable-next-line functional/immutable-data -- the thread key of the page's drafts
      thread.key = key;
    },
    release: () => {
      if (page) page.release();
      else void drafts.discard();
    },
  };
}

/**
 * The one chat of the app: application comments, the applicant status sheet, ticket notes and
 * card activity. It is the chat view of the kit (§ui-kit:002276); this component maps the app
 * models to the view models, gives the view the drafts of the app as `CHAT_FILES`, and maps the
 * outputs back (the draft token joins `send`).
 */
@Component({
  selector: 'app-chat',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ChatViewComponent],
  providers: [
    { provide: DRAFT_FILES_PERSIST, useValue: false },
    {
      provide: DraftAttachmentsService,
      useFactory: () => inject(ChatDrafts, { optional: true })?.claim() ?? new DraftAttachmentsService(),
    },
    {
      provide: CHAT_FILES,
      useFactory: () => {
        const drafts = inject(DraftAttachmentsService);
        const page = inject(ChatDrafts, { optional: true });
        return chatFilesPort(drafts, page?.holds(drafts) ? page : null, inject(API_BASE_URL));
      },
    },
  ],
  styleUrl: './chat.component.scss',
  host: { '[class.chat--phone]': 'phone()' },
  template: `<app-chat-view
    [messages]="viewMessages()"
    [events]="events()"
    [canPost]="canPost()"
    [loading]="loading()"
    [visibilities]="visibilities()"
    [guardVisibility]="visibilityGuard() !== null"
    [draftKey]="draftKey()"
    [placeholder]="placeholderText()"
    [canAttach]="canAttach()"
    [mentionables]="people()"
    [publicMentions]="publicMentions()"
    (send)="onSend($event)"
    (edit)="onEdit($event)"
    (delete)="delete.emit($event)"
    (retry)="retry.emit($event)"
    (discard)="discard.emit($event)"
    (refresh)="refresh.emit()"
  />`,
})
export class ChatComponent {
  private readonly i18n = inject(I18nService);
  private readonly drafts = inject(DraftAttachmentsService);

  readonly messages = input<readonly ChatMessage[]>([]);
  readonly events = input<readonly ChatEvent[]>([]);
  readonly canPost = input(true);
  /** The messages are on their way: the log shows placeholder bubbles. */
  readonly loading = input(false);
  /** The visibilities the composer offers. Empty: no toggle. */
  readonly visibilityOptions = input<readonly ChatVisibility[]>([]);
  /** Null: the plain switch. Set: the options name their readers (001691). */
  readonly visibilityGuard = input<ChatVisibilityGuard | null>(null);
  /** Names the thread in the browser storage (draft, last seen). */
  readonly draftKey = input.required<string>();
  readonly placeholder = input<TranslationKey>('chat.placeholder');
  /** Show the paperclip: the composer takes files. */
  readonly canAttach = input(false);
  /** The people who can read the thread: "@" lists them. Empty: no list. */
  readonly mentionables = input<readonly ChatPerson[]>([]);
  /** False: only an internal message mentions, because the other side reads a public one. */
  readonly publicMentions = input(true);

  readonly send = output<ChatSend>();
  readonly edit = output<ChatEdit>();
  readonly delete = output<ChatRef>();
  readonly retry = output<ChatRef>();
  /** A failed message leaves the thread: "Verwerfen", or "Bearbeiten" back into the composer. */
  readonly discard = output<ChatRef>();
  /** Read the thread again: a file of a sent message is still in the scan. */
  readonly refresh = output<void>();

  protected readonly phone = mediaQuery(MEDIA.phone);

  protected readonly viewMessages = computed<readonly ViewMessage[]>(() =>
    this.messages().map((m) => this.toView(m)),
  );

  protected readonly visibilities = computed<readonly ChatVisibilityOption[]>(() => {
    const labels = this.visibilityGuard()?.labels;
    return this.visibilityOptions().map((v) => ({
      value: v,
      label: this.i18n.translate(labels?.[v] ?? (v === 'internal' ? 'chat.internal' : 'chat.public')),
    }));
  });

  protected readonly placeholderText = computed(() => this.i18n.translate(this.placeholder()));

  protected readonly people = computed(() =>
    this.mentionables().map((p) => ({ name: p.displayName, principalId: p.principalId })),
  );

  private toView(m: ChatMessage): ViewMessage {
    const { attachments, author, mentions, visibility, ...rest } = m;
    return {
      ...rest,
      author: author ? this.person(author) : null,
      ...(visibility === undefined ? {} : { visibility }),
      ...(attachments ? { files: attachments } : {}),
      ...(mentions ? { mentions: mentions.map((p) => this.person(p)) } : {}),
    };
  }

  /** A person of the app as the kit names it; a deleted account is "Gelöschte Person". */
  private person(p: PersonRef): { name: string; principalId: string | null } {
    return { name: p.displayName ?? this.i18n.translate('chat.deletedPerson'), principalId: p.principalId };
  }

  protected onSend(req: ViewSend): void {
    const { fileIds, files, visibility, mentions, body } = req;
    this.send.emit({
      body,
      ...(visibility ? { visibility: visibility as ChatVisibility } : {}),
      ...(mentions ? { mentions: [...mentions] } : {}),
      ...(fileIds ? { attachmentIds: [...fileIds], draftToken: this.drafts.token() } : {}),
      ...(files ? { files } : {}),
    });
  }

  protected onEdit(req: ViewEdit): void {
    const { mentions, ...rest } = req;
    this.edit.emit({ ...rest, ...(mentions ? { mentions: [...mentions] } : {}) });
  }
}
