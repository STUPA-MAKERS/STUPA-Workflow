import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';

let nextId = 0;

/**
 * True when a file matches an `accept` list (".pdf, image/*, application/xml").
 *
 * The browser filters the picker by `accept`, but not a drop, so a drop runs through
 * this. An empty list accepts every file. The server checks the type again in any case.
 */
export function acceptsFile(file: File, accept: string): boolean {
  const tokens = accept
    .split(',')
    .map((t) => t.trim().toLowerCase())
    .filter((t) => t.length > 0);
  if (tokens.length === 0) return true;
  const name = file.name.toLowerCase();
  const type = (file.type || '').toLowerCase();
  return tokens.some((t) => {
    if (t.startsWith('.')) return name.endsWith(t);
    if (t.endsWith('/*')) return type.startsWith(t.slice(0, -1));
    return type === t;
  });
}

/**
 * A dashed area to drop files on, with a button that opens the file picker.
 *
 * The button is the keyboard path: Tab to it, Enter or Space opens the picker. A click
 * elsewhere on the area opens the picker too. The page passes the visible text (`label`,
 * `hint`, `buttonLabel`); the button is described by the label and the hint.
 *
 * `files` emits the accepted files of a drop or a pick, `rejected` the dropped files that
 * do not match `accept`.
 */
@Component({
  selector: 'app-file-drop-zone',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  templateUrl: './file-drop-zone.component.html',
  styleUrl: './file-drop-zone.component.scss',
})
export class FileDropZoneComponent {
  /** The main line, for example "Dateien hierher ziehen oder auswählen". */
  readonly label = input.required<string>();
  /** The rules, for example "PDF, Bilder · bis 10 MB je Datei". */
  readonly hint = input<string | null>(null);
  /** The text of the button, for example "Auswählen". */
  readonly buttonLabel = input.required<string>();
  /** The `accept` list of the file input. Empty accepts every file. */
  readonly accept = input('');
  readonly multiple = input(true);
  readonly disabled = input(false);

  readonly files = output<File[]>();
  readonly rejected = output<File[]>();

  protected readonly id = `file-drop-${nextId++}`;
  protected readonly over = signal(false);

  private readonly picker = viewChild.required<ElementRef<HTMLInputElement>>('picker');
  /** dragenter and dragleave also fire for the children; count them. */
  private depth = 0;

  protected openPicker(): void {
    if (!this.disabled()) this.picker().nativeElement.click();
  }

  /**
   * A click on the area itself opens the picker. The button has its own click, and the
   * click that `openPicker` sends to the hidden input bubbles up here too.
   */
  protected onAreaClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).closest('button, input')) return;
    this.openPicker();
  }

  protected onDragEnter(event: DragEvent): void {
    event.preventDefault();
    if (this.disabled()) return;
    this.depth++;
    this.over.set(true);
  }

  protected onDragOver(event: DragEvent): void {
    // Without this the browser opens the file instead of dropping it here.
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = this.disabled() ? 'none' : 'copy';
  }

  protected onDragLeave(): void {
    this.depth = Math.max(0, this.depth - 1);
    if (this.depth === 0) this.over.set(false);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.depth = 0;
    this.over.set(false);
    if (this.disabled()) return;
    let dropped = Array.from(event.dataTransfer?.files ?? []);
    if (!this.multiple()) dropped = dropped.slice(0, 1);
    this.emit(dropped);
  }

  protected onPick(): void {
    const input = this.picker().nativeElement;
    this.emit(Array.from(input.files ?? []));
    // Clear it, so picking the same file again fires `change` again.
    input.value = '';
  }

  private emit(list: File[]): void {
    const ok = list.filter((f) => acceptsFile(f, this.accept()));
    const bad = list.filter((f) => !ok.includes(f));
    if (ok.length > 0) this.files.emit(ok);
    if (bad.length > 0) this.rejected.emit(bad);
  }
}
