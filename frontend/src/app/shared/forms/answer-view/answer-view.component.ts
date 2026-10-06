import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { FieldType, FormFieldDef, FormSection } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { FieldGroupComponent, FieldRowComponent } from '@shared/ui/field-group/field-group.component';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { formatAnswer, formatFieldValue, isEmptyAnswer } from '../answer-format';
import { resolveI18n } from '../i18n-text';
import { evalJsonLogic, isFieldVisible } from '../jsonlogic';
import { PositionsViewComponent } from '../positions-view/positions-view.component';

/** One answer as a label and its text. */
export interface AnswerCell {
  key: string;
  label: string;
  value: string;
  /** Mono face: IBAN and amounts. */
  mono: boolean;
}

/** A row of the field group: short fields side by side, or one long field. */
export type AnswerRow =
  | { kind: 'grid'; key: string; cells: AnswerCell[] }
  | { kind: 'text'; cell: AnswerCell; markdown: boolean }
  | { kind: 'table'; key: string; label: string; columns: string[]; rows: string[][] };

/** A run of rows in one field group, or the cost positions in their own block. */
export type AnswerChunk =
  | { kind: 'group'; key: string; rows: AnswerRow[] }
  | { kind: 'positions'; key: string; label: string; value: unknown };

/** A section of the form with its visible answers. */
export interface AnswerBlock {
  key: string;
  label: string;
  chunks: AnswerChunk[];
}

/** Field types that the detail never shows: display text, markers and files (the files
 *  have the block "Anhänge" with the scan state). */
const NOT_SHOWN: ReadonlySet<FieldType> = new Set(['markdown', 'section', 'file']);
/** Field types in the mono face. */
const MONO: ReadonlySet<FieldType> = new Set(['iban', 'currency']);

/**
 * The answers of an application, read-only (O19, the table "Darstellung der
 * Formularfelder" in the target model). The detail and the review step of the apply
 * wizard use it.
 *
 * - Each section of the form is a group with its heading.
 * - Short fields (text, email, IBAN, number, date, selections, amounts, checkboxes,
 *   computed values) sit in a grid of two columns; below 22rem one column.
 * - A long text (`textarea`) takes the full width and renders as Markdown; a table
 *   takes the full width too.
 * - Selections show the names of their options (also Gremien and cost centres), a
 *   multiselect a comma list, an amount euro, a checkbox Ja or Nein.
 * - A computed field says "berechnet" after its label. Without a stored value the
 *   view computes it, as the form does.
 * - The cost positions get their own block (`app-positions-view`).
 * - Not shown: display texts (`markdown`), files (block "Anhänge"), empty answers and
 *   fields that `visibleIf` hides. A PII field that the server left out of `data`
 *   (O21) is an empty answer, so it shows nothing.
 * - Keys without a field (an answer of an older form version) come last under
 *   "Weitere Angaben" as plain text.
 */
@Component({
  selector: 'app-answer-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FieldGroupComponent, FieldRowComponent, MarkdownViewComponent, PositionsViewComponent],
  templateUrl: './answer-view.component.html',
  styleUrl: './answer-view.component.scss',
})
export class AnswerViewComponent {
  private readonly i18n = inject(I18nService);

  readonly sections = input.required<readonly FormSection[]>();
  readonly data = input.required<Readonly<Record<string, unknown>>>();
  /** More variables for `visibleIf` and `compute`, for example `has_budget`. */
  readonly context = input<Readonly<Record<string, unknown>>>({});
  /** Keys the page shows elsewhere, for example the title in the header. */
  readonly skipKeys = input<readonly string[]>(['title']);
  /** The text when no answer shows. Leave it empty to show nothing. */
  readonly emptyText = input('');
  /** The surface of the rows; see `app-field-group`. */
  readonly surface = input<1 | 2 | 3>(2);

  readonly blocks = computed<AnswerBlock[]>(() => {
    const lang = this.i18n.locale();
    const data = this.data();
    const ctx = { ...this.context(), ...data };
    const skip = new Set(this.skipKeys());
    const known = new Set<string>();
    const blocks: AnswerBlock[] = [];

    for (const section of this.sections()) {
      const builder = new ChunkBuilder();
      for (const f of section.fields) {
        known.add(f.key);
        if (skip.has(f.key) || NOT_SHOWN.has(f.type)) continue;
        if (!isFieldVisible(f.visibleIf, ctx)) continue;
        const raw = f.type === 'computed' ? this.computedValue(f, data, ctx) : data[f.key];
        if (isEmptyAnswer(raw)) continue;
        const label = resolveI18n(f.label, lang);
        if (f.type === 'positions') {
          builder.positions({ kind: 'positions', key: f.key, label, value: raw });
        } else if (f.type === 'table') {
          builder.row(tableRow(f.key, label, raw));
        } else if (f.type === 'textarea') {
          builder.row({ kind: 'text', cell: this.cell(f, label, raw), markdown: true });
        } else {
          builder.cell(this.cell(f, label, raw));
        }
      }
      const chunks = builder.done();
      if (chunks.length) {
        blocks.push({ key: section.key, label: resolveI18n(section.label, lang), chunks });
      }
    }

    // Answers without a field: an older form version had them. Plain text, last.
    const other = new ChunkBuilder();
    for (const [key, value] of Object.entries(data)) {
      if (known.has(key) || skip.has(key) || isEmptyAnswer(value)) continue;
      other.cell({ key, label: key, value: formatFieldValue(value), mono: false });
    }
    const otherChunks = other.done();
    if (otherChunks.length) {
      blocks.push({
        key: '__other',
        label: this.i18n.translate('forms.answers.other'),
        chunks: otherChunks,
      });
    }
    return blocks;
  });

  private cell(f: FormFieldDef, label: string, raw: unknown): AnswerCell {
    const value = formatAnswer(f, raw, {
      lang: this.i18n.locale(),
      yes: this.i18n.translate('common.yes'),
      no: this.i18n.translate('common.no'),
    });
    return {
      key: f.key,
      label:
        f.type === 'computed'
          ? `${label} · ${this.i18n.translate('forms.answers.computed')}`
          : label,
      value,
      mono: MONO.has(f.type),
    };
  }

  /** The stored value of a computed field, else the value of its rule. */
  private computedValue(
    f: FormFieldDef,
    data: Readonly<Record<string, unknown>>,
    ctx: Record<string, unknown>,
  ): unknown {
    if (!isEmptyAnswer(data[f.key]) || !f.compute) return data[f.key];
    try {
      return evalJsonLogic(f.compute, ctx);
    } catch {
      // A rule the engine cannot run gives no value, as in the form.
      return null;
    }
  }
}

/** Collects the rows of a section: short cells in pairs, the rest one per row. */
class ChunkBuilder {
  private readonly chunks: AnswerChunk[] = [];
  private rows: AnswerRow[] = [];
  private cells: AnswerCell[] = [];

  cell(cell: AnswerCell): void {
    this.cells.push(cell);
  }

  row(row: AnswerRow): void {
    this.flushCells();
    this.rows.push(row);
  }

  positions(chunk: AnswerChunk): void {
    this.flushRows();
    this.chunks.push(chunk);
  }

  done(): AnswerChunk[] {
    this.flushRows();
    return this.chunks;
  }

  private flushCells(): void {
    if (!this.cells.length) return;
    this.rows.push({ kind: 'grid', key: this.cells[0].key, cells: this.cells });
    this.cells = [];
  }

  private flushRows(): void {
    this.flushCells();
    if (!this.rows.length) return;
    const first = this.rows[0];
    const key = first.kind === 'text' ? first.cell.key : first.key;
    this.chunks.push({ kind: 'group', key, rows: this.rows });
    this.rows = [];
  }
}

/**
 * A `table` answer: a list of rows. Rows that are objects give the columns by their keys;
 * any other value shows as text.
 */
function tableRow(key: string, label: string, raw: unknown): AnswerRow {
  const list = Array.isArray(raw) ? raw : [];
  const objects = list.filter(
    (r): r is Record<string, unknown> => typeof r === 'object' && r !== null && !Array.isArray(r),
  );
  if (!objects.length || objects.length !== list.length) {
    return {
      kind: 'text',
      cell: { key, label, value: formatFieldValue(raw), mono: false },
      markdown: false,
    };
  }
  const columns = [...new Set(objects.flatMap((r) => Object.keys(r)))];
  const rows = objects.map((r) => columns.map((c) => formatFieldValue(r[c])));
  return { kind: 'table', key, label, columns, rows };
}
