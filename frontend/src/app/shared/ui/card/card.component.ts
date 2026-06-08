import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

/** Container-Fläche. Slots: [card-header], default body, [card-footer]. */
@Component({
  selector: 'app-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="card" [class.card--interactive]="interactive">
      <header class="card__header">
        @if (heading) {
          @switch (headingLevel) {
            @case (2) {
              <h2 class="card__title">{{ heading }}</h2>
            }
            @case (4) {
              <h4 class="card__title">{{ heading }}</h4>
            }
            @default {
              <h3 class="card__title">{{ heading }}</h3>
            }
          }
        }
        <ng-content select="[card-header]" />
      </header>
      <div class="card__body"><ng-content /></div>
      <footer class="card__footer"><ng-content select="[card-footer]" /></footer>
    </section>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
      }
      .card {
        flex: 1 1 auto;
        display: flex;
        flex-direction: column;
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-sm);
        overflow: hidden;
      }
      .card--interactive {
        transition:
          box-shadow var(--motion-base) var(--ease-standard),
          border-color var(--motion-base) var(--ease-standard);
      }
      .card--interactive:hover {
        box-shadow: var(--shadow-md);
        border-color: var(--color-border-strong);
      }
      .card__header:empty,
      .card__footer:empty {
        display: none;
      }
      .card__header {
        padding: var(--space-5) var(--space-5) 0;
      }
      .card__title {
        font-size: var(--fs-lg);
        font-weight: var(--fw-semibold);
      }
      .card__body {
        padding: var(--space-5);
      }
      .card__footer {
        padding: 0 var(--space-5) var(--space-5);
      }
    `,
  ],
})
export class CardComponent {
  @Input() heading = '';
  @Input() interactive = false;
  /** Überschriften-Ebene des `heading` (a11y/heading-order). Default `<h3>`. */
  @Input() headingLevel: 2 | 3 | 4 = 3;
}
