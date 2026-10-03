import { render, screen } from '@testing-library/angular';
import { runAxe } from '../../../../testing/a11y';
import { FieldGroupComponent, FieldRowComponent } from './field-group.component';

describe('FieldGroupComponent and FieldRowComponent', () => {
  const imports = [FieldGroupComponent, FieldRowComponent];

  it('shows each label above its value', async () => {
    const { container } = await render(
      `<app-field-group>
         <app-field-row label="Eingegangen" value="26.09.2026, 14:12" />
         <app-field-row label="Betrag" [mono]="true">1.250,00 €</app-field-row>
       </app-field-group>`,
      { imports },
    );
    const rows = container.querySelectorAll('app-field-row');
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector('.fld__label')).toHaveTextContent('Eingegangen');
    expect(rows[0].querySelector('.fld__value')).toHaveTextContent('26.09.2026, 14:12');
    expect(rows[0].querySelector('.fld__value')).not.toHaveClass('mono');
    expect(rows[1].querySelector('.fld__value')).toHaveTextContent('1.250,00 €');
    expect(rows[1].querySelector('.fld__value')).toHaveClass('mono');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows a zero, which is a value and not a missing one', async () => {
    const { container } = await render(`<app-field-row label="Anhänge" [value]="0" />`, {
      imports,
    });
    expect(container.querySelector('.fld__value')).toHaveTextContent('0');
  });

  it('projects an action into the trailing slot', async () => {
    await render(
      `<app-field-row label="Kostenstelle" value="Fachschaft Informatik">
         <button trail type="button" aria-label="Kostenstelle ändern">x</button>
       </app-field-row>`,
      { imports },
    );
    expect(screen.getByRole('button', { name: 'Kostenstelle ändern' })).toBeInTheDocument();
  });

  it('uses the global group look and switches the row surface', async () => {
    const { container } = await render(
      `<app-field-group /><app-field-group [surface]="1" /><app-field-group [surface]="3" />`,
      { imports },
    );
    const [two, one, three] = Array.from(container.querySelectorAll('app-field-group'));
    expect(two).toHaveClass('seg');
    expect(two).not.toHaveClass('seg--bg1');
    expect(two).not.toHaveClass('seg--bg3');
    expect(one).toHaveClass('seg', 'seg--bg1');
    expect(three).toHaveClass('seg', 'seg--bg3');
  });
});
