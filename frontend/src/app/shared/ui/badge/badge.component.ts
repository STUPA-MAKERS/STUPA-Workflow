import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type BadgeVariant = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info';

/** Status-Chip (z. B. Antrags-Status, Vote-Ergebnis). */
@Component({
  selector: 'app-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span
    class="badge"
    [class]="color ? 'badge--custom' : 'badge--' + variant"
    [style.background]="color || null"
    [style.color]="color ? textColor : null"
    ><ng-content
  /></span>`,
  styles: [
    `
      .badge {
        display: inline-flex;
        align-items: center;
        padding: var(--space-1) var(--space-3);
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
        line-height: 1.4;
        border-radius: var(--radius-pill);
        white-space: nowrap;
      }
      .badge--neutral {
        background: var(--color-surface-sunken);
        color: var(--color-text-muted);
      }
      .badge--primary {
        background: var(--color-primary-subtle);
        color: var(--color-primary);
      }
      .badge--success {
        background: var(--color-success-subtle);
        color: var(--color-success);
      }
      .badge--warning {
        background: var(--color-warning-subtle);
        color: var(--color-warning);
      }
      .badge--danger {
        background: var(--color-danger-subtle);
        color: var(--color-danger);
      }
      .badge--info {
        background: var(--color-info-subtle);
        color: var(--color-info);
      }
    `,
  ],
})
export class BadgeComponent {
  @Input() variant: BadgeVariant = 'neutral';

  /**
   * Optionale, frei konfigurierte Hintergrundfarbe (Hex, z. B. Flow-State-Farbe).
   * Ist sie gesetzt, überschreibt sie das Variant-Styling; die Textfarbe wird
   * automatisch lesbar gewählt (dunkler Text auf hellem Grund, sonst weiß).
   */
  @Input() color?: string | null;

  /** Lesbare Textfarbe für {@link color} via Luminanz-Schwelle. */
  get textColor(): string {
    return readableTextColor(this.color) ?? '#ffffff';
  }
}

/**
 * Liefert `#1a1a1a` (dunkel) oder `#ffffff` (weiß) je nach wahrgenommener
 * Helligkeit der gegebenen Hex-Farbe. Gibt `null` bei ungültiger Eingabe.
 */
export function readableTextColor(hex?: string | null): string | null {
  if (!hex) return null;
  let h = hex.trim().replace(/^#/, '');
  if (h.length === 3) {
    h = h
      .split('')
      .map((c) => c + c)
      .join('');
  }
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  // Relative Luminanz (sRGB, schnelle Variante).
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6 ? '#1a1a1a' : '#ffffff';
}
