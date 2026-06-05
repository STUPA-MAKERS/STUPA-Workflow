import { Injectable, signal } from '@angular/core';

export type ToastVariant = 'info' | 'success' | 'warning' | 'danger';

export interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

let nextId = 0;

/** Globaler Toast-Hub. Komponenten rufen `show()`, der Container rendert. */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly _toasts = signal<Toast[]>([]);
  readonly toasts = this._toasts.asReadonly();

  /** Zeigt einen Toast; `timeout=0` deaktiviert das automatische Schließen. */
  show(message: string, variant: ToastVariant = 'info', timeout = 4000): number {
    const id = nextId++;
    this._toasts.update((list) => [...list, { id, message, variant }]);
    if (timeout > 0) setTimeout(() => this.dismiss(id), timeout);
    return id;
  }

  success(message: string): number {
    return this.show(message, 'success');
  }
  error(message: string): number {
    return this.show(message, 'danger');
  }

  dismiss(id: number): void {
    this._toasts.update((list) => list.filter((t) => t.id !== id));
  }
}
