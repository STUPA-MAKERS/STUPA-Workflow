import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  Pipe,
  type PipeTransform,
  afterNextRender,
  afterRenderEffect,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  MEDIA,
  SegmentedComponent,
  ToastService,
  type SegmentedOption,
} from '@stupa-makers/ui-kit';
import { API_BASE_URL } from '@core/api/api.config';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { markdownToSafeHtml } from '@shared/markdown/markdown.util';
import { PressSelectDirective } from '@shared/press-select.directive';
import { mediaQuerySignal } from '../../../layout/media-query';
import { AvatarComponent } from '../avatar/avatar.component';
import { SideSheetComponent } from '../side-sheet/side-sheet.component';
import { scanStatus, type StatusView } from '../../status-kind.util';
import { StatusTextComponent } from '../status-text/status-text.component';
import { UPLOAD_ACCEPT, formatSize } from '../../../features/apply/apply.util';
import {
  DRAFT_FILES_PERSIST,
  DraftAttachmentsService,
  type DraftFile,
} from '../../../features/apply/draft-attachments.service';
import { ChatDrafts } from './chat-drafts';
import type {
  ChatAttachment,
  ChatEdit,
  ChatEvent,
  ChatMessage,
  ChatRef,
  ChatSend,
  ChatVisibility,
} from './chat.models';
import { CHAT_MAX_FILES, buildItems, chatFileUrl, dayKey, isPending, linkify, newCount } from './chat.util';

/** The log counts as "at the newest message" this close to its end, in px. */
const BOTTOM_SLACK = 24;
const DRAFT_PREFIX = 'ap.chat.draft.';
/** The longest body the server takes for a comment, a note or a card comment. */
export const CHAT_MAX_LENGTH = 10_000;
const SEEN_PREFIX = 'ap.chat.seen.';
/**
 * The waits between two reads of a thread while a file of a message is in the scan, in
 * ms: about 30 s in all. The ClamAV scan runs in the worker after the send.
 */
export const SCAN_BACKOFF: readonly number[] = [2_000, 4_000, 8_000, 16_000];

/** The extension of a pasted image without a name of its own. */
const PASTE_EXT: Readonly<Record<string, string>> = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/gif': 'gif',
  'image/webp': 'webp',
};

/** The chat text of a refused upload, from the reason of `DraftAttachmentsService`. */
export function chatUploadError(reason: TranslationKey): TranslationKey {
  if (reason === 'apply.files.error.type') return 'chat.error.fileType';
  if (reason === 'apply.files.error.tooLarge') return 'chat.error.fileTooLarge';
  return 'chat.error.upload';
}

/** The page's drafts, when the chat got them; else null. */
function heldDrafts(page: ChatDrafts | null, drafts: DraftAttachmentsService): ChatDrafts | null {
  return page?.holds(drafts) ? page : null;
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** A drag that carries files from the desktop, not a text selection. */
function isFileDrag(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files');
}

/** The body of a message as safe HTML: escaped Markdown, bare URLs as links. */
@Pipe({ name: 'chatBody', standalone: true })
export class ChatBodyPipe implements PipeTransform {
  private readonly sanitizer = inject(DomSanitizer);
  transform(body: string): SafeHtml {
    // `markdownToSafeHtml` escapes the whole input before it writes any tag, and
    // `linkify` only wraps escaped text, so the result holds no markup of the author.
    return this.sanitizer.bypassSecurityTrustHtml(linkify(markdownToSafeHtml(body)));
  }
}

function readStore(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStore(key: string, value: string | null): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // Private mode or blocked storage: the draft lives until the page closes.
  }
}

/**
 * The one chat of the app: application comments, the applicant status sheet, ticket
 * notes and card activity.
 *
 * - Own messages right in the accent, others left with the avatar. Messages of one person
 *   within 5 minutes form a group: one name, one avatar, the time under the last.
 * - Day separators instead of a date on every message; events small in the middle.
 * - "Intern" and "Öffentlich" show only where a thread holds both.
 * - Bare URLs become links; text and links wrap, nothing is shortened.
 * - The log opens at the newest message and follows new ones while it is at the end.
 *   Further up, a button "↓ N neue Nachrichten" appears. "N neue" marks where the viewer
 *   was last (per thread, in the browser).
 * - The composer grows to 6 lines. Enter sends on a desktop, Shift+Enter is a new line;
 *   on a phone Enter is a new line and only the button sends. The draft stays per thread.
 * - Optimistic send: the consumer passes pending messages (`state`), see `ChatOutbox`.
 *   A failed message offers "Erneut senden", "Bearbeiten" (its text back into the
 *   composer) and "Verwerfen".
 * - Own messages: edit and delete on hover or focus (desktop), a long press opens a
 *   bottom sheet (phone).
 * - Files (`canAttach`): the paperclip, a pasted image and a dropped file upload drafts through
 *   `POST /apply/attachments` (its own `DraftAttachmentsService`, never kept in
 *   `sessionStorage`). Up to 5 per message, each under the limit of the site config.
 *   The chips show the upload and the scan state and can leave before the send; the
 *   send carries the ids and the token and forgets them. On a message only a clean file
 *   is a link (streamed through the API); a file in the scan or in quarantine is not.
 *   A page that provides `ChatDrafts` keeps the files when a layout switch re-creates
 *   the chat. While a file of a sent message is in the scan, `refresh` asks the consumer to read
 *   the thread again (`SCAN_BACKOFF`), so the chip turns into a link without a reload.
 * - A paste with plain text (Word, a web page) stays text, even when the clipboard also
 *   holds a picture of it; a paste of files without plain text (a copied image, which
 *   comes with an HTML `<img>`) becomes files.
 */
@Component({
  selector: 'app-chat',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    AvatarComponent,
    ButtonComponent,
    ChatBodyPipe,
    DialogComponent,
    IconComponent,
    NgTemplateOutlet,
    PressSelectDirective,
    SegmentedComponent,
    SideSheetComponent,
    StatusTextComponent,
    TranslatePipe,
  ],
  providers: [
    { provide: DRAFT_FILES_PERSIST, useValue: false },
    {
      provide: DraftAttachmentsService,
      useFactory: () => inject(ChatDrafts, { optional: true })?.claim() ?? new DraftAttachmentsService(),
    },
  ],
  host: { '[class.chat--phone]': 'phone()' },
  templateUrl: './chat.component.html',
  styleUrl: './chat.component.scss',
})
export class ChatComponent {
  private readonly i18n = inject(I18nService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);
  private readonly drafts = inject(DraftAttachmentsService);
  /**
   * The page's drafts (`ChatDrafts`) when this chat holds them: a layout switch that
   * re-creates the chat keeps the files. Null: the files belong to this chat and go with it.
   */
  private readonly pageDrafts = heldDrafts(inject(ChatDrafts, { optional: true }), this.drafts);
  /** The thread whose files the drafts hold. */
  private readonly thread: { key: string | null } = this.pageDrafts ?? { key: null };
  private readonly toast = inject(ToastService);
  private readonly apiBase = inject(API_BASE_URL);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly messages = input<readonly ChatMessage[]>([]);
  readonly events = input<readonly ChatEvent[]>([]);
  readonly canPost = input(true);
  /** The visibilities the composer offers. Empty: no toggle. */
  readonly visibilityOptions = input<readonly ChatVisibility[]>([]);
  /** Names the thread in the browser storage (draft, last seen). */
  readonly draftKey = input.required<string>();
  readonly placeholder = input<TranslationKey>('chat.placeholder');
  /** Show the paperclip: the composer takes files. */
  readonly canAttach = input(false);

  readonly send = output<ChatSend>();
  readonly edit = output<ChatEdit>();
  readonly delete = output<ChatRef>();
  readonly retry = output<ChatRef>();
  /** A failed message leaves the thread: "Verwerfen", or "Bearbeiten" back into the composer. */
  readonly discard = output<ChatRef>();
  /** Read the thread again: a file of a sent message is still in the scan. */
  readonly refresh = output<void>();

  protected readonly phone = mediaQuerySignal(MEDIA.phone);
  private readonly coarse = mediaQuerySignal('(pointer: coarse)');
  /**
   * The long press opens the actions only on a phone with a touch screen. A narrow
   * window or a zoomed page with a mouse or a keyboard keeps the hover and focus actions.
   */
  protected readonly touchMenu = computed(() => this.phone() && this.coarse());
  private readonly log = viewChild.required<ElementRef<HTMLElement>>('log');
  private readonly composerInput = viewChild<ElementRef<HTMLTextAreaElement>>('composerInput');
  private readonly fileInput = viewChild<ElementRef<HTMLInputElement>>('fileInput');

  protected readonly accept = UPLOAD_ACCEPT;
  /** The uploaded files of the composer, oldest first. */
  protected readonly files = this.drafts.files;
  /** The files on their way up. */
  protected readonly uploads = this.drafts.pending;
  protected readonly uploading = this.drafts.busy;
  /** No room for another file. */
  protected readonly full = computed(() => this.files().length + this.uploads().length >= CHAT_MAX_FILES);

  protected readonly maxLength = CHAT_MAX_LENGTH;
  protected readonly draft = signal('');
  protected readonly visibility = signal<ChatVisibility | null>(null);
  protected readonly editingId = signal<string | null>(null);
  protected readonly editDraft = signal('');
  protected readonly deleting = signal<ChatMessage | null>(null);
  /** The message whose delete was confirmed, until it leaves `messages`. */
  private deletedId: string | null = null;
  /** The own message whose phone menu is open. */
  protected readonly menuFor = signal<ChatMessage | null>(null);

  /** The time of the newest message the viewer has seen, per thread. */
  private readonly seenAt = signal<string | null>(null);
  /** Where "N neue" stands: the last seen time when the thread opened. */
  private readonly markerAt = signal<string | null>(null);
  private markerSet = false;
  /** The log is at its end: new messages scroll into view. */
  private stick = true;
  protected readonly atBottom = signal(true);

  protected readonly segmentOptions = computed<SegmentedOption[]>(() =>
    this.visibilityOptions().map((v) => ({
      value: v,
      label: this.i18n.translate(v === 'internal' ? 'chat.internal' : 'chat.public'),
    })),
  );

  /** Mark visibilities only where both kinds exist in the thread. */
  private readonly marked = computed(() => {
    if (this.visibilityOptions().length > 1) return true;
    const kinds = new Set(this.messages().map((m) => m.visibility ?? null));
    return kinds.has('internal') && kinds.has('public');
  });

  protected readonly items = computed(() =>
    buildItems(this.messages(), this.events(), {
      marked: this.marked(),
      markerAt: this.markerAt(),
      dayLabel: (d) => this.dayLabel(d),
      name: (m) => this.authorName(m),
    }),
  );

  /** New messages below the visible part of the log. */
  protected readonly unread = computed(() =>
    this.atBottom() ? 0 : newCount(this.messages(), this.seenAt()),
  );

  /** The ids of the files of sent messages that are in the scan, sorted and joined. */
  private readonly scanning = computed(() => {
    const ids: string[] = [];
    for (const m of this.messages()) {
      if (isPending(m)) continue;
      for (const f of m.attachments ?? []) if (!f.lost && f.scanState === 'scanning') ids.push(f.id);
    }
    return ids.sort().join(' ');
  });
  /** The scanning files the current back-off waits for. */
  private scanIds = new Set<string>();
  private scanStep = 0;
  private scanTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => {
      const key = this.draftKey();
      untracked(() => {
        this.draft.set(readStore(DRAFT_PREFIX + key) ?? '');
        this.seenAt.set(readStore(SEEN_PREFIX + key));
        this.markerAt.set(null);
        this.markerSet = false;
        this.stick = true;
        this.atBottom.set(true);
        this.editingId.set(null);
        // The files of another thread never go into this one, nor do its running uploads.
        // The same thread in a re-created chat keeps them.
        if (this.thread.key !== key && (this.drafts.files().length || this.drafts.busy())) {
          void this.drafts.discard();
        }
        this.thread.key = key;
        // A new thread starts on the default visibility (public first), never on the last one.
        this.visibility.set(this.visibilityOptions()[0] ?? null);
      });
    });
    effect(() => {
      const first = this.visibilityOptions()[0] ?? null;
      untracked(() => this.visibility.set(first));
    });
    effect(() => {
      const newest = this.newestAt();
      if (this.markerSet || newest === null) return;
      this.markerSet = true;
      untracked(() => this.markerAt.set(this.seenAt() ?? newest));
    });
    afterRenderEffect(() => {
      this.items();
      untracked(() => this.follow());
    });
    afterRenderEffect(() => {
      const messages = this.messages();
      untracked(() => this.refocusAfterDelete(messages));
    });
    effect(() => {
      const ids = this.scanning();
      untracked(() => this.watchScan(ids));
    });
    this.destroyRef.onDestroy(() => {
      this.stopScanWatch();
      if (this.pageDrafts) this.pageDrafts.release();
      else void this.drafts.discard();
    });
    afterNextRender(() => {
      const observer = new ResizeObserver(() => this.follow());
      observer.observe(this.log().nativeElement);
      this.destroyRef.onDestroy(() => observer.disconnect());
    });
  }

  /**
   * A new file in the scan starts the back-off again; the last file out of the scan ends
   * it. When the back-off runs out, the next send starts it again.
   */
  private watchScan(joined: string): void {
    if (!joined) {
      this.stopScanWatch();
      this.scanIds = new Set();
      return;
    }
    const ids = joined.split(' ');
    const fresh = ids.some((id) => !this.scanIds.has(id));
    this.scanIds = new Set(ids);
    if (!fresh) return;
    this.stopScanWatch();
    this.scanStep = 0;
    this.armScanWatch();
  }

  private armScanWatch(): void {
    const wait = SCAN_BACKOFF[this.scanStep];
    if (wait === undefined) return;
    this.scanTimer = setTimeout(() => {
      this.scanTimer = null;
      this.scanStep++;
      this.refresh.emit();
      this.armScanWatch();
    }, wait);
  }

  private stopScanWatch(): void {
    if (this.scanTimer !== null) clearTimeout(this.scanTimer);
    this.scanTimer = null;
  }

  /** The time of the newest sent message, or null. */
  private newestAt(): string | null {
    let newest: string | null = null;
    for (const m of this.messages()) {
      if (isPending(m)) continue;
      if (newest === null || Date.parse(m.at) > Date.parse(newest)) newest = m.at;
    }
    return newest;
  }

  protected authorName(msg: ChatMessage): string | null {
    if (msg.authorLabel) return msg.authorLabel;
    if (!msg.author) return null;
    return msg.author.displayName ?? this.i18n.translate('chat.deletedPerson');
  }

  protected dayLabel(date: Date): string {
    const today = this.now();
    const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (dayKey(date) === dayKey(today)) return this.i18n.translate('chat.today');
    if (dayKey(date) === dayKey(yesterday)) return this.i18n.translate('chat.yesterday');
    // "Do, 08.10.": the weekday without its abbreviation dot, as everywhere in the app.
    const locale = this.i18n.formatLocale();
    const weekday = new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(date).replace(/\.$/, '');
    const opts: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit' };
    const sameYear = date.getFullYear() === today.getFullYear();
    if (!sameYear) opts.year = 'numeric';
    let day = new Intl.DateTimeFormat(locale, opts).format(date);
    if (sameYear && locale.startsWith('de') && !day.endsWith('.')) day = `${day}.`;
    return `${weekday}, ${day}`;
  }

  /** "PNG · 96 KB": the file type from the name, then the size. */
  protected fileMeta(file: { filename: string; size: number }): string {
    const dot = file.filename.lastIndexOf('.');
    const ext = dot > 0 ? file.filename.slice(dot + 1).toUpperCase() : '';
    const size = formatSize(file.size, this.i18n.formatLocale());
    return ext ? `${ext} · ${size}` : size;
  }

  /** The scan state of a file that is not a link; a lost file says so. */
  protected fileState(file: ChatAttachment | DraftFile): StatusView {
    if (('lost' in file && file.lost) || ('failed' in file && file.failed)) {
      return { kind: 'error', key: 'apply.files.lost' };
    }
    return scanStatus(file.scanState ?? 'clean');
  }

  /** A file of a message opens only when the scan found it clean. */
  protected isLink(file: ChatAttachment): boolean {
    return !file.lost && (file.scanState ?? 'clean') === 'clean';
  }

  protected time(at: string): string {
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(new Date(at));
  }

  /** The current time. A separate method lets a test fix it. */
  protected now(): Date {
    return new Date();
  }

  /** Own sent messages can change (or any the viewer may moderate). A pending one cannot. */
  protected canAct(msg: ChatMessage): boolean {
    return (msg.canEdit ?? msg.own) && !isPending(msg);
  }

  // --- scrolling -------------------------------------------------------------------

  /** Keep the newest message in view while the log is at its end. */
  private follow(): void {
    if (!this.stick) return;
    const el = this.log().nativeElement;
    el.scrollTop = el.scrollHeight;
    this.markSeen();
  }

  protected onScroll(): void {
    const el = this.log().nativeElement;
    this.stick = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_SLACK;
    this.atBottom.set(this.stick);
    if (this.stick) this.markSeen();
  }

  protected scrollToEnd(): void {
    this.stick = true;
    this.atBottom.set(true);
    this.follow();
  }

  private markSeen(): void {
    const newest = this.newestAt();
    if (newest === null || newest === this.seenAt()) return;
    this.seenAt.set(newest);
    writeStore(SEEN_PREFIX + this.draftKey(), newest);
  }

  // --- composer --------------------------------------------------------------------

  protected onDraft(value: string): void {
    this.draft.set(value);
    writeStore(DRAFT_PREFIX + this.draftKey(), value);
  }

  protected setVisibility(value: string | null): void {
    this.visibility.set(value === 'internal' || value === 'public' ? value : null);
  }

  /** Desktop: Enter sends, Shift+Enter is a new line. Phone: Enter is a new line. */
  protected onComposerKey(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || this.phone()) return;
    event.preventDefault();
    this.submit();
  }

  protected submit(event?: Event): void {
    event?.preventDefault();
    if (this.uploading()) return;
    const body = this.draft().trim();
    const files = this.drafts.usable();
    if (!body && !files.length) return;
    const vis = this.visibility();
    const req: ChatSend = vis ? { body, visibility: vis } : { body };
    if (files.length) {
      req.attachmentIds = files.map((f) => f.id);
      req.draftToken = this.drafts.token();
      req.files = files.map((f) => ({
        id: f.id,
        filename: f.filename,
        mime: f.mime,
        size: f.size,
        scanState: f.scanState,
        url: chatFileUrl(this.apiBase, f.id),
      }));
    }
    this.send.emit(req);
    // The message owns the files now: the next one starts a new draft.
    this.drafts.clear();
    // The chosen visibility stays for the next message of the thread.
    this.onDraft('');
    this.scrollToEnd();
  }

  // --- files -----------------------------------------------------------------------

  protected pickFiles(): void {
    this.fileInput()?.nativeElement.click();
  }

  protected onPicked(event: Event): void {
    const box = event.target as HTMLInputElement;
    const files = Array.from(box.files ?? []);
    box.value = '';
    void this.addFiles(files);
  }

  /**
   * A pasted image becomes a file of the message; pasted text stays text. Word, Excel and
   * many pages put a picture of the selection next to its text, so a clipboard with
   * plain text keeps the text and drops the picture. "Bild kopieren" in a browser, Slack
   * or Teams puts the image next to an HTML `<img>` and no plain text: that is a file.
   */
  protected onPaste(event: ClipboardEvent): void {
    if (!this.canAttach()) return;
    const data = event.clipboardData;
    if (data?.getData('text/plain').trim()) return;
    const files = Array.from(data?.files ?? []);
    if (!files.length) return;
    event.preventDefault();
    void this.addFiles(files.map((f) => this.named(f)));
  }

  /**
   * A file dragged onto the composer: without a handler the browser opens the file in
   * the tab, the app unloads and the outbox is lost. A file drag is therefore always
   * taken, and its files upload only when the chat takes files (`addFiles` applies the
   * count and the size). A text drag stays with the textarea.
   */
  protected onDragOver(event: DragEvent): void {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = this.canAttach() && !this.full() ? 'copy' : 'none';
  }

  protected onDrop(event: DragEvent): void {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    if (!this.canAttach()) return;
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length) void this.addFiles(files);
  }

  /**
   * A pasted image often has no extension, and the server matches the extension with
   * the content: "Bild-20261015-104500.png".
   */
  private named(file: File): File {
    if (/.\.[^.]+$/.test(file.name)) return file;
    const d = this.now();
    const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
    const ext = PASTE_EXT[file.type] ?? 'bin';
    const name = `${this.i18n.translate('chat.pastedImage')}-${stamp}.${ext}`;
    return new File([file], name, { type: file.type, lastModified: file.lastModified });
  }

  /** Upload files: the count and the size are checked here first, the server checks again. */
  protected async addFiles(list: readonly File[]): Promise<void> {
    const room = CHAT_MAX_FILES - this.files().length - this.uploads().length;
    if (list.length > room) {
      this.toast.error(this.i18n.translate('chat.error.tooManyFiles', { max: CHAT_MAX_FILES }));
    }
    const maxBytes = this.drafts.limits().maxFileBytes;
    const mb = Math.round(maxBytes / (1024 * 1024));
    const take: File[] = [];
    for (const file of list.slice(0, Math.max(0, room))) {
      if (file.size > maxBytes) {
        this.toast.error(`${file.name}: ${this.i18n.translate('chat.error.fileTooLarge', { mb })}`);
      } else {
        take.push(file);
      }
    }
    if (!take.length) return;
    const done = this.drafts.upload(take);
    this.leaveFullAttach();
    const { failed } = await done;
    for (const f of failed) {
      this.toast.error(`${f.filename}: ${this.i18n.translate(chatUploadError(f.reason), { mb })}`);
    }
  }

  /**
   * A full composer disables the paperclip, and a disabled button drops its focus to
   * the page. The upload queues its files at once, so the focus goes to the text box
   * before the next render disables the button.
   */
  private leaveFullAttach(): void {
    const attach = this.host.nativeElement.querySelector('.chat__attach');
    if (this.full() && attach?.contains(document.activeElement)) {
      this.composerInput()?.nativeElement.focus();
    }
  }

  /**
   * The remove button leaves the DOM with its chip, so the focus goes to the remove
   * button of the chip that takes its place (or the one before), else to the text box.
   */
  protected async removeFile(file: DraftFile): Promise<void> {
    const at = this.files().findIndex((f) => f.id === file.id);
    if (!(await this.drafts.remove(file.id))) {
      this.toast.error(this.i18n.translate('apply.files.error.delete'));
      return;
    }
    afterNextRender(
      () => {
        const buttons = Array.from(this.host.nativeElement.querySelectorAll<HTMLElement>('.chat__draftX'));
        const next = buttons[Math.min(at, buttons.length - 1)];
        (next ?? this.composerInput()?.nativeElement)?.focus();
      },
      { injector: this.injector },
    );
  }

  /** "Bearbeiten" on a failed message: only while it has no file the server still holds. */
  protected canEditFailed(msg: ChatMessage): boolean {
    return (msg.attachments ?? []).every((f) => f.lost);
  }

  // --- failed messages -------------------------------------------------------------

  /**
   * "Bearbeiten" on a failed message: its text goes back into the composer, ahead of a
   * draft typed since, and the failed message leaves the thread.
   */
  protected editFailed(msg: ChatMessage): void {
    const draft = this.draft().trim();
    this.onDraft(draft ? `${msg.body}\n\n${draft}` : msg.body);
    // The resend keeps the visibility the message had, not the one the composer shows now.
    if (msg.visibility && this.segmentOptions().some((o) => o.value === msg.visibility)) {
      this.visibility.set(msg.visibility);
    }
    this.discard.emit({ id: msg.id });
    afterNextRender(
      () => {
        const box = this.composerInput();
        if (!box) return;
        box.nativeElement.focus();
        box.nativeElement.setSelectionRange(box.nativeElement.value.length, box.nativeElement.value.length);
      },
      { injector: this.injector },
    );
  }

  // --- edit, delete, phone menu ----------------------------------------------------

  /**
   * The Edit button that had the focus leaves the DOM with the edit, so the focus goes
   * to the edit field, with the cursor at the end.
   */
  protected startEdit(msg: ChatMessage): void {
    this.menuFor.set(null);
    this.openEdit(msg.id, msg.body);
  }

  private openEdit(id: string, body: string): void {
    this.editDraft.set(body);
    this.editingId.set(id);
    afterNextRender(
      () => {
        const box = this.log().nativeElement.querySelector<HTMLTextAreaElement>('.chat__editInput');
        if (!box) return;
        box.focus();
        box.setSelectionRange(box.value.length, box.value.length);
      },
      { injector: this.injector },
    );
  }

  protected cancelEdit(): void {
    this.endEdit();
  }

  /**
   * Close the edit. When the focus was in it, it goes back to the Edit button of the
   * message, or to the log where the message has no buttons (a phone).
   */
  private endEdit(): void {
    const id = this.editingId();
    const log = this.log().nativeElement;
    const inside = log.contains(document.activeElement);
    this.editingId.set(null);
    if (id === null || !inside) return;
    afterNextRender(
      () => {
        const row = Array.from(log.querySelectorAll<HTMLElement>('.chat__row')).find((r) => r.dataset['msgId'] === id);
        (row?.querySelector<HTMLElement>('.chat__acts button') ?? log).focus();
      },
      { injector: this.injector },
    );
  }

  protected onEditKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      this.cancelEdit();
      return;
    }
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || this.phone()) return;
    event.preventDefault();
    this.saveEdit();
  }

  protected saveEdit(event?: Event): void {
    event?.preventDefault();
    const id = this.editingId();
    const body = this.editDraft().trim();
    if (id === null || !body) return;
    const msg = this.messages().find((m) => m.id === id);
    this.endEdit();
    if (msg && msg.body !== body) this.edit.emit({ id, body, restore: () => this.restoreEdit(id, body) });
  }

  /**
   * The server refused an edit: it opens again with the new text, so nothing typed is
   * lost. Not while another edit is open, and not for a message that is gone.
   */
  private restoreEdit(id: string, body: string): void {
    if (this.editingId() !== null || !this.messages().some((m) => m.id === id)) return;
    this.openEdit(id, body);
  }

  /**
   * "Erneut senden" and "Verwerfen" take away the button that had the focus, so it goes
   * to the composer, or to the log where the thread has none.
   */
  protected retryFailed(msg: ChatMessage): void {
    this.retry.emit({ id: msg.id });
    this.focusComposer();
  }

  protected discardFailed(msg: ChatMessage): void {
    this.discard.emit({ id: msg.id });
    this.focusComposer();
  }

  private focusComposer(): void {
    afterNextRender(
      () => (this.composerInput()?.nativeElement ?? this.log().nativeElement).focus(),
      { injector: this.injector },
    );
  }

  protected askDelete(msg: ChatMessage): void {
    this.menuFor.set(null);
    this.deleting.set(msg);
  }

  protected confirmDelete(): void {
    const msg = this.deleting();
    this.deleting.set(null);
    if (!msg) return;
    this.deletedId = msg.id;
    this.delete.emit({ id: msg.id });
  }

  /**
   * The dialog gives the focus back to the trash button, and that button goes with the
   * message once the consumer removes it. Then the focus goes to the composer, or to the
   * log where the thread has none, unless it has already moved somewhere that stays.
   */
  private refocusAfterDelete(messages: readonly ChatMessage[]): void {
    const id = this.deletedId;
    if (id === null || messages.some((m) => m.id === id)) return;
    this.deletedId = null;
    const active = this.log().nativeElement.ownerDocument.activeElement;
    if (active && active !== active.ownerDocument.body && active.isConnected) return;
    (this.composerInput()?.nativeElement ?? this.log().nativeElement).focus();
  }

  protected readonly menuHeading = computed(() => {
    const msg = this.menuFor();
    return msg ? this.i18n.translate('chat.ownMessage', { time: this.time(msg.at) }) : '';
  });

  protected onMenuOpen(open: boolean): void {
    if (!open) this.menuFor.set(null);
  }

  protected openMenu(msg: ChatMessage): void {
    this.menuFor.set(msg);
  }

  protected copy(msg: ChatMessage): void {
    this.menuFor.set(null);
    const clipboard = navigator.clipboard as Clipboard | undefined;
    if (clipboard) void clipboard.writeText(msg.body).catch(() => undefined);
  }
}
