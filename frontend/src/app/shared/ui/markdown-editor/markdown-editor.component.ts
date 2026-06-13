import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  type OnDestroy,
  effect,
  input,
  output,
  viewChild,
} from '@angular/core';
import { Editor } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { Markdown } from 'tiptap-markdown';

/**
 * WYSIWYG-Markdown-Editor (Tiptap) im Stil von Nextcloud Collectives: man tippt
 * Markdown-Kürzel (`# `, `- `, `**fett**`) und sieht **sofort** das gerenderte
 * Ergebnis — kein separater Vorschau-Bereich. Ein- und Ausgabe sind Markdown.
 *
 * Imperativ angebunden: Tiptap mountet in das Host-`div`. ``docKey`` identifiziert
 * das aktuell editierte Dokument (z. B. ein TOP); ändert es sich, wird der Inhalt
 * neu geladen, ohne die Eingabe während des Tippens zu überschreiben.
 */
@Component({
  selector: 'app-markdown-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './markdown-editor.component.html',
  styleUrl: './markdown-editor.component.scss',
})
export class MarkdownEditorComponent implements OnDestroy {
  /** Anfangs-/Soll-Markdown des aktuellen Dokuments. */
  readonly value = input<string>('');
  /** Dokument-Schlüssel: ändert er sich, wird ``value`` neu in den Editor geladen. */
  readonly docKey = input<string>('');
  readonly disabled = input<boolean>(false);
  readonly placeholder = input<string>('');

  /** Emittiert das serialisierte Markdown bei jeder Änderung. */
  readonly valueChange = output<string>();

  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('host');
  private editor: Editor | null = null;
  private loadedKey: string | null = null;
  private emitting = false;

  constructor() {
    // Editor lazy aufbauen, sobald das Host-Element existiert, und auf
    // docKey/disabled reagieren.
    effect(() => {
      const el = this.host().nativeElement;
      const key = this.docKey();
      const disabled = this.disabled();
      if (!this.editor) {
        this.editor = new Editor({
          element: el,
          extensions: [StarterKit, Markdown.configure({ html: false })],
          content: this.value(),
          editable: !disabled,
          editorProps: { attributes: { 'data-placeholder': this.placeholder() } },
          onUpdate: ({ editor }) => {
            if (this.emitting) return;
            this.valueChange.emit(this.toMarkdown(editor));
          },
        });
        this.loadedKey = key;
        return;
      }
      this.editor.setEditable(!disabled);
      // Dokument gewechselt → Inhalt neu laden (ohne valueChange auszulösen).
      if (key !== this.loadedKey) {
        this.loadedKey = key;
        this.emitting = true;
        this.editor.commands.setContent(this.value());
        this.emitting = false;
      }
    });
  }

  ngOnDestroy(): void {
    this.editor?.destroy();
    this.editor = null;
  }

  /** Markdown aus dem Tiptap-Markdown-Storage holen (untypisiert in Tiptap). */
  private toMarkdown(editor: Editor): string {
    const storage = editor.storage as unknown as Record<
      string,
      { getMarkdown?: () => string }
    >;
    return storage['markdown']?.getMarkdown?.() ?? '';
  }
}
