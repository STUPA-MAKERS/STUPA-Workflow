import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type IconName = 'sun' | 'moon' | 'language';

/**
 * Inline-SVG-Icon-Set (#80). Saubere, konsistente `currentColor`-Icons (folgen
 * also Text-/Theme-Farbe automatisch, Dark/Light). Bewusst inline statt externer
 * Assets: keine zusätzlichen Requests, kein SVG-XSS-Vektor (vgl. img-only-Logo-
 * Kontrakt). Dekorativ (`aria-hidden`) — der barrierefreie Name kommt vom
 * umschließenden Control (`aria-label`).
 */
@Component({
  selector: 'app-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <svg
      class="icon"
      [attr.width]="size"
      [attr.height]="size"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      @switch (name) {
        @case ('sun') {
          <circle cx="12" cy="12" r="4" />
          <path
            d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"
          />
        }
        @case ('moon') {
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        }
        @case ('language') {
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3c2.5 2.5 2.5 15.5 0 18M12 3c-2.5 2.5-2.5 15.5 0 18" />
        }
      }
    </svg>
  `,
  styles: [
    `
      :host {
        display: inline-flex;
        line-height: 0;
      }
      .icon {
        display: block;
      }
    `,
  ],
})
export class IconComponent {
  @Input() name: IconName = 'sun';
  /** Kantenlänge in px (quadratisch). */
  @Input() size = 20;
}
