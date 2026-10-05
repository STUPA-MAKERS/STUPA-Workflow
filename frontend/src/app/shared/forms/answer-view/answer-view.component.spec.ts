import { render, screen, within } from '@testing-library/angular';
import type { FormFieldDef, FormSection } from '@core/api/models';
import { runAxe } from '../../../../testing/a11y';
import { AnswerViewComponent } from './answer-view.component';

const opts = (...pairs: [string, string][]) => pairs.map(([value, de]) => ({ value, label: { de } }));

async function view(
  sections: FormSection[],
  data: Record<string, unknown>,
  inputs: Record<string, unknown> = {},
) {
  localStorage.setItem('ap.locale', 'de');
  return render(AnswerViewComponent, {
    componentInputs: { sections, data, ...inputs },
  });
}

const one = (fields: FormFieldDef[], label = 'Vorhaben'): FormSection[] => [
  { key: 'main', label: { de: label }, fields },
];

/** The text of the value of the row with this label, or null. */
function valueOf(label: string): string | null {
  const row = screen.queryByText(label)?.closest('app-field-row');
  return row?.querySelector('.fld__value')?.textContent?.trim() ?? null;
}

describe('AnswerViewComponent', () => {
  // One row per field type: the value as the reader sees it (O19).
  it.each<[string, FormFieldDef, unknown, string]>([
    ['text', { key: 'f', type: 'text', label: { de: 'Feld' } }, 'Hallo', 'Hallo'],
    ['email', { key: 'f', type: 'email', label: { de: 'Feld' } }, 'a@b.de', 'a@b.de'],
    ['iban', { key: 'f', type: 'iban', label: { de: 'Feld' } }, 'DE02 1203', 'DE02 1203'],
    ['number', { key: 'f', type: 'number', label: { de: 'Feld' } }, 350, '350'],
    ['number 0', { key: 'f', type: 'number', label: { de: 'Feld' } }, 0, '0'],
    ['date', { key: 'f', type: 'date', label: { de: 'Feld' } }, '2026-10-16', '16.10.2026'],
    ['daterange', { key: 'f', type: 'daterange', label: { de: 'Feld' } }, { from: '2026-10-16', to: '2026-10-18' }, '16.10.2026 – 18.10.2026'],
    ['select', { key: 'f', type: 'select', label: { de: 'Feld' }, options: opts(['a', 'Kultur']) }, 'a', 'Kultur'],
    ['select unknown', { key: 'f', type: 'select', label: { de: 'Feld' }, options: opts(['a', 'Kultur']) }, 'zzz', 'zzz'],
    ['gremium_select', { key: 'f', type: 'gremium_select', label: { de: 'Feld' }, options: opts(['g1', 'StuPa']) }, 'g1', 'StuPa'],
    ['budget_select', { key: 'f', type: 'budget_select', label: { de: 'Feld' }, options: opts(['b1', 'Kultur (HH-1)']) }, 'b1', 'Kultur (HH-1)'],
    ['multiselect', { key: 'f', type: 'multiselect', label: { de: 'Feld' }, options: opts(['x', 'Party'], ['y', 'Erstis']) }, ['x', 'y', 'z'], 'Party, Erstis, z'],
    ['multiselect scalar', { key: 'f', type: 'multiselect', label: { de: 'Feld' }, options: opts(['x', 'Party']) }, 'x', 'Party'],
    ['currency', { key: 'f', type: 'currency', label: { de: 'Feld' } }, 1250, '1.250,00 €'],
    ['currency text', { key: 'f', type: 'currency', label: { de: 'Feld' } }, 'viel', 'viel'],
    ['checkbox yes', { key: 'f', type: 'checkbox', label: { de: 'Feld' } }, true, 'Ja'],
    ['checkbox no', { key: 'f', type: 'checkbox', label: { de: 'Feld' } }, false, 'Nein'],
    ['checkbox text', { key: 'f', type: 'checkbox', label: { de: 'Feld' } }, 'vielleicht', 'vielleicht'],
  ])('shows a %s answer as text', async (_name, field, value, expected) => {
    await view(one([field]), { f: value });
    expect(valueOf('Feld')?.replace(/\u00a0/g, ' ')).toBe(expected);
  });

  it('puts short fields side by side and a long text over the full width as Markdown', async () => {
    const { container } = await view(
      one([
        { key: 'a', type: 'text', label: { de: 'A' } },
        { key: 'b', type: 'number', label: { de: 'B' } },
        { key: 'desc', type: 'textarea', label: { de: 'Beschreibung' } },
        { key: 'c', type: 'text', label: { de: 'C' } },
      ]),
      { a: 'eins', b: 2, desc: 'Ein **fetter** Satz.', c: 'drei' },
    );
    const group = container.querySelector('app-field-group') as HTMLElement;
    const grids = group.querySelectorAll(':scope > .av__grid');
    expect(grids).toHaveLength(2);
    expect(grids[0].querySelectorAll('app-field-row')).toHaveLength(2);
    expect(grids[1].querySelectorAll('app-field-row')).toHaveLength(1);
    // The long text is a row of its own between the two grids, rendered as Markdown.
    const md = group.querySelector(':scope > app-field-row app-markdown-view') as HTMLElement;
    expect(md.querySelector('strong')?.textContent).toBe('fetter');
    // Amounts and IBANs use the mono face, other values not.
    expect(screen.getByText('A').closest('app-field-row')?.querySelector('.fld__value')).not.toHaveClass('mono');
  });

  it('gives each section its heading and leaves out a section without answers', async () => {
    await view(
      [
        { key: 's1', label: { de: 'Vorhaben' }, fields: [{ key: 'a', type: 'text', label: { de: 'A' } }] },
        { key: 's2', label: { de: 'Leer' }, fields: [{ key: 'b', type: 'text', label: { de: 'B' } }] },
        { key: 's3', label: { de: 'Kontakt' }, fields: [{ key: 'iban', type: 'iban', label: { de: 'IBAN' } }] },
      ],
      { a: 'x', iban: 'DE02' },
    );
    expect(screen.getAllByRole('heading').map((h) => h.textContent)).toEqual(['Vorhaben', 'Kontakt']);
    expect(screen.getByText('DE02').closest('.fld__value')).toHaveClass('mono');
  });

  it('hides empty answers, visibleIf-hidden fields, display texts, files and the title', async () => {
    await view(
      one([
        { key: 'title', type: 'text', label: { de: 'Titel' } },
        { key: 'empty', type: 'text', label: { de: 'Leer' } },
        { key: 'list', type: 'multiselect', label: { de: 'Liste' } },
        { key: 'range', type: 'daterange', label: { de: 'Zeitraum' } },
        { key: 'info', type: 'markdown', label: { de: 'Hinweis' }, help: { de: 'Lies das.' } },
        { key: 'doc', type: 'file', label: { de: 'Datei' } },
        { key: 'flag', type: 'checkbox', label: { de: 'Raum nötig' } },
        { key: 'room', type: 'text', label: { de: 'Raum' }, visibleIf: { '==': [{ var: 'flag' }, true] } },
        { key: 'pot', type: 'text', label: { de: 'Topf' }, visibleIf: { '==': [{ var: 'has_budget' }, true] } },
        { key: 'shown', type: 'text', label: { de: 'Sichtbar' } },
      ]),
      {
        title: 'T',
        empty: '  ',
        list: [],
        range: { from: '', to: null },
        info: 'x',
        doc: 'file-id',
        flag: false,
        room: 'R 101',
        pot: 'P',
        shown: 'ja',
      },
      { context: { has_budget: false } },
    );
    for (const label of ['Titel', 'Leer', 'Liste', 'Zeitraum', 'Hinweis', 'Datei', 'Raum', 'Topf']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    expect(valueOf('Raum nötig')).toBe('Nein');
    expect(valueOf('Sichtbar')).toBe('ja');
  });

  it('shows nothing for a PII field the server left out (O21)', async () => {
    await view(
      one([
        { key: 'name', type: 'text', label: { de: 'Name' } },
        { key: 'iban', type: 'iban', label: { de: 'IBAN' }, isPII: true },
      ]),
      { name: 'Lea' },
    );
    expect(screen.queryByText('IBAN')).not.toBeInTheDocument();
    expect(valueOf('Name')).toBe('Lea');
  });

  it('says "berechnet" for a computed field and computes a missing value', async () => {
    await view(
      one([
        { key: 'fee', type: 'currency', label: { de: 'Eintritt' } },
        { key: 'n', type: 'number', label: { de: 'Personen' } },
        { key: 'income', type: 'computed', label: { de: 'Einnahmen' }, compute: { '*': [{ var: 'fee' }, { var: 'n' }] } },
        { key: 'stored', type: 'computed', label: { de: 'Gespeichert' }, compute: { '+': [1, 1] } },
        { key: 'broken', type: 'computed', label: { de: 'Kaputt' }, compute: { nope: [1] } },
        { key: 'norule', type: 'computed', label: { de: 'Ohne Regel' } },
      ]),
      { fee: 3, n: 100, stored: 7 },
    );
    expect(valueOf('Einnahmen · berechnet')).toBe('300');
    // A stored value wins over the rule.
    expect(valueOf('Gespeichert · berechnet')).toBe('7');
    // A rule that fails, or no rule, gives no value: the field does not show.
    expect(screen.queryByText(/Kaputt/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Ohne Regel/)).not.toBeInTheDocument();
  });

  it('renders the cost positions in their own block between the field groups', async () => {
    const { container } = await view(
      one(
        [
          { key: 'costs', type: 'positions', label: { de: 'Kostenaufstellung' } },
          { key: 'fee', type: 'currency', label: { de: 'Eintritt' } },
        ],
        'Kosten',
      ),
      { costs: [{ label: 'Raum', offers: [{ label: 'Mensa', value: 450, preferred: true }] }], fee: 2 },
    );
    const sec = container.querySelector('.av__sec') as HTMLElement;
    const kids = [...sec.children].map((el) => el.tagName.toLowerCase());
    expect(kids).toEqual(['h3', 'app-positions-view', 'app-field-group']);
    expect(within(sec).getByText('Raum')).toBeInTheDocument();
  });

  it('shows a table answer as a table and an odd value as text', async () => {
    await view(
      one([
        { key: 't', type: 'table', label: { de: 'Helfende' } },
        { key: 'u', type: 'table', label: { de: 'Kaputt' } },
      ]),
      { t: [{ name: 'Lea', role: 'Kasse' }, { name: 'Tom' }], u: 'freier Text' },
    );
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('columnheader').map((c) => c.textContent)).toEqual(['name', 'role']);
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(valueOf('Kaputt')).toBe('freier Text');
  });

  it('lists answers without a field last under "Weitere Angaben"', async () => {
    await view(one([{ key: 'a', type: 'text', label: { de: 'A' } }]), {
      a: 'x',
      title: 'T',
      legacy: { old: true },
      blank: '',
    });
    const headings = screen.getAllByRole('heading').map((h) => h.textContent);
    expect(headings).toEqual(['Vorhaben', 'Weitere Angaben']);
    expect(valueOf('legacy')).toBe('{"old":true}');
    expect(screen.queryByText('blank')).not.toBeInTheDocument();
    expect(screen.queryByText('title')).not.toBeInTheDocument();
  });

  it('shows the empty text only when no answer shows', async () => {
    const { rerender } = await view(one([{ key: 'a', type: 'text', label: { de: 'A' } }]), {}, {
      emptyText: 'Keine Angaben vorhanden.',
    });
    expect(screen.getByText('Keine Angaben vorhanden.')).toBeInTheDocument();
    await rerender({ componentInputs: { sections: one([]), data: {}, emptyText: '' } });
    expect(screen.queryByText('Keine Angaben vorhanden.')).not.toBeInTheDocument();
  });

  it('passes the surface to its groups and has no a11y violations', async () => {
    const { container } = await view(
      one([
        { key: 'a', type: 'text', label: { de: 'A' } },
        { key: 'costs', type: 'positions', label: { de: 'Kosten' } },
      ]),
      { a: 'x', costs: [{ label: 'P', offers: [{ label: 'O', value: 1, preferred: true }] }] },
      { surface: 3 },
    );
    expect(container.querySelector('app-field-group')).toHaveClass('rowgroup--bg3');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
