/**
 * The shared building blocks of the app (`@shared/ui`).
 *
 * The ui-kit (`@stupa-makers/ui-kit`) holds the generic controls and patterns: buttons,
 * fields, tables, dialogs, the list rows, the sheets, the empty states. These blocks are
 * specific to this app; they use its i18n, its API and its status model. Import them
 * from here:
 *
 *   import { ChatComponent, HistoryComponent } from '@shared/ui';
 *
 * Exception: code in the initial bundle (the shell, the layout, the command palette)
 * imports a block by its path, for example `@shared/ui/page-header/page-header.component`.
 * When the initial bundle imports this barrel, every block that a lazy page uses goes into
 * the initial bundle too.
 */
export { ChatComponent } from './chat/chat.component';
export { ChatDrafts } from './chat/chat-drafts';
export { chatPeople, type ChatPerson } from './chat/chat-mentions';
export { ChatOutbox, draftDropper, filesRefused, missingFiles, sendErrorKey } from './chat/chat-outbox';
export { CHAT_MAX_FILES, appendOnce, chatFileUrl, toChatAttachments, withScanStates } from './chat/chat.util';
export type {
  ChatAttachment,
  ChatEdit,
  ChatEvent,
  ChatMessage,
  ChatMessageState,
  ChatRef,
  ChatSend,
  ChatVisibility,
} from './chat/chat.models';
export { FabComponent } from './fab/fab.component';
export { PullRefreshDirective, rubberBand } from './pull-refresh/pull-refresh.directive';
export { HistoryComponent } from './history/history.component';
export { ImageThumbComponent, inlineUrl, isThumbImage } from './image-thumb/image-thumb.component';
export type { HistoryChange, HistoryEntry } from './history/history.component';
export { PageHeaderComponent } from './page-header/page-header.component';
export * from '../status-kind.util';
