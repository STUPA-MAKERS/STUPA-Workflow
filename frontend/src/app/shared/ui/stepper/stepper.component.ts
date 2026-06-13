import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export interface Step {
  label: string;
}

/** Fortschrittsanzeige für den Antrags-Wizard (N1a Multi-Step). */
@Component({
  selector: 'app-stepper',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './stepper.component.html',
  styleUrl: './stepper.component.scss',
})
export class StepperComponent {
  @Input() steps: Step[] = [];
  @Input() activeIndex = 0;
  @Input() ariaLabel = 'Fortschritt';
}
