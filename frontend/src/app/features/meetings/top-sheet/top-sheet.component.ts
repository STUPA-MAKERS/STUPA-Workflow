import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  type ElementRef,
  inject,
  Injector,
  input,
  model,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { AgendaItem, Meeting, Protocol, Uuid } from '@core/api/models';
import {
  ButtonComponent,
  EmptyStateComponent,
  IconComponent,
  type IconName,
  MEDIA,
  mediaQuery,
  NoteComponent,
  SegmentedComponent,
  type SegmentedOption,
  type StatusKind,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  MarkdownEditorComponent,
  type MarkdownFormat,
  type MarkdownImageUploader,
} from '@stupa-makers/ui-kit/markdown-editor';
import { MediaApiService } from '@shared/markdown/media-api.service';
import {
  MarkdownImageUploadDirective,
  imageUploadErrorKey,
} from '@shared/markdown/markdown-image-upload.directive';
import { resolveI18n } from '@shared/forms/i18n-text';
import { meetingKeeperLine } from '../keepers.util';
import { ProtocolBarComponent } from '../protocol-bar/protocol-bar.component';
import { TodoLinkedListComponent } from '../../todos/linked-list/todo-linked-list.component';
import { voteResultResolver } from '../vote-result/vote-result';
import { applyRawFormat, insertRawTable } from './raw-format';

/** The autosave state of the text of the open item. */
export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/** The view of the text: rendered as it reads, or the Markdown source. */
export type EditorMode = 'formatted' | 'raw';

const NO_FORMATS: ReadonlySet<MarkdownFormat> = new Set();

/** A button of the format bar. */
interface FormatTool {
  format: MarkdownFormat;
  icon: IconName;
  label: TranslationKey;
}

const TOOLS: readonly FormatTool[] = [
  { format: 'heading', icon: 'heading', label: 'meetings.editor.heading' },
  { format: 'bold', icon: 'bold', label: 'meetings.editor.bold' },
  { format: 'italic', icon: 'italic', label: 'meetings.editor.italic' },
  { format: 'bulletList', icon: 'list', label: 'meetings.editor.list' },
];

/** The file name without its extension, as the alt text of an uploaded image. */
function altOf(file: File): string {
  return file.name.replace(/\.[^.]*$/, '');
}

/**
 * The sheet of the open agenda item: "TOP 3 · Antrag", the title, "Antrag öffnen", the
 * format bar with the save state, and the Markdown editor of the text.
 *
 * A planned meeting has no protocol yet, but the text of its items can be prepared
 * (`editable`); the start creates the protocol around it.
 *
 * In a live meeting only the minute-taker types (`editable`); everybody else with write
 * access reads the same sheet, and its foot says who keeps the minutes and the state of
 * the protocol.
 *
 * A closed meeting (boards Sitzung-Protokoll-Entwurf, Sitzung-Geschlossen): the protocol
 * bar on top (draft and "Finalisieren & versenden", or final and the PDF links) and the
 * keeper line below the title, "Protokoll: Lara Leitung (TOP 1–3), Uli Übernahme (ab TOP 3,
 * 18:55)". The text stays editable for every writer while the protocol is a draft.
 *
 * A writer of the minutes (`editable`) ticks the open item with "Erledigt" right of the
 * title, a toggle that also removes the tick ("TOP abhaken").
 *
 * The participant view (`follow`) reads the same sheet without a protocol of its own.
 *
 * A switch in the format bar shows the text formatted or as its Markdown source. The
 * format buttons work in both views. The choice stays when another item opens.
 * "Tabelle einfügen" and "Bild einfügen" also work in both views; in a table of the
 * formatted view a menu edits its rows and columns. A paste or a drop of an image file
 * uploads it to the media store and inserts the image (`MediaApiService`).
 *
 * A vote result in the text shows as a card with "Beschluss · 18:52 · Einfache Mehrheit",
 * the counts and the result (a tie is "Abgelehnt"), from the votes of this meeting.
 */
@Component({
  selector: 'app-top-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    EmptyStateComponent,
    FormsModule,
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    IconComponent,
    MarkdownEditorComponent,
    MarkdownImageUploadDirective,
    NoteComponent,
    ProtocolBarComponent,
    SegmentedComponent,
    StatusTextComponent,
    TodoLinkedListComponent,
  ],
  templateUrl: './top-sheet.component.html',
  styleUrl: './top-sheet.component.scss',
})
export class TopSheetComponent {
  private readonly i18n = inject(I18nService);
  private readonly injector = inject(Injector);
  private readonly toast = inject(ToastService);

  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol | null>();
  readonly top = input.required<AgendaItem | null>();
  /** The 0-based index of the open item. */
  readonly topIndex = input.required<number>();
  /**
   * The minutes may be written here: a protocol exists (or the meeting is planned), it
   * is not locked, and the viewer keeps the minutes (or nobody does and the viewer may
   * write).
   */
  readonly editable = input.required<boolean>();
  /** The viewer may write the protocol in principle (`canEditProtocol`). */
  readonly canEdit = input.required<boolean>();
  readonly saveState = input.required<SaveState>();
  /**
   * The editor reloads its text only when the document key changes. An insert from
   * outside the editor, like a vote result, raises this number so the new text shows.
   */
  readonly revision = input(0);
  /** The finalize runs. */
  readonly finalizing = input(false);
  /**
   * The participant view (boards Teilnahme-Live, Schmal-Teilnahme): read only, "Jetzt"
   * before the item that the room handles, the line "Mara Keller führt das Protokoll"
   * below the title, and the text without a protocol of the viewer.
   */
  readonly follow = input(false);
  /**
   * The viewer may rename a free-text item (`canChangeAgenda`). A click on the title
   * then opens the title field in place of the heading. An application item keeps the
   * title of its application.
   */
  readonly canRename = input(false);
  /** The item in the inline rename of the agenda, shared with the agenda pane. */
  readonly renamingTopId = input<Uuid | null>(null);
  readonly renameDraft = model<string>('');

  readonly bodyChange = output<{ itemId: Uuid; body: string }>();
  /** "Finalisieren & versenden" in the protocol bar of a closed meeting. */
  readonly finalize = output<void>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  /** "Erledigt" in the bar: set or remove the done mark of the open item. */
  readonly doneChange = output<{ item: AgendaItem; done: boolean }>();

  private readonly phone = mediaQuery(MEDIA.phone);

  /**
   * The save state sits in the footer of a live protocol, so the bar keeps one row. A
   * phone keeps it in the bar: there the footer is at the end of the text.
   */
  protected readonly saveInFoot = computed(() => {
    const m = this.meeting();
    return !!this.protocol() && m.status !== 'closed' && !this.follow() && !this.phone();
  });

  protected readonly tools = TOOLS;

  /**
   * The item whose rename started from this heading. The agenda pane shows its own field
   * for a rename from its row menu, so the heading shows the field only for its own rename.
   */
  private readonly renamingHere = signal<Uuid | null>(null);
  private readonly titleInput = viewChild<ElementRef<HTMLInputElement>>('titleInput');

  /** The title of the open item can change here. */
  protected readonly titleRenamable = computed(() => {
    const t = this.top();
    return this.canRename() && !this.follow() && !!t && !t.applicationId;
  });
  /** The heading shows the title field. */
  protected readonly titleEditing = computed(
    () => {
      const id = this.top()?.id;
      return this.titleRenamable() && this.renamingHere() === id && this.renamingTopId() === id;
    },
  );

  /**
   * Only a rename end after the start counts, because the agenda names the item only after the
   * click.
   */
  constructor() {
    effect(() => {
      const el = this.titleInput()?.nativeElement;
      if (!el) return;
      el.focus();
      el.select();
    });
    let started = false;
    effect(() => {
      const id = this.renamingTopId();
      const here = untracked(this.renamingHere);
      if (here !== null && id === here) {
        started = true;
      } else if (started) {
        started = false;
        this.renamingHere.set(null);
      }
    });
  }

  /** Open the title field of the heading. */
  protected editTitle(t: AgendaItem): void {
    this.renamingHere.set(t.id);
    this.startRename.emit(t);
  }

  /**
   * Save the title (Enter or blur). An unchanged or empty title saves nothing, and the
   * agenda ignores the blur that follows an Enter or an Escape.
   */
  protected saveTitle(t: AgendaItem): void {
    this.renamingHere.set(null);
    this.renameTop.emit(t);
  }

  /** Close the title field and keep the old title (Escape). */
  protected cancelTitle(): void {
    this.renamingHere.set(null);
    this.cancelRename.emit();
  }

  /** The view of the text. */
  protected readonly mode = signal<EditorMode>('formatted');

  protected readonly modeOptions = computed<SegmentedOption[]>(() => {
    this.i18n.locale();
    return [
      { value: 'formatted', label: this.i18n.translate('meetings.editor.modeFormatted') },
      { value: 'raw', label: this.i18n.translate('meetings.editor.modeRaw') },
    ];
  });

  private readonly editor = viewChild<MarkdownEditorComponent>('ed');
  private readonly rawArea = viewChild<ElementRef<HTMLTextAreaElement>>('raw');
  private readonly rawUpload = viewChild(MarkdownImageUploadDirective);

  /**
   * Upload an image of the formatted view. The service resolves on the first upload, so
   * a sheet that never uploads needs no HTTP client. An error shows as a toast.
   */
  protected readonly imageUpload: MarkdownImageUploader = async (file) => {
    try {
      const image = await firstValueFrom(this.injector.get(MediaApiService).uploadImage(file));
      return { src: `/api/media/images/${image.id}`, alt: altOf(file) };
    } catch (err) {
      this.toast.error(this.i18n.translate(imageUploadErrorKey((err as { status?: number } | null)?.status)));
      throw err;
    }
  };

  /** The formats at the cursor. The Markdown source shows none as pressed. */
  protected readonly activeFormats = computed(() =>
    this.mode() === 'raw' ? NO_FORMATS : (this.editor()?.activeFormats() ?? NO_FORMATS),
  );

  protected setMode(value: string | null): void {
    this.mode.set(value === 'raw' ? 'raw' : 'formatted');
  }

  /** A button of the format bar: in the editor, or in the Markdown source. */
  protected toggleFormat(format: MarkdownFormat): void {
    if (this.mode() !== 'raw') {
      this.editor()?.toggleFormat(format);
      return;
    }
    const area = this.rawArea()?.nativeElement;
    const t = this.top();
    if (!area || !t || area.readOnly) return;
    const next = applyRawFormat(
      { text: area.value, start: area.selectionStart, end: area.selectionEnd },
      format,
    );
    area.value = next.text;
    area.focus();
    area.setSelectionRange(next.start, next.end);
    this.bodyChange.emit({ itemId: t.id, body: next.text });
  }

  /** "Tabelle einfügen": in the editor, or as a Markdown table in the source. */
  protected insertTable(): void {
    if (this.mode() !== 'raw') {
      this.editor()?.insertTable();
      return;
    }
    const area = this.rawArea()?.nativeElement;
    const t = this.top();
    if (!area || !t || area.readOnly) return;
    const next = insertRawTable({ text: area.value, start: area.selectionStart, end: area.selectionEnd });
    area.value = next.text;
    area.focus();
    area.setSelectionRange(next.start, next.end);
    this.bodyChange.emit({ itemId: t.id, body: next.text });
  }

  /** "Bild einfügen": the file dialog of the editor or of the Markdown source. */
  protected insertImage(): void {
    if (this.mode() !== 'raw') {
      this.editor()?.pickImage();
      return;
    }
    this.rawUpload()?.pick();
  }

  /** An edit in the formatted editor. A reader changes nothing, also when the editor emits. */
  protected onEditorChange(t: AgendaItem, value: string): void {
    if (!this.editable()) return;
    this.bodyChange.emit({ itemId: t.id, body: value });
  }

  /** An edit of the Markdown source. A reader changes nothing. */
  protected onRawInput(t: AgendaItem, value: string): void {
    if (!this.editable()) return;
    this.bodyChange.emit({ itemId: t.id, body: value });
  }

  /** "TOP 3 · Antrag", or "TOP 3" for a free-text item ("Freitext" says nothing). */
  protected kindLine(t: AgendaItem): string {
    const top = this.i18n.translate('meetings.agenda.top', { n: this.topIndex() + 1 });
    return t.applicationId ? `${top} · ${this.i18n.translate('meetings.agenda.kindApplication')}` : top;
  }

  /**
   * The document key of the editor. The minute-taker's editor keeps its key while they
   * type, and only an insert from outside raises `revision`. The participant view
   * (`follow`) has no input of its own: the text that the room writes reaches it with
   * each read of the agenda, so its key changes with the text.
   */
  protected readonly docKey = computed(() => {
    const t = this.top();
    if (!t) return '';
    return this.follow() ? `${t.id}:${textHash(t.body ?? '')}` : `${t.id}:${this.revision()}`;
  });

  /** The item is the one that the room handles now (participant view, live meeting). */
  protected readonly isNow = computed(() => {
    const m = this.meeting();
    return this.follow() && m.status === 'live' && !!m.currentAgendaItemId && this.top()?.id === m.currentAgendaItemId;
  });

  /** The state of the application of the item, in the language of the page. */
  protected readonly stateLabel = computed(() =>
    resolveI18n(this.top()?.stateLabel, this.i18n.locale()),
  );

  /** The keeper line of a closed meeting: every minute-taker with the TOPs they wrote. */
  protected readonly keepers = computed(() =>
    meetingKeeperLine(
      this.meeting(),
      (key, params) => this.i18n.translate(key, params),
      this.i18n.locale(),
    ),
  );

  /** The vote cards of the text read the closed votes of this meeting. */
  protected readonly voteInfo = computed(() =>
    voteResultResolver(
      this.meeting().votes,
      (key, params) => this.i18n.translate(key, params),
      this.i18n.locale(),
    ),
  );

  /** The state of the protocol as status text. */
  protected protocolState(p: Protocol): { kind: StatusKind; key: TranslationKey } {
    if (p.isFinal) return { kind: 'accent', key: 'meetings.protocol.final' };
    if (p.status === 'rendering') return { kind: 'warn', key: 'meetings.protocol.rendering' };
    return { kind: 'neutral', key: 'meetings.protocol.draft' };
  }
}

/** A short hash of a text (FNV-1a, 32 bit), so that a document key changes with it. */
function textHash(text: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${text.length}.${(hash >>> 0).toString(36)}`;
}
