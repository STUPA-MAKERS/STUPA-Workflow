import { Component, computed, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, CheckboxComponent, DialogComponent, InputComponent } from '@stupa-makers/ui-kit';

/**
 * Asks for the alternative text of an image before it goes into a Markdown text (app
 * spec 000506, WCAG 1.1.1). The text is required, unless the user marks the image as
 * decorative: then the alternative text is empty, and a screen reader skips the image.
 * `done` gives the text, or `null` when the user cancels.
 */
@Component({
  selector: 'app-image-alt-dialog',
  standalone: true,
  imports: [FormsModule, TranslatePipe, DialogComponent, InputComponent, CheckboxComponent, ButtonComponent],
  templateUrl: './image-alt-dialog.component.html',
  styleUrl: './image-alt-dialog.component.scss',
})
export class ImageAltDialogComponent {
  /** The file name, so the user knows which image the text is for. */
  readonly fileName = input('');
  readonly done = output<string | null>();

  protected readonly text = signal('');
  protected readonly decorative = signal(false);
  protected readonly tried = signal(false);
  protected readonly valid = computed(() => this.decorative() || this.text().trim() !== '');

  protected confirm(): void {
    this.tried.set(true);
    if (!this.valid()) return;
    this.done.emit(this.decorative() ? '' : this.text().trim());
  }

  protected cancel(): void {
    this.done.emit(null);
  }
}
