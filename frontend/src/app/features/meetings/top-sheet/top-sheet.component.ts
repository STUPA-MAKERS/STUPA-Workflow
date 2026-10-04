import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { AgendaItem, Meeting, Protocol, Uuid } from '@core/api/models';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';
import {
  MarkdownEditorComponent,
  type MarkdownFormat,
} from '@stupa-makers/ui-kit/markdown-editor';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import type { StatusKind } from '@shared/status-kind.util';
import { resolveI18n } from '../meetings-display.util';

/** The autosave state of the text of the open item. */
export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

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

/**
 * The sheet of the open agenda item: "TOP 3 · Antrag", the title, "Antrag öffnen", the
 * format bar with the save state, and the Markdown editor of the text.
 *
 * Only the minute-taker types (`editable`); everybody else with write access reads the
 * same sheet, and its foot says who keeps the minutes. The foot also carries the state of
 * the protocol and its PDF links.
 */
@Component({
  selector: 'app-top-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent, MarkdownEditorComponent, StatusTextComponent],
  templateUrl: './top-sheet.component.html',
  styleUrl: './top-sheet.component.scss',
})
export class TopSheetComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  readonly protocol = input.required<Protocol | null>();
  readonly top = input.required<AgendaItem | null>();
  /** The 0-based index of the open item. */
  readonly topIndex = input.required<number>();
  /**
   * The minutes may be written here: a protocol exists, it is not locked, and the viewer
   * keeps the minutes (or nobody does and the viewer may write).
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

  readonly bodyChange = output<{ itemId: Uuid; body: string }>();

  protected readonly tools = TOOLS;

  /** "TOP 3 · Antrag". */
  protected kindLine(t: AgendaItem): string {
    const kind = t.applicationId ? 'meetings.agenda.kindApplication' : 'meetings.agenda.kindFreetext';
    return `${this.i18n.translate('meetings.agenda.top', { n: this.topIndex() + 1 })} · ${this.i18n.translate(kind)}`;
  }

  /** The state of the application of the item, in the language of the page. */
  protected readonly stateLabel = computed(() =>
    resolveI18n(this.top()?.stateLabel, this.i18n.locale()),
  );

  /** The state of the protocol as status text. */
  protected protocolState(p: Protocol): { kind: StatusKind; key: TranslationKey } {
    if (p.isFinal) return { kind: 'accent', key: 'meetings.protocol.final' };
    if (p.status === 'rendering') return { kind: 'warn', key: 'meetings.protocol.rendering' };
    return { kind: 'neutral', key: 'meetings.protocol.draft' };
  }

  /**
   * Why a closed meeting shows no finalize to this person: the right is missing. Every
   * other state the status text and the header already say. `null` when nothing to say.
   */
  protected protocolHint(p: Protocol): TranslationKey | null {
    const m = this.meeting();
    if (p.isFinal || p.status === 'rendering' || m.status !== 'closed') return null;
    return m.canWrite && !m.canFinalize ? 'meetings.protocol.finalizeNeedsRight' : null;
  }
}
