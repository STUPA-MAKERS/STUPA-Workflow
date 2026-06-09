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
  template: `<div #host class="mde__host" [class.mde__host--disabled]="disabled()"></div>`,
  styles: [
    `
      :host {
        display: block;
      }
      .mde__host {
        min-height: 16rem;
        padding: var(--space-3) var(--space-4);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        overflow-wrap: anywhere;
      }
      .mde__host--disabled {
        opacity: 0.7;
      }
      .mde__host :first-child {
        margin-top: 0;
      }
      .mde__host .ProseMirror {
        outline: none;
        min-height: 14rem;
        line-height: 1.55;
      }
      .mde__host .ProseMirror h1 {
        font-size: var(--fs-xl);
      }
      .mde__host .ProseMirror h2 {
        font-size: var(--fs-lg);
      }
      .mde__host .ProseMirror h3 {
        font-size: var(--fs-md);
        font-weight: var(--fw-semibold);
      }
      .mde__host .ProseMirror ul,
      .mde__host .ProseMirror ol {
        padding-left: var(--space-5);
        margin: var(--space-2) 0;
      }
      .mde__host .ProseMirror blockquote {
        margin: var(--space-2) 0;
        padding-left: var(--space-3);
        border-left: 3px solid var(--color-border-strong);
        color: var(--color-text-muted);
      }
      .mde__host .ProseMirror code {
        background: var(--color-bg);
        padding: 0 var(--space-1);
        border-radius: var(--radius-sm);
        font-size: 0.9em;
      }
      .mde__host .ProseMirror pre {
        background: var(--color-bg);
        padding: var(--space-3);
        border-radius: var(--radius-md);
        overflow-x: auto;
      }
      .mde__host .ProseMirror hr {
        border: 0;
        border-top: var(--border-width) solid var(--color-border);
        margin: var(--space-3) 0;
      }
      /* Platzhalter, wenn leer (Tiptap setzt is-editor-empty auf den ersten Knoten). */
      .mde__host .ProseMirror p.is-editor-empty:first-child::before {
        content: attr(data-placeholder);
        color: var(--color-text-muted);
        float: left;
        height: 0;
        pointer-events: none;
      }
    `,
  ],
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
