import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type IconName =
  | 'sun'
  | 'moon'
  | 'language'
  | 'edit'
  | 'delete'
  | 'add'
  | 'remove'
  | 'members'
  | 'roles'
  | 'chevron-down'
  | 'power';

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
        @case ('edit') {
          <path d="M12 20h9" />
          <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
        }
        @case ('delete') {
          <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />
        }
        @case ('add') {
          <path d="M12 5v14M5 12h14" />
        }
        @case ('remove') {
          <path d="M18 6 6 18M6 6l12 12" />
        }
        @case ('members') {
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
          <circle cx="9" cy="7" r="4" />
          <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
        }
        @case ('roles') {
          <circle cx="12" cy="8" r="6" />
          <path d="M15.5 12.9 17 22l-5-3-5 3 1.5-9.1" />
        }
        @case ('chevron-down') {
          <path d="M6 9l6 6 6-6" />
        }
        @case ('power') {
          <path d="M18.4 6.6a9 9 0 1 1-12.8 0M12 2v8" />
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
