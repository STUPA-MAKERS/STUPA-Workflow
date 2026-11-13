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
  type Signal,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { AgendaItem, Meeting, Protocol, Uuid } from '@core/api/models';
import {
  ButtonComponent,
  EmptyStateComponent,
  IconComponent,
  type IconName,
  NoteComponent,
  SegmentedComponent,
  type SegmentedOption,
  ScrollFadeDirective,
  StatusTextComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  MarkdownEditorComponent,
  type MarkdownDocumentInfo,
  type MarkdownDocumentRef,
  type MarkdownDocumentUploader,
  type MarkdownFormat,
  type MarkdownImageUploader,
} from '@stupa-makers/ui-kit/markdown-editor';
import { ImageAltService } from '@shared/markdown/image-alt.service';
import {
  DocumentViewerComponent,
  type ShownDocument,
} from '@shared/markdown/document-viewer.component';
import {
  MEDIA_DOCUMENT_TYPES,
  MediaApiService,
  type MediaDocument,
  markdownDocument,
} from '@shared/markdown/media-api.service';
import {
  MarkdownImageUploadDirective,
  imageUploadErrorKey,
} from '@shared/markdown/markdown-image-upload.directive';
import { meetingKeeperLine } from '../keepers.util';
import { ProtocolBarComponent } from '../protocol-bar/protocol-bar.component';
import { type LinkedLead, TodoLinkedListComponent } from '../../todos/linked-list/todo-linked-list.component';
import { voteResultResolver } from '../vote-result/vote-result';
import { hasOpenBlackout } from '../../../shared/markdown/markdown.util';
import {
  applyRawFormat,
  insertRawInline,
  insertRawTable,
  insertRawTimeNote,
  protocolNow,
} from './raw-format';
import { topLead } from '../top-application-lead.util';

/** The autosave state of the text of the open item. */
export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/** The view of the text: rendered as it reads, or the Markdown source. */
export type EditorMode = 'formatted' | 'raw';

const NO_FORMATS: ReadonlySet<MarkdownFormat> = new Set();

/** The i18n key of a PDF upload error, from the HTTP status of the problem response. */
export function documentUploadErrorKey(status?: number): TranslationKey {
  switch (status) {
    case 403:
      return 'markdown.document.error.forbidden';
    case 413:
      return 'markdown.document.error.tooLarge';
    case 415:
      return 'markdown.document.error.type';
    case 429:
      return 'markdown.image.error.rate';
    case 503:
      return 'markdown.image.error.storage';
    default:
      return 'markdown.document.error.upload';
  }
}

/** A button of the format bar. */
interface FormatTool {
  readonly format: MarkdownFormat;
  readonly icon: IconName;
  readonly label: TranslationKey;
}

const TOOLS: readonly FormatTool[] = [
  { format: 'heading', icon: 'heading', label: 'meetings.editor.heading' },
  { format: 'bold', icon: 'bold', label: 'meetings.editor.bold' },
  { format: 'italic', icon: 'italic', label: 'meetings.editor.italic' },
  { format: 'bulletList', icon: 'list', label: 'meetings.editor.list' },
  { format: 'blockquote', icon: 'quote', label: 'meetings.editor.quote' },
  { format: 'blackout', icon: 'eyeslash', label: 'meetings.editor.blackout' },
];

/**
 * The sheet of the open agenda item: "TOP 3 · Antrag", the title, the rows of the
 * application and of the linked to-do cards below the title, the format bar with the save state, and the Markdown editor of the text.
 *
 * A planned meeting has no protocol yet, but the text of its items can be prepared
 * (`editable`); the start creates the protocol around it.
 *
 * In a live meeting only the minute-taker types (`editable`); everybody else with write
 * access reads the same sheet, and its foot says who keeps the minutes and the state of
 * the protocol.
 *
 * A closed meeting: the protocol
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
    TranslatePipe,
    IconComponent,
    MarkdownEditorComponent,
    MarkdownImageUploadDirective,
    DocumentViewerComponent,
    NoteComponent,
    ProtocolBarComponent,
    ScrollFadeDirective,
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
   * The participant view: read only, "Jetzt"
   * before the item that the room handles, the line "Mara Keller führt das Protokoll"
   * below the title, and the text without a protocol of the viewer.
   */
  readonly follow = input(false);
  /**
   * Show the linked list (the application and the to-dos) below the title. The meeting
   * page turns it off and shows the list above the sheet, between the votes and the
   * protocol.
   */
  readonly linked = input(true);
  /**
   * The bar: the format tools, "Erledigt" and the view switch. On a phone the dock of the
   * page holds them as icon buttons (the tools behind "Aa"), and the page binds `mode`;
   * the save state then sits beside the title.
   */
  readonly barControls = input(true);
  /**
   * The viewer may rename the item (`canChangeAgenda`). A click on the title then opens
   * the title field in place of the heading. An application item keeps the title of its
   * application in its row below the title.
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


  readonly tools = TOOLS;

  /**
   * The item whose rename started from this heading. The agenda pane shows its own field
   * for a rename from its row menu, so the heading shows the field only for its own rename.
   */
  private readonly renamingHere = signal<Uuid | null>(null);
  /** The rename of `renamingHere` reached the agenda; its end clears `renamingHere`. */
  private renameStarted = false;
  private readonly titleInput = viewChild<ElementRef<HTMLInputElement>>('titleInput');

  /** The title of the open item can change here. */
  protected readonly titleRenamable = computed(() => {
    const t = this.top();
    return this.canRename() && !this.follow() && !!t;
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
    effect(() => {
      const id = this.renamingTopId();
      const here = untracked(this.renamingHere);
      if (here !== null && id === here) {
        this.renameStarted = true;
      } else if (this.renameStarted) {
        this.renameStarted = false;
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
  readonly mode = model<EditorMode>('formatted');

  protected readonly modeOptions = computed<SegmentedOption[]>(() => {
    this.i18n.uiLocale();
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
    // The alt text comes first (app spec 000506). A cancel inserts nothing and needs no toast.
    const alt = await this.injector.get(ImageAltService).ask(file);
    if (alt === null) throw new Error('cancelled');
    try {
      const image = await firstValueFrom(this.injector.get(MediaApiService).uploadImage(file));
      return { src: `/api/media/images/${image.id}`, alt };
    } catch (err) {
      this.toast.error(this.i18n.translate(imageUploadErrorKey((err as { status?: number } | null)?.status)));
      throw err;
    }
  };

  /**
   * Upload a PDF of the formatted view to the protocol of the meeting (spec 000862). An
   * error shows as a toast; the editor then inserts nothing.
   */
  protected readonly documentUpload: MarkdownDocumentUploader = async (file) => {
    const doc = await this.sendDocument(file);
    return { src: doc.url, name: doc.name };
  };

  /** The page count of a PDF badge, from its info route; cached per path. */
  private readonly pageCounts = signal<ReadonlyMap<string, Promise<number | null>>>(new Map());
  protected readonly documentInfo: MarkdownDocumentInfo = (src) => {
    const known = this.pageCounts().get(src);
    if (known) return known;
    const next = firstValueFrom(this.injector.get(MediaApiService).documentInfo(src)).then(
      (info) => info.pages,
      () => null,
    );
    this.pageCounts.update((counts) => new Map([...counts, [src, next]]));
    return next;
  };

  /** The PDF in the overlay (spec 000863). */
  protected readonly shownDocument = signal<ShownDocument | null>(null);

  protected openDocument(ref: MarkdownDocumentRef): void {
    this.shownDocument.set({ name: ref.name, url: ref.src });
  }

  private async sendDocument(file: File): Promise<MediaDocument> {
    try {
      return await firstValueFrom(
        this.injector.get(MediaApiService).uploadDocument(this.meeting().id, file),
      );
    } catch (err) {
      this.toast.error(
        this.i18n.translate(documentUploadErrorKey((err as { status?: number } | null)?.status)),
      );
      throw err;
    }
  }

  /** "PDF einfügen": the file dialog of the editor, or of the Markdown source. */
  insertDocument(): void {
    if (this.mode() !== 'raw') {
      this.editor()?.pickDocument();
      return;
    }
    const area = this.rawArea()?.nativeElement;
    if (!area || area.readOnly) return;
    const picker = document.createElement('input');
    picker.setAttribute('type', 'file');
    picker.setAttribute('accept', MEDIA_DOCUMENT_TYPES.join(','));
    picker.toggleAttribute('multiple', true);
    picker.addEventListener('change', () => void this.uploadRawDocuments(Array.from(picker.files ?? [])));
    picker.click();
  }

  /** A paste of PDF files into the Markdown source uploads them (images go to the directive). */
  protected onRawPaste(event: ClipboardEvent): void {
    const pdfs = pdfFiles(event.clipboardData?.files);
    if (!pdfs.length || !this.editable()) return;
    event.preventDefault();
    void this.uploadRawDocuments(pdfs);
  }

  /** A drop of PDF files on the Markdown source uploads them at the caret. */
  protected onRawDrop(event: DragEvent): void {
    const pdfs = pdfFiles(event.dataTransfer?.files);
    if (!pdfs.length || !this.editable()) return;
    event.preventDefault();
    void this.uploadRawDocuments(pdfs);
  }

  /** Upload PDFs one after the other and put each reference at the caret of the source. */
  private async uploadRawDocuments(files: readonly File[]): Promise<void> {
    await files.reduce(async (done, file) => {
      await done;
      const doc = await this.sendDocument(file).catch(() => null);
      const area = this.rawArea()?.nativeElement;
      const t = this.top();
      if (!doc || !area || !t || area.readOnly) return;
      const next = insertRawInline(
        { text: area.value, start: area.selectionStart, end: area.selectionEnd },
        markdownDocument(doc.name, doc.id),
      );
      Reflect.set(area, 'value', next.text);
      area.setSelectionRange(next.start, next.end);
      this.bodyChange.emit({ itemId: t.id, body: next.text });
    }, Promise.resolve());
  }

  /** The text has a `%%` without its closing pair (000686): the public variant would show the name. */
  protected readonly openBlackout = computed(() => hasOpenBlackout(this.top()?.body ?? ''));

  /** The formats at the cursor. The Markdown source shows none as pressed. */
  readonly activeFormats = computed(() =>
    this.mode() === 'raw' ? NO_FORMATS : (this.editor()?.activeFormats() ?? NO_FORMATS),
  );

  protected setMode(value: string | null): void {
    this.mode.set(value === 'raw' ? 'raw' : 'formatted');
  }

  /** A button of the format bar: in the editor, or in the Markdown source. */
  toggleFormat(format: MarkdownFormat): void {
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
    Reflect.set(area, 'value', next.text);
    area.focus();
    area.setSelectionRange(next.start, next.end);
    this.bodyChange.emit({ itemId: t.id, body: next.text });
  }

  /** "Tabelle einfügen": in the editor, or as a Markdown table in the source. */
  insertTable(): void {
    if (this.mode() !== 'raw') {
      this.editor()?.insertTable();
      return;
    }
    const area = this.rawArea()?.nativeElement;
    const t = this.top();
    if (!area || !t || area.readOnly) return;
    const next = insertRawTable({ text: area.value, start: area.selectionStart, end: area.selectionEnd });
    Reflect.set(area, 'value', next.text);
    area.focus();
    area.setSelectionRange(next.start, next.end);
    this.bodyChange.emit({ itemId: t.id, body: next.text });
  }

  /**
   * "Anmerkung": a time note with the current local time after the line of the cursor,
   * in the editor or in the Markdown source. The cursor goes to the text of the note.
   */
  insertTimeNote(): void {
    const time = protocolNow();
    if (this.mode() !== 'raw') {
      this.editor()?.insertTimeNote(time);
      return;
    }
    const area = this.rawArea()?.nativeElement;
    const t = this.top();
    if (!area || !t || area.readOnly) return;
    const next = insertRawTimeNote({ text: area.value, start: area.selectionStart, end: area.selectionEnd }, time);
    Reflect.set(area, 'value', next.text);
    area.focus();
    area.setSelectionRange(next.start, next.end);
    this.bodyChange.emit({ itemId: t.id, body: next.text });
  }

  /** "Bild einfügen": the file dialog of the editor or of the Markdown source. */
  insertImage(): void {
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

  /** "TOP 3 · Antrag", "TOP 3 · Haushaltsplan", or "TOP 3" for a free-text item. */
  protected kindLine(t: AgendaItem): string {
    const top = this.i18n.translate('meetings.agenda.top', { n: this.topIndex() + 1 });
    const kind = t.applicationId
      ? 'meetings.agenda.kindApplication'
      : t.planVersionId
        ? 'meetings.agenda.planSub'
        : null;
    return kind ? `${top} · ${this.i18n.translate(kind)}` : top;
  }

  /**
   * The document key of the editor. The minute-taker's editor keeps its key while they
   * type, and only an insert from outside raises `revision`. A read-only editor has no
   * input of its own: the participant view (`follow`) and the pane of a reader with
   * `canWrite` who does not keep the minutes (the session lead, an admin). The text that
   * the room writes reaches it with each live draft and each read of the agenda, so its
   * key changes with the text.
   */
  protected readonly docKey = computed(() => {
    const t = this.top();
    if (!t) return '';
    const reader = this.follow() || !this.editable();
    return reader ? `${t.id}:${textHash(t.body ?? '')}` : `${t.id}:${this.revision()}`;
  });

  /** The item is the one that the room handles now (participant view, live meeting). */
  protected readonly isNow = computed(() => {
    const m = this.meeting();
    return this.follow() && m.status === 'live' && !!m.currentAgendaItemId && this.top()?.id === m.currentAgendaItemId;
  });

  /** The row of the application, the first row of the linked list (`topLead`). */
  protected readonly applicationLead: Signal<LinkedLead | null> = topLead(this.top, this.injector, this.i18n);

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
}

/** A short hash of a text (FNV-1a, 32 bit), so that a document key changes with it. */
function textHash(text: string): string {
  const hash = text
    .split('')
    .reduce((h, c) => Math.imul(h ^ c.charCodeAt(0), 0x01000193), 0x811c9dc5);
  return `${text.length}.${(hash >>> 0).toString(36)}`;
}

/** The PDF files of a paste or a drop. */
function pdfFiles(list: FileList | null | undefined): readonly File[] {
  return Array.from(list ?? []).filter((f) => MEDIA_DOCUMENT_TYPES.includes(f.type));
}
