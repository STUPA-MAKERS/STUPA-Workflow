import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  EventEmitter,
  HostListener,
  Input,
  OnChanges,
  OnDestroy,
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
  templateUrl: './dialog.component.html',
  styleUrl: './dialog.component.scss',
})
export class DialogComponent implements OnChanges, OnDestroy {
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

  /** Body-Scroll-Sperre: gemerkter vorheriger overflow-Wert für den Restore. */
  private prevBodyOverflow: string | null = null;
  // Drag-to-dismiss (Mobile-Sheet, #14).
  private dragStartY = 0;
  private dragStartT = 0;
  private dragging = false;
  private dragDy = 0;

  ngOnChanges(changes: SimpleChanges): void {
    const c = changes['open'];
    if (!c || c.firstChange) {
      if (this.open) {
        this.captureAndFocus();
        this.lockScroll();
      }
      return;
    }
    if (!c.previousValue && c.currentValue) {
      this.captureAndFocus();
      this.lockScroll();
    } else if (c.previousValue && !c.currentValue) {
      this.restoreFocus();
      this.unlockScroll();
    }
  }

  ngOnDestroy(): void {
    // Falls der Dialog im offenen Zustand zerstört wird: Scroll-Sperre lösen.
    this.unlockScroll();
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

  // --- Drag-to-dismiss (Mobile-Sheet, #14) -----------------------------------
  onDragStart(event: TouchEvent): void {
    if (event.touches.length !== 1) return;
    this.dragging = true;
    this.dragStartY = event.touches[0].clientY;
    this.dragStartT = event.timeStamp;
    this.dragDy = 0;
    const pane = this.pane?.nativeElement;
    if (pane) pane.style.transition = 'none';
  }

  onDragMove(event: TouchEvent): void {
    if (!this.dragging) return;
    // Nur nach unten ziehen (kein „Hochziehen").
    this.dragDy = Math.max(0, event.touches[0].clientY - this.dragStartY);
    const pane = this.pane?.nativeElement;
    if (pane) pane.style.transform = `translateY(${this.dragDy}px)`;
  }

  onDragEnd(event: TouchEvent): void {
    if (!this.dragging) return;
    this.dragging = false;
    const pane = this.pane?.nativeElement;
    if (pane) pane.style.transition = '';
    const dt = event.timeStamp - this.dragStartT;
    const velocity = this.dragDy / Math.max(1, dt); // px/ms
    // Flick (schnelle Abwärtsbewegung) ODER deutlicher Weg → schließen.
    if (velocity > 0.5 || this.dragDy > 120) {
      this.close();
    } else if (pane) {
      pane.style.transform = '';
    }
  }

  close(): void {
    this.open = false;
    const pane = this.pane?.nativeElement;
    if (pane) pane.style.transform = '';
    this.restoreFocus();
    this.unlockScroll();
    this.closed.emit();
  }

  private lockScroll(): void {
    if (this.prevBodyOverflow !== null) return;
    this.prevBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }

  private unlockScroll(): void {
    if (this.prevBodyOverflow === null) return;
    document.body.style.overflow = this.prevBodyOverflow;
    this.prevBodyOverflow = null;
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
