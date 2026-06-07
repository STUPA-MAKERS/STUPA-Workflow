import { ChangeDetectionStrategy, Component, Input, signal } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';

let nextId = 0;

/**
 * Checkbox des UI-Kits. Boolescher Wert über `ControlValueAccessor`
 * (Reactive Forms + `ngModel`). Token-basiert (`accent-color` = CD-Primär),
 * sichtbarer Fokus-Ring (global `:focus-visible`), Label/`for`-Bindung für a11y.
 * Label-Text wird projiziert: `<app-checkbox [(ngModel)]="x">Text</app-checkbox>`.
 */
@Component({
  selector: 'app-checkbox',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: CheckboxComponent, multi: true }],
  template: `
    <label class="cbx" [class.cbx--disabled]="disabled()" [for]="id">
      <input
        class="cbx__input"
        type="checkbox"
        [id]="id"
        [checked]="checked()"
        [disabled]="disabled()"
        [attr.aria-describedby]="hint ? id + '-hint' : null"
        (change)="onToggle($event)"
        (blur)="onTouched()"
      />
      <span class="cbx__label"><ng-content /></span>
    </label>
    @if (hint) {
      <p class="cbx__hint" [id]="id + '-hint'">{{ hint }}</p>
    }
  `,
  styles: [
    `
      :host {
        display: inline-flex;
        flex-direction: column;
        gap: var(--space-1);
      }
      .cbx {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
        cursor: pointer;
        font-size: var(--fs-sm);
        color: var(--color-text);
      }
      .cbx--disabled {
        cursor: not-allowed;
        opacity: 0.6;
      }
      .cbx__input {
        flex: none;
        width: 1.1rem;
        height: 1.1rem;
        margin: 0;
        accent-color: var(--color-primary);
        cursor: inherit;
      }
      .cbx__label {
        line-height: var(--lh-normal);
      }
      .cbx__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
        padding-left: calc(1.1rem + var(--space-2));
      }
    `,
  ],
})
export class CheckboxComponent implements ControlValueAccessor {
  @Input() id = `app-checkbox-${nextId++}`;
  @Input() hint = '';

  readonly checked = signal(false);
  readonly disabled = signal(false);

  private onChange: (value: boolean) => void = () => {};
  onTouched: () => void = () => {};

  onToggle(event: Event): void {
    const v = (event.target as HTMLInputElement).checked;
    this.checked.set(v);
    this.onChange(v);
  }

  writeValue(value: boolean | null): void {
    this.checked.set(!!value);
  }
  registerOnChange(fn: (value: boolean) => void): void {
    this.onChange = fn;
  }
  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }
  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }
}
