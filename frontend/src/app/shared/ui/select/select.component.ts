import { ChangeDetectionStrategy, Component, Input, signal } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';

let nextId = 0;

/** Auswahloption für {@link SelectComponent}. */
export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

/**
 * Dropdown des UI-Kits (#77). Ersetzt Freitext-Felder mit eingeschränkten
 * Optionen (Gremium, Budget, Status/Typ, Rollen). `ControlValueAccessor` →
 * Reactive Forms + `ngModel`. Token-basiert, eingebettetes Chevron, sichtbarer
 * Fokus-Ring, Label/`for`-Bindung + `aria-describedby` (a11y), Dark/Light.
 */
@Component({
  selector: 'app-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: SelectComponent, multi: true }],
  template: `
    <div class="sel">
      @if (label) {
        <label class="sel__label" [for]="id">
          {{ label }}
          @if (required) {
            <span class="sel__req" aria-hidden="true">*</span>
          }
        </label>
      }
      <select
        class="sel__control"
        [id]="id"
        [value]="value()"
        [disabled]="disabled()"
        [attr.aria-label]="!label && ariaLabel ? ariaLabel : null"
        [attr.aria-invalid]="error ? 'true' : null"
        [attr.aria-describedby]="describedBy"
        [attr.required]="required ? '' : null"
        (change)="onSelect($event)"
        (blur)="onTouched()"
      >
        @if (placeholder) {
          <option value="" [disabled]="required">{{ placeholder }}</option>
        }
        @for (opt of options; track opt.value) {
          <option [value]="opt.value" [disabled]="opt.disabled ?? false">{{ opt.label }}</option>
        }
      </select>
      @if (hint && !error) {
        <p class="sel__hint" [id]="id + '-hint'">{{ hint }}</p>
      }
      @if (error) {
        <p class="sel__error" [id]="id + '-error'" role="alert">{{ error }}</p>
      }
    </div>
  `,
  styles: [
    `
      .sel {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .sel__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .sel__req {
        color: var(--color-danger);
      }
      .sel__control {
        appearance: none;
        -webkit-appearance: none;
        width: 100%;
        height: var(--control-height);
        box-sizing: border-box;
        padding: 0 var(--space-7) 0 var(--space-4);
        font-size: var(--fs-md);
        line-height: var(--lh-normal);
        color: var(--color-text);
        background-color: var(--color-surface);
        background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12"><path d="M2 4.5l4 4 4-4" fill="none" stroke="%236e756f" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>');
        background-repeat: no-repeat;
        background-position: right var(--space-3) center;
        background-size: 0.7rem;
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        cursor: pointer;
        transition: border-color var(--motion-fast) var(--ease-standard);
      }
      .sel__control:hover:not(:disabled) {
        border-color: var(--color-text-muted);
      }
      .sel__control:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .sel__control[aria-invalid='true'] {
        border-color: var(--color-danger);
      }
      .sel__hint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
      }
      .sel__error {
        font-size: var(--fs-xs);
        color: var(--color-danger);
      }
    `,
  ],
})
export class SelectComponent implements ControlValueAccessor {
  @Input() label = '';
  /** Barrierefreier Name, wenn kein sichtbares Label gesetzt ist. */
  @Input() ariaLabel = '';
  @Input() placeholder = '';
  @Input() hint = '';
  @Input() error = '';
  @Input() required = false;
  @Input() options: SelectOption[] = [];
  @Input() id = `app-select-${nextId++}`;

  readonly value = signal('');
  readonly disabled = signal(false);

  private onChange: (value: string) => void = () => {};
  onTouched: () => void = () => {};

  get describedBy(): string | null {
    if (this.error) return `${this.id}-error`;
    if (this.hint) return `${this.id}-hint`;
    return null;
  }

  onSelect(event: Event): void {
    const v = (event.target as HTMLSelectElement).value;
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
