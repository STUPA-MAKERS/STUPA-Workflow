import { ChangeDetectionStrategy, Component, HostBinding, Input } from '@angular/core';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';
export type ButtonSize = 'sm' | 'md' | 'lg';

/** Basis-Button des UI-Kits. Clean/minimal, CD-Tokens, a11y-Fokus. */
@Component({
  selector: 'app-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './button.component.html',
  styleUrl: './button.component.scss',
})
export class ButtonComponent {
  @Input() variant: ButtonVariant = 'primary';
  /** Frei wählbare Hintergrundfarbe (Hex); überschreibt die Variante (#flow). */
  @Input() color: string | null = null;
  @Input() size: ButtonSize = 'md';
  @Input() type: 'button' | 'submit' | 'reset' = 'button';
  @Input() disabled = false;
  @Input() loading = false;
  /** Quadratischer Icon-Button (gleiche Höhe/Breite) für einzelne Glyphs (✕ ↑ ↓). */
  @Input() iconOnly = false;
  /** Volle Breite des Containers (gestapelte Aktionen gleicher Breite). */
  @Input() @HostBinding('class.btn-block') block = false;
  /** Barrierefreier Name — Pflicht für Icon-Buttons ohne sichtbaren Text. */
  @Input() ariaLabel = '';
  /** Hover-Tooltip; bei Icon-Buttons fällt er automatisch auf `ariaLabel` zurück (#47). */
  @Input() title = '';

  /** Tooltip-Text: explizit gesetzt, sonst für Icon-Buttons der `ariaLabel`. */
  protected tooltip(): string | null {
    return this.title || (this.iconOnly ? this.ariaLabel : '') || null;
  }

  /** Lesbare Textfarbe (schwarz/weiß) zur gewählten `color` per WCAG-Luminanz. */
  protected contrastColor(): string {
    const hex = (this.color ?? '').trim().replace('#', '');
    const full =
      hex.length === 3
        ? hex
            .split('')
            .map((c) => c + c)
            .join('')
        : hex;
    if (full.length !== 6) return '#ffffff';
    const channel = (i: number) => {
      const v = parseInt(full.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    };
    const lum = 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
    return lum > 0.4 ? '#111111' : '#ffffff';
  }
}
