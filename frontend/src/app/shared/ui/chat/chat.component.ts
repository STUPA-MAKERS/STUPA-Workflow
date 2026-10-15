import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
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
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  MEDIA,
  SegmentedComponent,
  type SegmentedOption,
} from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { markdownToSafeHtml } from '@shared/markdown/markdown.util';
import { PressSelectDirective } from '@shared/press-select.directive';
import { mediaQuerySignal } from '../../../layout/media-query';
import { AvatarComponent } from '../avatar/avatar.component';
import { SideSheetComponent } from '../side-sheet/side-sheet.component';
import type {
  ChatEdit,
  ChatEvent,
  ChatMessage,
  ChatRef,
  ChatSend,
  ChatVisibility,
} from './chat.models';
import { buildItems, dayKey, isPending, linkify, newCount } from './chat.util';

/** The log counts as "at the newest message" this close to its end, in px. */
const BOTTOM_SLACK = 24;
const DRAFT_PREFIX = 'ap.chat.draft.';
const SEEN_PREFIX = 'ap.chat.seen.';

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
 * - Own messages: edit and delete on hover or focus (desktop), a long press opens a
 *   bottom sheet (phone).
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
    PressSelectDirective,
    SegmentedComponent,
    SideSheetComponent,
    TranslatePipe,
  ],
  host: { '[class.chat--phone]': 'phone()' },
  templateUrl: './chat.component.html',
  styleUrl: './chat.component.scss',
})
export class ChatComponent {
  private readonly i18n = inject(I18nService);
  private readonly destroyRef = inject(DestroyRef);

  readonly messages = input<readonly ChatMessage[]>([]);
  readonly events = input<readonly ChatEvent[]>([]);
  readonly canPost = input(true);
  /** The visibilities the composer offers. Empty: no toggle. */
  readonly visibilityOptions = input<readonly ChatVisibility[]>([]);
  /** Names the thread in the browser storage (draft, last seen). */
  readonly draftKey = input.required<string>();
  readonly placeholder = input<TranslationKey>('chat.placeholder');

  readonly send = output<ChatSend>();
  readonly edit = output<ChatEdit>();
  readonly delete = output<ChatRef>();
  readonly retry = output<ChatRef>();

  protected readonly phone = mediaQuerySignal(MEDIA.phone);
  private readonly log = viewChild.required<ElementRef<HTMLElement>>('log');

  protected readonly draft = signal('');
  protected readonly visibility = signal<ChatVisibility | null>(null);
  protected readonly editingId = signal<string | null>(null);
  protected readonly editDraft = signal('');
  protected readonly deleting = signal<ChatMessage | null>(null);
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
    afterNextRender(() => {
      const observer = new ResizeObserver(() => this.follow());
      observer.observe(this.log().nativeElement);
      this.destroyRef.onDestroy(() => observer.disconnect());
    });
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
    const opts: Intl.DateTimeFormatOptions = { weekday: 'short', day: '2-digit', month: '2-digit' };
    if (date.getFullYear() !== today.getFullYear()) opts.year = 'numeric';
    return new Intl.DateTimeFormat(this.i18n.formatLocale(), opts).format(date);
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

  /** Own sent messages can change. A pending one cannot. */
  protected canAct(msg: ChatMessage): boolean {
    return msg.own && !isPending(msg);
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
    const body = this.draft().trim();
    if (!body) return;
    const vis = this.visibility();
    this.send.emit(vis ? { body, visibility: vis } : { body });
    this.onDraft('');
    this.visibility.set(this.visibilityOptions()[0] ?? null);
    this.scrollToEnd();
  }

  // --- edit, delete, phone menu ----------------------------------------------------

  protected startEdit(msg: ChatMessage): void {
    this.menuFor.set(null);
    this.editDraft.set(msg.body);
    this.editingId.set(msg.id);
  }

  protected cancelEdit(): void {
    this.editingId.set(null);
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
    this.editingId.set(null);
    if (msg && msg.body !== body) this.edit.emit({ id, body });
  }

  protected askDelete(msg: ChatMessage): void {
    this.menuFor.set(null);
    this.deleting.set(msg);
  }

  protected confirmDelete(): void {
    const msg = this.deleting();
    this.deleting.set(null);
    if (msg) this.delete.emit({ id: msg.id });
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
