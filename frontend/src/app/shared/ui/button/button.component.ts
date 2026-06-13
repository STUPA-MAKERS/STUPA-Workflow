import { ChangeDetectionStrategy, Component, HostBinding, Input } from '@angular/core';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success';
export type ButtonSize = 'sm' | 'md' | 'lg';

/** Basis-Button des UI-Kits. Clean/minimal, CD-Tokens, a11y-Fokus. */
@Component({
  selector: 'app-button',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      [type]="type"
      [disabled]="disabled || loading"
      [attr.aria-busy]="loading ? 'true' : null"
      [attr.aria-label]="ariaLabel || null"
      [attr.title]="tooltip()"
      [class]="'btn btn--' + variant + ' btn--' + size + (iconOnly ? ' btn--icon' : '')"
      [class.btn--custom]="!!color"
      [style.background]="color || null"
      [style.color]="color ? contrastColor() : null"
    >
      @if (loading) {
        <span class="btn__spinner" aria-hidden="true"></span>
      }
      <span class="btn__label"><ng-content /></span>
    </button>
  `,
  styles: [
    `
      :host {
        display: inline-flex;
      }
      /* Volle Breite (z. B. gestapelte Aktionen): Host + Button strecken. */
      :host(.btn-block) {
        display: flex;
      }
      :host(.btn-block) .btn {
        width: 100%;
      }
      .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: var(--space-2);
        font-weight: var(--fw-semibold);
        line-height: 1;
        border: var(--border-width) solid transparent;
        border-radius: var(--radius-md);
        cursor: pointer;
        white-space: nowrap;
        max-width: 100%;
        min-width: 0;
        transition:
          background-color var(--motion-fast) var(--ease-standard),
          color var(--motion-fast) var(--ease-standard),
          border-color var(--motion-fast) var(--ease-standard);
      }
      .btn:disabled {
        opacity: 0.55;
        cursor: not-allowed;
      }
      .btn--sm {
        padding: var(--space-2) var(--space-3);
        font-size: var(--fs-sm);
      }
      .btn--md {
        padding: var(--space-3) var(--space-5);
        font-size: var(--fs-md);
      }
      .btn--lg {
        padding: var(--space-4) var(--space-6);
        font-size: var(--fs-lg);
      }
      /* Quadratischer Icon-Button: gleiche H/B, zentriertes Glyph. */
      .btn--icon {
        aspect-ratio: 1;
        padding: var(--space-2);
        line-height: 1;
      }
      .btn--icon.btn--sm {
        padding: var(--space-1) var(--space-2);
      }
      .btn--primary {
        background: var(--color-primary);
        color: var(--color-on-primary);
      }
      .btn--primary:hover:not(:disabled) {
        background: var(--color-primary-hover);
      }
      .btn--primary:active:not(:disabled) {
        background: var(--color-primary-active);
      }
      .btn--secondary {
        background: var(--color-surface);
        color: var(--color-text);
        border-color: var(--color-border-strong);
      }
      .btn--secondary:hover:not(:disabled) {
        background: var(--color-surface-sunken);
        border-color: var(--color-text-muted);
      }
      .btn--secondary:active:not(:disabled) {
        background: var(--color-border);
      }
      .btn--ghost {
        background: transparent;
        color: var(--color-primary);
      }
      .btn--ghost:hover:not(:disabled) {
        background: var(--color-primary-subtle);
      }
      .btn--ghost:active:not(:disabled) {
        background: var(--color-primary-subtle);
        color: var(--color-primary-active);
      }
      .btn--danger {
        background: var(--color-danger);
        color: var(--color-text-inverse);
      }
      .btn--danger:hover:not(:disabled) {
        filter: brightness(1.08);
      }
      .btn--danger:active:not(:disabled) {
        filter: brightness(0.94);
      }
      .btn--success {
        background: var(--color-success);
        color: var(--color-text-inverse);
      }
      .btn--success:hover:not(:disabled) {
        filter: brightness(1.08);
      }
      .btn--success:active:not(:disabled) {
        filter: brightness(0.94);
      }
      /* Frei wählbare Farbe (#flow): Hintergrund kommt inline, Hover/Active wie danger/success. */
      .btn--custom:hover:not(:disabled) {
        filter: brightness(1.08);
      }
      .btn--custom:active:not(:disabled) {
        filter: brightness(0.94);
      }
      /* Überlange Beschriftungen (z. B. Flow-Transition-Labels) laufen nicht aus dem
         Button heraus, sondern werden mit … abgeschnitten. */
      .btn__label {
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
        max-width: 100%;
        /* line-height des Buttons ist 1 (kompakt); für den Text etwas mehr Raum,
           sonst schneidet overflow:hidden Unterlängen (g/p/ü) unten ab (#btn-clip). */
        line-height: 1.3;
      }
      .btn__spinner {
        width: 1em;
        height: 1em;
        border: 2px solid currentColor;
        border-right-color: transparent;
        border-radius: var(--radius-pill);
        animation: btn-spin 0.6s linear infinite;
      }
      @keyframes btn-spin {
        to {
          transform: rotate(360deg);
        }
      }
    `,
  ],
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
