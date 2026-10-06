import { ChangeDetectionStrategy, Component, inject, output, signal } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';
import { AltchaService } from './altcha.service';

type AltchaState = 'idle' | 'verifying' | 'solved' | 'error';

let nextId = 0;

/**
 * ALTCHA widget of the submit step.
 *
 * A click solves a fresh proof-of-work challenge (`AltchaService`) and emits the base64
 * solution to the wizard. If ALTCHA has no configuration, the challenge route answers
 * 404 and the widget emits `unavailable`; the wizard then needs no solution. The wizard
 * allows the submit only after `solved` or `unavailable`.
 *
 * Look: one filled row like an input field (no shadow), a check box at the start, the
 * state as its label, and the purpose as a muted line below.
 */
@Component({
  selector: 'app-altcha',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent],
  templateUrl: './altcha.component.html',
  styleUrl: './altcha.component.scss',
})
export class AltchaComponent {
  private readonly altcha = inject(AltchaService);

  /** Emits the base64 proof-of-work solution after the widget solves the challenge. */
  readonly solved = output<string>();
  /** Emits when the server has Altcha off. The form then needs no captcha. */
  readonly unavailable = output<void>();

  readonly state = signal<AltchaState>('idle');
  protected readonly noteId = `altcha-note-${nextId++}`;

  async solve(): Promise<void> {
    if (this.state() === 'verifying' || this.state() === 'solved') return;
    this.state.set('verifying');
    try {
      const solution = await this.altcha.solve();
      this.state.set('solved');
      if (solution === null) this.unavailable.emit();
      else this.solved.emit(solution);
    } catch {
      this.state.set('error');
    }
  }
}
