import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  OnChanges,
  Output,
  SimpleChanges,
  ViewChild,
} from '@angular/core';

let nextId = 0;

/**
 * Modaler Dialog. Schließt per Backdrop-Klick, Schließen-Button oder ESC.
 *
 * a11y (T-43, WCAG 2.1.2/2.4.3): Beim Öffnen wandert der Fokus in den Dialog,
 * Tab/Shift+Tab werden im Dialog gefangen (Focus-Trap), beim Schließen kehrt der
 * Fokus auf das auslösende Element zurück. `aria-modal`/`role="dialog"` +
 * `aria-labelledby` sind gesetzt.
 */
@Component({
  selector: 'app-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open) {
      <div class="dialog__backdrop" (click)="onBackdrop($event)">
        <div
          #pane
          class="dialog"
          [class.dialog--lg]="size === 'lg'"
          role="dialog"
          aria-modal="true"
          tabindex="-1"
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
      .dialog--lg {
        max-width: 44rem;
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

      /* Mobile (≤768px): Dialog als Sheet — volle Breite, am unteren Rand,
         mehr nutzbare Höhe. Desktop unverändert. */
      @media (max-width: 768px) {
        .dialog__backdrop {
          align-items: flex-end;
          padding: 0;
        }
        .dialog {
          max-width: none;
          max-height: 92dvh;
          border-radius: var(--radius-lg) var(--radius-lg) 0 0;
          border-bottom: 0;
        }
        .dialog__header {
          padding: var(--space-4) var(--space-4) var(--space-2);
        }
        .dialog__body {
          padding: 0 var(--space-4);
        }
        .dialog__footer {
          padding: var(--space-4);
          flex-wrap: wrap;
        }
      }
    `,
  ],
})
export class DialogComponent implements OnChanges {
  @Input() open = false;
  @Input() title = '';
  @Input() closeLabel = 'Schließen';
  /** Breite: 'md' (32rem, Default) oder 'lg' (44rem, z. B. Charts). */
  @Input() size: 'md' | 'lg' = 'md';
  @Output() closed = new EventEmitter<void>();

  @ViewChild('pane') private pane?: ElementRef<HTMLElement>;

  readonly titleId = `app-dialog-title-${nextId++}`;

  /** Element, das vor dem Öffnen den Fokus hatte — für Restore beim Schließen. */
  private previouslyFocused: HTMLElement | null = null;

  ngOnChanges(changes: SimpleChanges): void {
    const c = changes['open'];
    if (!c || c.firstChange) {
      if (this.open) this.captureAndFocus();
      return;
    }
    if (!c.previousValue && c.currentValue) this.captureAndFocus();
    else if (c.previousValue && !c.currentValue) this.restoreFocus();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open) this.close();
  }

  /** Tab/Shift+Tab im Dialog halten (Focus-Trap). */
  @HostListener('document:keydown', ['$event'])
  onKeydown(event: KeyboardEvent): void {
    if (!this.open || event.key !== 'Tab') return;
    const pane = this.pane?.nativeElement;
    if (!pane) return;
    const focusables = this.focusable(pane);
    if (focusables.length === 0) {
      event.preventDefault();
      pane.focus();
      return;
    }
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === pane)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  onBackdrop(_event: MouseEvent): void {
    this.close();
  }

  close(): void {
    this.open = false;
    this.restoreFocus();
    this.closed.emit();
  }

  /** Vorherigen Fokus merken und Fokus in den Dialog setzen (nach Render). */
  private captureAndFocus(): void {
    this.previouslyFocused = (document.activeElement as HTMLElement) ?? null;
    queueMicrotask(() => {
      const pane = this.pane?.nativeElement;
      if (!pane) return;
      const focusables = this.focusable(pane);
      (focusables[0] ?? pane).focus();
    });
  }

  private restoreFocus(): void {
    const target = this.previouslyFocused;
    this.previouslyFocused = null;
    if (target && typeof target.focus === 'function') target.focus();
  }

  private focusable(root: HTMLElement): HTMLElement[] {
    const selector = [
      'a[href]',
      'button:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',');
    return Array.from(root.querySelectorAll<HTMLElement>(selector));
  }
}
