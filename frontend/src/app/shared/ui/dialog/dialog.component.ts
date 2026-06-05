import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
} from '@angular/core';

let nextId = 0;

/** Modaler Dialog. Schließt per Backdrop-Klick, Schließen-Button oder ESC. */
@Component({
  selector: 'app-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open) {
      <div class="dialog__backdrop" (click)="onBackdrop($event)">
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          [attr.aria-labelledby]="titleId"
          (click)="$event.stopPropagation()"
        >
          <header class="dialog__header">
            <h2 class="dialog__title" [id]="titleId">{{ title }}</h2>
            <button
              type="button"
              class="dialog__close"
              [attr.aria-label]="closeLabel"
              (click)="close()"
            >
              ✕
            </button>
          </header>
          <div class="dialog__body"><ng-content /></div>
          <footer class="dialog__footer"><ng-content select="[dialog-footer]" /></footer>
        </div>
      </div>
    }
  `,
  styles: [
    `
      .dialog__backdrop {
        position: fixed;
        inset: 0;
        z-index: var(--z-dialog);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--space-5);
        background: rgba(0, 18, 10, 0.55);
      }
      .dialog {
        width: 100%;
        max-width: 32rem;
        background: var(--color-bg-elevated);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-lg);
        display: flex;
        flex-direction: column;
        max-height: 85dvh;
      }
      .dialog__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-4);
        padding: var(--space-5) var(--space-5) var(--space-3);
      }
      .dialog__title {
        font-size: var(--fs-xl);
      }
      .dialog__close {
        background: transparent;
        border: 0;
        cursor: pointer;
        font-size: var(--fs-lg);
        color: var(--color-text-muted);
        border-radius: var(--radius-sm);
        padding: var(--space-1);
      }
      .dialog__body {
        padding: 0 var(--space-5);
        overflow-y: auto;
      }
      .dialog__footer {
        display: flex;
        justify-content: flex-end;
        gap: var(--space-3);
        padding: var(--space-5);
      }
      .dialog__footer:empty {
        display: none;
      }
    `,
  ],
})
export class DialogComponent {
  @Input() open = false;
  @Input() title = '';
  @Input() closeLabel = 'Schließen';
  @Output() closed = new EventEmitter<void>();

  readonly titleId = `app-dialog-title-${nextId++}`;

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open) this.close();
  }

  onBackdrop(_event: MouseEvent): void {
    this.close();
  }

  close(): void {
    this.open = false;
    this.closed.emit();
  }
}
