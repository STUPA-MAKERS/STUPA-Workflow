import {
  ChangeDetectionStrategy,
  Component,
  type TemplateRef,
  effect,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  dockInListDetailBar,
  IconComponent,
  ListDetailBarComponent,
  ListDetailNav,
  MEDIA,
  mediaQuery,
  type StatusKind,
  StatusTextComponent,
} from '@stupa-makers/ui-kit';

/**
 * The head of a meeting view: "Zurück", the title with the status after it, and a quiet
 * sub line. The meeting page and the follow view use it. The controls of the page follow
 * as content.
 *
 * On a phone the head is the bar of the kit (`app-list-detail-bar`), the same bar as on
 * every detail that fills the screen: it stays at the top of the window while the page
 * scrolls, with the back arrow, the title in small type, the status and the sub line as
 * its second line, and the controls of the page as its actions. The head gives itself a
 * `ListDetailNav`, because the meeting views are not inside `app-list-detail`. The page
 * sets `display: contents` on the host there, because a sticky bar sticks only inside
 * its parent box, and the header is only as tall as the bar.
 *
 * The host is the `header` of the page, so the page keeps its frame rules (padding,
 * height, gap, role). The page can set `--mh-title-size` and `--mh-title-line`
 * for the title and `--mh-status-size` for the status.
 *
 * ```html
 * <header appMeetingHead class="mp__head" [heading]="m.title" [statusKind]="status().kind"
 *         [statusText]="status().key | t" [sub]="subLine()" (back)="back.emit()">
 *   <app-row-menu … />
 * </header>
 * ```
 */
@Component({
  // eslint-disable-next-line @angular-eslint/component-selector -- the host is the header of the page, which keeps its frame rules
  selector: 'header[appMeetingHead]',
  standalone: true,
  imports: [
    ButtonComponent,
    IconComponent,
    ListDetailBarComponent,
    NgTemplateOutlet,
    StatusTextComponent,
    TranslatePipe,
  ],
  providers: [ListDetailNav],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './meeting-head.component.html',
  styleUrl: './meeting-head.component.scss',
})
export class MeetingHeadComponent {
  /** The title of the meeting. */
  readonly heading = input.required<string>();
  /** The colour of the status. */
  readonly statusKind = input<StatusKind>('neutral');
  /** The translated status. */
  readonly statusText = input.required<string>();
  /** The sub line, such as the date and the place. `null`: no sub line. */
  readonly sub = input<string | null>(null);
  /** The person pressed "Zurück". */
  readonly back = output<void>();

  /** A phone: the head is the bar of the kit. */
  protected readonly phone = mediaQuery(MEDIA.phone);

  private readonly actions = viewChild<TemplateRef<unknown>>('actions');
  private readonly subtitle = viewChild<TemplateRef<unknown>>('subtitle');

  constructor() {
    const nav = inject(ListDetailNav);
    effect(() => nav.active.set(this.phone()));
    dockInListDetailBar({
      actions: () => this.actions() as TemplateRef<unknown>,
      titled: () => this.actions() !== undefined,
      title: () => null,
      subtitle: () => this.subtitle() ?? null,
    });
  }
}
