import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';

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
  | 'chevron-up'
  | 'power'
  | 'filter'
  | 'check'
  | 'building'
  | 'parliament'
  | 'euro'
  | 'form'
  | 'flow'
  | 'palette'
  | 'webhook'
  | 'bell'
  | 'audit'
  | 'clock'
  | 'export'
  | 'play'
  | 'stop'
  | 'half'
  | 'send'
  | 'repeat'
  | 'menu'
  | 'gear'
  | 'key'
  | 'handshake'
  | 'paperclip'
  | 'upload'
  | 'document'
  | 'chart-pie';

/** Icon-Name → Font-Awesome-Solid-Klasse (#80, FA-Migration). */
const FA: Record<IconName, string> = {
  sun: 'fa-sun',
  moon: 'fa-moon',
  language: 'fa-language',
  edit: 'fa-pen-to-square',
  delete: 'fa-trash',
  add: 'fa-plus',
  remove: 'fa-xmark',
  members: 'fa-users',
  roles: 'fa-user-shield',
  user: 'fa-user',
  'chevron-down': 'fa-chevron-down',
  'chevron-up': 'fa-chevron-up',
  power: 'fa-power-off',
  filter: 'fa-filter',
  check: 'fa-check',
  building: 'fa-building',
  parliament: 'fa-landmark',
  euro: 'fa-euro-sign',
  form: 'fa-clipboard-list',
  flow: 'fa-diagram-project',
  palette: 'fa-palette',
  webhook: 'fa-globe',
  bell: 'fa-bell',
  audit: 'fa-clipboard-check',
  clock: 'fa-clock',
  export: 'fa-file-export',
  play: 'fa-play',
  stop: 'fa-stop',
  half: 'fa-circle-half-stroke',
  send: 'fa-paper-plane',
  repeat: 'fa-repeat',
  menu: 'fa-bars',
  gear: 'fa-gear',
  key: 'fa-key',
  handshake: 'fa-handshake',
  paperclip: 'fa-paperclip',
  upload: 'fa-file-arrow-up',
  document: 'fa-file-lines',
  'chart-pie': 'fa-chart-pie',
};

/**
 * Icon-Komponente (#80). Rendert ein **Font-Awesome**-Solid-Icon (`fa-solid`),
 * gesteuert über einen stabilen, semantischen `name`. Dekorativ
 * (`aria-hidden`) — der barrierefreie Name kommt vom umschließenden Control.
 * `currentColor` folgt der Text-/Theme-Farbe automatisch (Dark/Light).
 */
@Component({
  selector: 'app-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<i class="fa-solid" [class]="faClass()" [style.fontSize.px]="size" aria-hidden="true"></i>`,
  styles: [
    `
      :host {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        line-height: 0;
      }
      i {
        line-height: 1;
      }
    `,
  ],
})
export class IconComponent {
  private readonly _name = signal<IconName>('sun');

  @Input() set name(value: IconName) {
    this._name.set(value);
  }
  /** Kantenlänge in px (Schriftgröße des Glyphs). */
  @Input() size = 18;

  protected readonly faClass = computed(() => FA[this._name()] ?? 'fa-circle-question');
}
