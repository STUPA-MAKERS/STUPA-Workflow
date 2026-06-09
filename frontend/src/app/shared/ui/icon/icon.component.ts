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
  | 'user'
  | 'chevron-down'
  | 'power'
  | 'filter'
  | 'check'
  | 'building'
  | 'euro'
  | 'form'
  | 'flow'
  | 'palette'
  | 'webhook'
  | 'bell'
  | 'audit'
  | 'clock'
  | 'export';

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
        @case ('user') {
          <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        }
        @case ('chevron-down') {
          <path d="M6 9l6 6 6-6" />
        }
        @case ('power') {
          <path d="M18.4 6.6a9 9 0 1 1-12.8 0M12 2v8" />
        }
        @case ('filter') {
          <path d="M3 4h18l-7 8v6l-4 2v-8z" />
        }
        @case ('check') {
          <path d="M20 6 9 17l-5-5" />
        }
        @case ('building') {
          <path d="M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2" />
        }
        @case ('euro') {
          <path d="M17 5a7 7 0 1 0 0 14M4 10h9M4 14h7" />
        }
        @case ('form') {
          <path d="M5 3h11l4 4v14a0 0 0 0 1 0 0H5a0 0 0 0 1 0 0z" />
          <path d="M15 3v5h5M8 13h8M8 17h6" />
        }
        @case ('flow') {
          <circle cx="6" cy="6" r="3" />
          <circle cx="6" cy="18" r="3" />
          <circle cx="18" cy="12" r="3" />
          <path d="M9 6h3a3 3 0 0 1 3 3v0M9 18h3a3 3 0 0 0 3-3v0" />
        }
        @case ('palette') {
          <path d="M12 3a9 9 0 1 0 0 18 2 2 0 0 0 2-2 2 2 0 0 1 2-2h1a4 4 0 0 0 4-4 9 9 0 0 0-9-8z" />
          <circle cx="7.5" cy="10.5" r="1" />
          <circle cx="12" cy="7.5" r="1" />
          <circle cx="16.5" cy="10.5" r="1" />
        }
        @case ('webhook') {
          <path d="M9 7a3 3 0 1 1 4.2 2.7L16 15M15 17a3 3 0 1 1-2.5-3l3-5M9 17a3 3 0 1 0 3 3M9 17H5.5" />
        }
        @case ('bell') {
          <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
        }
        @case ('audit') {
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6M9 13l2 2 4-4" />
        }
        @case ('clock') {
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        }
        @case ('export') {
          <path d="M12 3v12M8 7l4-4 4 4M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
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
