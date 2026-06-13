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
  templateUrl: './select.component.html',
  styleUrl: './select.component.scss',
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
