import { Directive, effect, input, output, signal, untracked } from '@angular/core';

/** A drag that carries files from the desktop, not a text selection or a dragged row. */
export function isFileDrag(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files');
}

/**
 * Counts the drag of files over one element.
 *
 * dragenter and dragleave also fire for every child the pointer crosses, so a plain flag
 * flickers. `active` is true from the first enter until the last leave or the drop. A file
 * drag that this element takes stops here: a page and a panel inside it never both show
 * their overlay, and a drop uploads once.
 */
export class FileDragTracker {
  readonly active = signal(false);
  private depth = 0;

  /**
   * `accepts` is read at each event: the element takes files only while it is true. It
   * gets the event, so a host can leave a drag over one of its children alone.
   */
  constructor(private readonly accepts: (event: DragEvent) => boolean) {}

  /** The data of a file drag that this element takes, else null. */
  private take(event: DragEvent): DataTransfer | null {
    if (!isFileDrag(event) || !this.accepts(event)) return null;
    // Without `preventDefault` on dragover the browser opens the file in the tab.
    event.preventDefault();
    event.stopPropagation();
    // `isFileDrag` read the types of this object.
    return event.dataTransfer as DataTransfer;
  }

  enter(event: DragEvent): void {
    if (!this.take(event)) return;
    this.depth++;
    this.active.set(true);
  }

  over(event: DragEvent): void {
    const data = this.take(event);
    if (data) data.dropEffect = 'copy';
  }

  leave(event: DragEvent): void {
    if (!this.take(event)) return;
    this.depth = Math.max(0, this.depth - 1);
    if (this.depth === 0) this.active.set(false);
  }

  /** The dropped files, or null when this element does not take the drop. */
  drop(event: DragEvent): File[] | null {
    const data = this.take(event);
    this.reset();
    return data ? Array.from(data.files) : null;
  }

  /** Hide the overlay, for example when the element stops taking files during a drag. */
  reset(): void {
    this.depth = 0;
    this.active.set(false);
  }
}

/**
 * Makes its host a drop target for files: `appFileDrop` emits the dropped files.
 *
 * `appFileDropEnabled` gates it (a permission, a state lock); while it is false, a file
 * drag passes through to the elements around the host. `appFileDropExclude` is a CSS
 * selector of children that take their own drops (an `app-file-drop-zone`): a drag over
 * one of them is not counted, so the host's overlay hides there and a drop imports once. `active` (exported as `appFileDrop`)
 * is true while files hover over the host; the host shows `app-drop-overlay` then.
 * The checks of the file picker (count, size, type) stay with the host's upload: the drop
 * hands the files to the same method.
 */
@Directive({
  selector: '[appFileDrop]',
  standalone: true,
  exportAs: 'appFileDrop',
  host: {
    '(dragenter)': 'tracker.enter($event)',
    '(dragover)': 'tracker.over($event)',
    '(dragleave)': 'tracker.leave($event)',
    '(drop)': 'onDrop($event)',
  },
})
export class FileDropDirective {
  readonly enabled = input(true, { alias: 'appFileDropEnabled' });
  readonly exclude = input<string | null>(null, { alias: 'appFileDropExclude' });
  readonly dropped = output<File[]>({ alias: 'appFileDrop' });

  protected readonly tracker = new FileDragTracker(
    (event) => this.enabled() && !this.excluded(event),
  );
  readonly active = this.tracker.active.asReadonly();

  constructor() {
    // Turned off during a drag (a sheet opened, the state locked): its leave events pass
    // through now, so the overlay would stay.
    effect(() => {
      if (!this.enabled()) untracked(() => this.tracker.reset());
    });
  }

  /** The drag is over a child that takes its own drops. */
  private excluded(event: DragEvent): boolean {
    const selector = this.exclude();
    const target = event.target;
    return !!selector && target instanceof Element && !!target.closest(selector);
  }

  protected onDrop(event: DragEvent): void {
    const files = this.tracker.drop(event);
    if (files?.length) this.dropped.emit(files);
  }
}
