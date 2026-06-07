/**
 * a11y-Scan der UI-Primitive (T-43, requirements N3 — WCAG 2.1 AA).
 *
 * Die Primitive (Button/Input/Select/Checkbox/Dialog/Table/Stepper/Badge/Toast/
 * Vote-Bars) werden quer durch alle Views wiederverwendet — ein axe-Verstoß hier
 * schlägt also überall durch. Jede Komponente wird mit repräsentativen Inputs
 * (inkl. Fehlerzustand) gerendert und mit axe gescannt.
 */
import { Component } from '@angular/core';
import { render } from '@testing-library/angular';
import { runAxe } from '../../../testing/a11y';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  CheckboxComponent,
  DatepickerComponent,
  DateRangeComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  StepperComponent,
  TableComponent,
} from './index';
import { VoteBarsComponent } from '../../features/voting/vote-bars.component';
import { ToastComponent } from './toast/toast.component';

interface Row {
  name: string;
  amount: number;
}

@Component({
  standalone: true,
  imports: [
    ButtonComponent,
    InputComponent,
    SelectComponent,
    CheckboxComponent,
    DatepickerComponent,
    DateRangeComponent,
    BadgeComponent,
    CardComponent,
    StepperComponent,
    IconComponent,
    TableComponent,
    DialogComponent,
  ],
  template: `
    <main>
      <h1>UI-Kit</h1>
      <app-button variant="primary">Speichern</app-button>
      <app-button iconOnly ariaLabel="Schließen"><app-icon name="moon" /></app-button>

      <app-input label="Titel" hint="Pflichtfeld" [required]="true" />
      <app-input label="E-Mail" error="Ungültige Adresse" />

      <app-select
        label="Gremium"
        [options]="[{ value: 'a', label: 'AStA' }]"
        error="Bitte wählen"
      />

      <app-checkbox hint="Optional">Einverstanden</app-checkbox>

      <app-datepicker label="Frist" [required]="true" />
      <app-date-range legend="Zeitraum" startLabel="Von" endLabel="Bis" />

      <app-badge variant="success">Aktiv</app-badge>

      <h2>Karten</h2>
      <app-card heading="Karte"><p>Inhalt</p></app-card>

      <app-stepper [steps]="steps" [activeIndex]="1" ariaLabel="Fortschritt" />

      <app-table [columns]="cols" [rows]="rows" caption="Anträge" />

      <app-dialog [open]="true" title="Bestätigen" closeLabel="Schließen">
        <p>Wirklich fortfahren?</p>
        <app-button dialog-footer>OK</app-button>
      </app-dialog>
    </main>
  `,
})
class PrimitivesHost {
  readonly steps = [{ label: 'Eins' }, { label: 'Zwei' }, { label: 'Drei' }];
  readonly cols = [
    { key: 'name' as const, label: 'Name' },
    { key: 'amount' as const, label: 'Betrag' },
  ];
  readonly rows: Row[] = [{ name: 'Antrag A', amount: 100 }];
}

describe('UI-Primitive a11y (axe)', () => {
  it('has no axe violations across the primitive kit', async () => {
    const { container } = await render(PrimitivesHost);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('vote-bars (progressbar) has no axe violations', async () => {
    @Component({
      standalone: true,
      imports: [VoteBarsComponent],
      template: `<app-vote-bars
        [options]="['yes', 'no', 'abstain']"
        [counts]="{ yes: 12, no: 5, abstain: 2 }"
        [eligible]="30"
        leading="yes"
      />`,
    })
    class BarsHost {}
    const { container } = await render(BarsHost);
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('toast live-region has no axe violations', async () => {
    const { container } = await render(ToastComponent);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
