import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  Injector,
  input,
  model,
  output,
  type Signal,
  signal,
  viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { I18nService } from '@core/i18n/i18n.service';
import { PaperlessService, type PaperlessCopy } from '@core/api/paperless.service';
import type { AgendaItem, Meeting, Protocol, Uuid } from '@core/api/models';
import type { MarkdownDocumentRef, MarkdownFormat } from '@stupa-makers/ui-kit/markdown-editor';
import {
  type EditorMode,
  type SaveState,
  TopSheetViewComponent,
} from '@stupa-makers/ui-kit/views/protocol';
import {
  DocumentViewerComponent,
  type ShownDocument,
} from '@shared/markdown/document-viewer.component';
import { meetingKeeperLine } from '../keepers.util';
import { PaperlessInsertComponent } from '../paperless-insert/paperless-insert.component';
import { type LinkedLead, TodoLinkedListComponent } from '../../todos/linked-list/todo-linked-list.component';
import { voteResultResolver } from '../vote-result/vote-result';
import { topLead } from '../top-application-lead.util';
import { provideProtocolApi } from './protocol-api.provider';

export type { EditorMode, SaveState } from '@stupa-makers/ui-kit/views/protocol';

const NO_FORMATS: ReadonlySet<MarkdownFormat> = new Set();

/** The typed text that opens the Paperless search (§F/integrations/paperless/002527). */
export const PAPERLESS_PREFIX = '::';

/**
 * The sheet of the open agenda item: the kit view `app-top-sheet-view`
 * (S/framework/views/002273) with the parts of the app. This component gives the view the
 * vote cards of the meeting, the keeper line, the rows of the application and of the linked
 * to-dos, the media store (`PROTOCOL_API`), the PDF viewer and the Paperless search that `::`
 * opens (§F/integrations/paperless/002527).
 *
 * The meeting page reaches the format tools of the view through it (`toolGroups`,
 * `activeFormats`, `toggleFormat`, the inserts), because on a phone the dock holds them.
 */
@Component({
  selector: 'app-top-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TopSheetViewComponent, TodoLinkedListComponent, DocumentViewerComponent, PaperlessInsertComponent],
  providers: [provideProtocolApi()],
  templateUrl: './top-sheet.component.html',
  styleUrl: './top-sheet.component.scss',
})
export class TopSheetComponent {
  private readonly i18n = inject(I18nService);
  private readonly injector = inject(Injector);

  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol | null>();
  readonly top = input.required<AgendaItem | null>();
  readonly topIndex = input.required<number>();
  readonly editable = input.required<boolean>();
  readonly canEdit = input.required<boolean>();
  readonly saveState = input.required<SaveState>();
  readonly revision = input(0);
  readonly follow = input(false);
  readonly linked = input(true);
  readonly barControls = input(true);
  readonly canRename = input(false);
  readonly renamingTopId = input<Uuid | null>(null);
  readonly renameDraft = model<string>('');
  readonly mode = model<EditorMode>('formatted');

  readonly bodyChange = output<{ itemId: Uuid; body: string }>();
  readonly startRename = output<AgendaItem>();
  readonly cancelRename = output<void>();
  readonly renameTop = output<AgendaItem>();
  readonly doneChange = output<{ item: AgendaItem; done: boolean }>();

  private readonly view = viewChild(TopSheetViewComponent);

  /** The format tools as button groups, for the dock of the page. */
  get toolGroups(): TopSheetViewComponent['toolGroups'] {
    return this.view()?.toolGroups ?? [];
  }

  /** The formats at the cursor. */
  readonly activeFormats = computed(() => this.view()?.activeFormats() ?? NO_FORMATS);

  toggleFormat(format: MarkdownFormat): void {
    this.view()?.toggleFormat(format);
  }

  insertTable(): void {
    this.view()?.insertTable();
  }

  insertImage(): void {
    this.view()?.insertImage();
  }

  insertDocument(): void {
    this.view()?.insertDocument();
  }

  insertTimeNote(): void {
    this.view()?.insertTimeNote();
  }

  /** The PDF in the overlay (spec 000863). */
  protected readonly shownDocument = signal<ShownDocument | null>(null);

  protected openDocument(ref: MarkdownDocumentRef): void {
    this.shownDocument.set({ name: ref.name, url: ref.src });
  }

  /**
   * `::` opens the Paperless search only for a person with `paperless.use` and while the
   * part is on; else the text stays plain (§F/integrations/paperless/002527).
   */
  private readonly paperlessOn = toSignal(inject(PaperlessService).insertOn(), { initialValue: false });
  protected readonly insertTrigger = computed(() => (this.paperlessOn() ? PAPERLESS_PREFIX : null));
  protected readonly paperlessOpen = signal(false);

  /** The copy of the picked document goes to the place of the `::`. */
  protected insertCopy(copy: PaperlessCopy): void {
    this.view()?.insertDocumentRef({ src: copy.url, name: copy.name });
  }

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
