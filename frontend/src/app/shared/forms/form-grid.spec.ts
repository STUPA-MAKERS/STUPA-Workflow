/**
 * Layout of the two-column form grid (`toFormlySections`, global `.fe-form .fe-grid`)
 * when `visibleIf` hides fields. jsdom does no layout, so this spec checks the two
 * parts that make the layout: Formly empties the host of a hidden field, and the global
 * styles give an empty host no grid cell.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { render } from '@testing-library/angular';
import type { FormSection } from '@core/api/models';
import { provideFormly } from '@shared/formly/formly.providers';
import { toFormlySections } from './formly-mapper';

const styles = readFileSync(join(__dirname, '../../../styles.scss'), 'utf8');

/** The declarations of the first rule with exactly this selector. */
function rule(css: string, selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = css.match(new RegExp(`(?:^|\\n)${esc} \\{([^}]*)\\}`));
  if (!m) throw new Error(`No rule ${selector}`);
  return m[1];
}

/** The applicant section of the QSM form: two questions only for an institution. */
const SECTIONS: FormSection[] = [
  {
    key: 'applicant',
    label: { de: 'Antragsteller' },
    fields: [
      {
        key: 'art',
        type: 'select',
        label: { de: 'Art des Antragstellers' },
        options: [
          { value: 'person', label: { de: 'Person' } },
          { value: 'institution', label: { de: 'Institution' } },
        ],
      },
      {
        key: 'inst_art',
        type: 'select',
        label: { de: 'Art der Institution' },
        options: [{ value: 'verein', label: { de: 'Verein' } }],
        visibleIf: { '==': [{ var: 'art' }, 'institution'] },
      },
      {
        key: 'inst_name',
        type: 'text',
        label: { de: 'Name der Institution' },
        visibleIf: { '==': [{ var: 'art' }, 'institution'] },
      },
      {
        key: 'notes',
        type: 'textarea',
        label: { de: 'Anmerkungen der Institution' },
        visibleIf: { '==': [{ var: 'art' }, 'institution'] },
      },
      { key: 'faculty', type: 'text', label: { de: 'Fakultät' } },
      { key: 'role', type: 'text', label: { de: 'Rolle' } },
    ],
  },
];

@Component({
  standalone: true,
  imports: [ReactiveFormsModule, FormlyForm],
  template: `<div class="fe-form"><formly-form [form]="form" [fields]="fields" [model]="model" /></div>`,
})
class HostComponent {
  form = new FormGroup({});
  model: Record<string, unknown> = {};
  fields: FormlyFieldConfig[] = [];
}

async function renderGrid(model: Record<string, unknown>) {
  const view = await render(HostComponent, {
    providers: [provideFormly()],
    componentProperties: { fields: toFormlySections(SECTIONS, 'de'), model },
  });
  const hosts = () =>
    Array.from(view.container.querySelectorAll<HTMLElement>('.fe-grid > formly-field'));
  /** The hosts that take a grid cell: every host that is not empty. */
  const cells = () =>
    hosts()
      .filter((h) => !h.matches(':empty'))
      .map((h) => h.querySelector('label, h3')?.textContent?.replace('*', '').trim());
  return { ...view, hosts, cells };
}

describe('form grid with hidden fields', () => {
  it('gives the empty host of a hidden field no grid cell', () => {
    expect(rule(styles, '.fe-form .fe-grid > formly-field:empty')).toMatch(/display: none;/);
    // The rule for every host sets no `display`, so it cannot win over the rule above
    // (or over the `:host:empty` rule of Formly).
    expect(rule(styles, '.fe-form .fe-grid > formly-field')).not.toMatch(/display:/);
  });

  it('leaves the host of a hidden field empty, so the next field takes its cell', async () => {
    const { hosts, cells } = await renderGrid({ art: 'person' });
    // Heading + 6 fields: every field keeps its host, hidden or not.
    expect(hosts()).toHaveLength(7);
    expect(hosts().filter((h) => h.matches(':empty'))).toHaveLength(3);
    // "Fakultät" follows "Art des Antragstellers" in the next cell, no hole between them.
    expect(cells()).toEqual(['Antragsteller', 'Art des Antragstellers', 'Fakultät', 'Rolle']);
  });

  it('fills the hosts again when the answer shows the fields', async () => {
    const { fixture, cells } = await renderGrid({ art: 'institution' });
    await fixture.whenStable();
    expect(cells()).toEqual([
      'Antragsteller',
      'Art des Antragstellers',
      'Art der Institution',
      'Name der Institution',
      'Anmerkungen der Institution',
      'Fakultät',
      'Rolle',
    ]);
  });
});
