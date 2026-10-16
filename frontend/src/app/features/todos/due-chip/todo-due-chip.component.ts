import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';
import { longDay } from '../todos.util';

/**
 * The due date of a card as a chip ("Di, 03.11.2026 ⌄", frame 2). The chip opens the
 * date picker of the browser; a set date has a remove button beside it.
 */
@Component({
  selector: 'app-todo-due-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent],
  templateUrl: './todo-due-chip.component.html',
  styleUrl: './todo-due-chip.component.scss',
})
export class TodoDueChipComponent {
  private readonly i18n = inject(I18nService);

  /** `YYYY-MM-DD` or null. */
  readonly value = input<string | null>(null);
  readonly disabled = input(false);
  /** A new date, or null to remove it. */
  readonly changed = output<string | null>();

  private readonly native = viewChild.required<ElementRef<HTMLInputElement>>('native');

  readonly text = computed(() => {
    const v = this.value();
    return v ? longDay(v, this.i18n.formatLocale()) : null;
  });

  /** Open the calendar of the browser; without `showPicker` the field takes a click. */
  pick(): void {
    const el = this.native().nativeElement;
    el.value = this.value() ?? '';
    try {
      if (typeof el.showPicker === 'function') {
        el.showPicker();
        return;
      }
    } catch {
      // A picker that may not open here (no user gesture) falls back to the click.
    }
    el.click();
  }

  /** A picked date, or null when the calendar of the browser cleared the date. */
  onNative(value: string): void {
    if (value === (this.value() ?? '')) return;
    this.changed.emit(value || null);
  }
}
