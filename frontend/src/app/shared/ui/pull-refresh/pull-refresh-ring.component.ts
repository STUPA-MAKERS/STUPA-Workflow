import { ChangeDetectionStrategy, Component, ElementRef, inject, viewChild } from '@angular/core';

/** The length of the arc of the ring: 2 π r with r = 11 in a 36-unit box. */
export const RING_LENGTH = 69.1;

/**
 * The ring of a pull to refresh, created by `PullRefreshDirective` beside the rows it
 * pulls. A track in the surface 3 colour and an arc in the accent that fills with the
 * pull, then turns while the list loads. It is for the eye only (`aria-hidden`): the
 * list says `aria-busy` while it loads, and the bar of the app runs.
 *
 * The directive paints it straight into the DOM (`paint`), without change detection,
 * because it moves on every touch move.
 */
@Component({
  selector: 'app-pull-refresh-ring',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { 'aria-hidden': 'true' },
  template: `<svg viewBox="0 0 36 36" width="28" height="28">
    <circle class="ptr__track" cx="18" cy="18" r="11" />
    <circle #arc class="ptr__arc" cx="18" cy="18" r="11" />
  </svg>`,
  styleUrl: './pull-refresh-ring.component.scss',
})
export class PullRefreshRingComponent {
  readonly el = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private readonly arc = viewChild.required<ElementRef<SVGCircleElement>>('arc');

  /**
   * Put the ring in the middle of the gap above the rows: `top` is the top edge of the
   * rows in the box of the ring, `pull` the height of the gap. `fill` (0 to 1) fills the
   * arc up to 80 %, so a full ring never reads as "done". `ms` is the time of the settle
   * of a release, 0 while the finger moves.
   */
  paint(top: number, pull: number, fill: number, ms: number): void {
    const s = this.el.style;
    const transition = ms > 0 ? `${ms}ms var(--ease-enter)` : '';
    s.top = `${top}px`;
    s.transition = transition ? `transform ${transition}, opacity ${transition}` : 'none';
    s.opacity = String(Math.min(1, pull / 24));
    s.transform = `translateY(${pull / 2 - 14}px)`;
    if (!this.el.classList.contains('ptr--spin')) {
      this.arc().nativeElement.style.strokeDashoffset = String(RING_LENGTH * (1 - Math.min(1, fill) * 0.8));
    }
  }

  /** The list loads: a third of the arc turns. */
  spin(on: boolean): void {
    this.el.classList.toggle('ptr--spin', on);
    if (on) this.arc().nativeElement.style.strokeDashoffset = String(RING_LENGTH * (2 / 3));
  }
}
