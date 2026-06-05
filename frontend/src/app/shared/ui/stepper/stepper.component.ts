import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export interface Step {
  label: string;
}

/** Fortschrittsanzeige für den Antrags-Wizard (N1a Multi-Step). */
@Component({
  selector: 'app-stepper',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ol class="stepper" [attr.aria-label]="ariaLabel">
      @for (step of steps; track step.label; let i = $index) {
        <li
          class="stepper__item"
          [class.is-active]="i === activeIndex"
          [class.is-done]="i < activeIndex"
          [attr.aria-current]="i === activeIndex ? 'step' : null"
        >
          <span class="stepper__marker">{{ i < activeIndex ? '✓' : i + 1 }}</span>
          <span class="stepper__label">{{ step.label }}</span>
        </li>
      }
    </ol>
  `,
  styles: [
    `
      .stepper {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-5);
        padding: 0;
        margin: 0;
        list-style: none;
      }
      .stepper__item {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .stepper__marker {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 1.75rem;
        height: 1.75rem;
        border-radius: var(--radius-pill);
        border: var(--border-width) solid var(--color-border-strong);
        font-weight: var(--fw-semibold);
        font-size: var(--fs-sm);
      }
      .stepper__item.is-active {
        color: var(--color-text);
      }
      .stepper__item.is-active .stepper__marker {
        background: var(--color-primary);
        border-color: var(--color-primary);
        color: var(--color-on-primary);
      }
      .stepper__item.is-done .stepper__marker {
        background: var(--color-primary-subtle);
        border-color: var(--color-primary);
        color: var(--color-primary);
      }
    `,
  ],
})
export class StepperComponent {
  @Input() steps: Step[] = [];
  @Input() activeIndex = 0;
  @Input() ariaLabel = 'Fortschritt';
}
