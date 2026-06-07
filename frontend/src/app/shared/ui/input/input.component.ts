import { ChangeDetectionStrategy, Component, Input, signal } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';

let nextId = 0;

/** Textfeld mit Label/Hinweis/Fehler. ControlValueAccessor → Reactive Forms. */
@Component({
  selector: 'app-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: InputComponent, multi: true }],
  template: `
    <div class="field">
      <label class="field__label" [for]="id">
        {{ label }}
        @if (required) {
          <span class="field__req" aria-hidden="true">*</span>
        }
      </label>
      <input
        class="field__control"
        [id]="id"
        [type]="type"
        [value]="value()"
        [disabled]="disabled()"
        [attr.placeholder]="placeholder || null"
        [attr.aria-invalid]="error ? 'true' : null"
        [attr.aria-describedby]="describedBy"
        [attr.required]="required ? '' : null"
        (input)="onInput($event)"
        (blur)="onTouched()"
      />
      @if (hint && !error) {
        <p class="field__hint" [id]="id + '-hint'">{{ hint }}</p>
      }
      @if (error) {
        <p class="field__error" [id]="id + '-error'" role="alert">{{ error }}</p>
      }
    </div>
  `,
  styles: [
    `
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .field__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .field__req {
        color: var(--color-danger);
      }
      .field__control {
        height: var(--control-height);
        box-sizing: border-box;
        padding: 0 var(--space-4);
        font-size: var(--fs-md);
        line-height: var(--lh-normal);
        color: var(--color-text);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        transition: border-color var(--motion-fast) var(--ease-standard);
      }
      .field__control:hover:not(:disabled) {
        border-color: var(--color-text-muted);
      }
      .field__control:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .field__control[aria-invalid='true'] {
        border-color: var(--color-danger);
      }
      .field__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .field__error {
        font-size: var(--fs-xs);
        color: var(--color-danger);
      }
    `,
  ],
})
export class InputComponent implements ControlValueAccessor {
  @Input() label = '';
  @Input() type = 'text';
  @Input() placeholder = '';
  @Input() hint = '';
  @Input() error = '';
  @Input() required = false;
  @Input() id = `app-input-${nextId++}`;

  readonly value = signal('');
  readonly disabled = signal(false);

  private onChange: (value: string) => void = () => {};
  onTouched: () => void = () => {};

  get describedBy(): string | null {
    if (this.error) return `${this.id}-error`;
    if (this.hint) return `${this.id}-hint`;
    return null;
  }

  onInput(event: Event): void {
    const v = (event.target as HTMLInputElement).value;
    this.value.set(v);
    this.onChange(v);
  }

  writeValue(value: string | null): void {
    this.value.set(value ?? '');
  }
  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
  }
  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }
  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }
}
