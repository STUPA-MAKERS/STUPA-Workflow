import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Ein Filter-Feld im {@link FilterBarComponent}-Popover: Label + projizierte
 * Steuerung (native input/select oder `<app-select>`). Einheitliche Optik für
 * alle Listen. Controls erben `.filter-field__control`-Styling über `::ng-deep`,
 * sodass Konsumenten nur ihr Control projizieren müssen.
 */
@Component({
  selector: 'app-filter-field',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <label class="flex flex-col gap-1 min-w-0">
      <span class="text-sm font-medium text-muted">{{ label() }}</span>
      <ng-content />
    </label>
  `,
  styles: [
    `
      /* Projizierte native Controls einheitlich stylen (app-currency-input bringt
         eigenes Styling mit → ausnehmen). */
      :host ::ng-deep input:not([type='checkbox']):not([type='radio']):not(.cur__input),
      :host ::ng-deep select {
        width: 100%;
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-bg);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font: inherit;
        font-size: var(--fs-md);
      }
      :host ::ng-deep input[type='date'] {
        min-width: 0;
      }
    `,
  ],
})
export class FilterFieldComponent {
  /** Sichtbares Label über dem Control. */
  readonly label = input('');
}
