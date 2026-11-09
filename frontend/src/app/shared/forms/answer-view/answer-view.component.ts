import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import type { FieldType, FormFieldDef, FormSection } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { formatAnswer, formatFieldValue, isEmptyAnswer } from '../answer-format';
import { langAttr, resolvedI18nLang, resolveI18n } from '../i18n-text';
import { evalJsonLogic, isFieldVisible } from '../jsonlogic';
import { PositionsViewComponent } from '../positions-view/positions-view.component';
import { runs } from '@shared/util/immutable';
import { FieldGroupComponent, FieldRowComponent, SectionComponent } from '@stupa-makers/ui-kit';

/** One answer as a label and its text. */
export interface AnswerCell {
  readonly key: string;
  readonly label: string;
  readonly value: string;
  /** Mono face: IBAN and amounts. */
  readonly mono: boolean;
  /** `lang` of the label: a form text in a fallback language (app spec 000523). */
  readonly labelLang: string | null;
  /** `lang` of the value: the language of the application for free text. */
  readonly valueLang: string | null;
}

/** A row of the field group: short fields side by side, or one long field. */
export type AnswerRow =
  | { readonly kind: 'grid'; readonly key: string; readonly cells: readonly AnswerCell[] }
  | { readonly kind: 'text'; readonly cell: AnswerCell; readonly markdown: boolean }
  | {
      readonly kind: 'table';
      readonly key: string;
      readonly label: string;
      readonly labelLang: string | null;
      readonly valueLang: string | null;
      readonly columns: readonly string[];
      readonly rows: readonly (readonly string[])[];
    };

/** A run of rows in one field group, or the cost positions in their own block. */
export type AnswerChunk =
  | { readonly kind: 'group'; readonly key: string; readonly rows: readonly AnswerRow[] }
  | {
      readonly kind: 'positions';
      readonly key: string;
      readonly label: string;
      readonly value: unknown;
    };

/** A section of the form with its visible answers. */
export interface AnswerBlock {
  readonly key: string;
  readonly label: string;
  readonly labelLang: string | null;
  readonly chunks: readonly AnswerChunk[];
}

/** One shown answer before the grouping: a short cell, a full-width row or the positions. */
type AnswerPiece =
  | { readonly kind: 'cell'; readonly cell: AnswerCell }
  | { readonly kind: 'row'; readonly row: AnswerRow }
  | { readonly kind: 'positions'; readonly chunk: AnswerChunk };

/** Field types that the detail never shows: display text, markers and files (the files
 *  have the block "Anhänge" with the scan state). */
const NOT_SHOWN: ReadonlySet<FieldType> = new Set(['markdown', 'section', 'file']);
/** Field types in the mono face. */
const MONO: ReadonlySet<FieldType> = new Set(['iban', 'currency', 'funding']);
/** Field types whose answer is the free text of the applicant, in the language of the application. */
const FREE_TEXT: ReadonlySet<FieldType> = new Set(['text', 'textarea']);
/** Field types whose answer is the label of an option, a form text. */
const OPTION: ReadonlySet<FieldType> = new Set(['select', 'gremium_select', 'budget_select']);

/**
 * The answers of an application, read-only (the table "Darstellung der
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
 *   is an empty answer, so it shows nothing.
 * - Keys without a field (an answer of an older form version) come last under
 *   "Weitere Angaben" as plain text.
 */
@Component({
  selector: 'app-answer-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SectionComponent, FieldGroupComponent, FieldRowComponent, MarkdownViewComponent, PositionsViewComponent],
  templateUrl: './answer-view.component.html',
  styleUrl: './answer-view.component.scss',
})
export class AnswerViewComponent {
  private readonly i18n = inject(I18nService);

  readonly sections = input.required<readonly FormSection[]>();
  readonly data = input.required<Readonly<Record<string, unknown>>>();
  /** More variables for `visibleIf` and `compute`, for example `has_budget`. */
  readonly context = input<Readonly<Record<string, unknown>>>({});
  /**
   * The language of the application (`lang`, the UI language at submit). Free text in
   * another language than the UI gets it as `lang` (app spec 000523). `null`: unknown.
   */
  readonly contentLang = input<string | null>(null);
  /** Keys the page shows elsewhere, for example the title in the header. */
  readonly skipKeys = input<readonly string[]>(['title']);
  /** The text when no answer shows. Leave it empty to show nothing. */
  readonly emptyText = input('');
  /** The surface of the rows; see `app-field-group`. */
  readonly surface = input<1 | 2 | 3>(2);

  /** Answers without a field come from an older form version and show last, as plain text. */
  readonly blocks = computed<readonly AnswerBlock[]>(() => {
    const lang = this.i18n.uiLocale();
    const data = this.data();
    const ctx = { ...this.context(), ...data };
    const skip: ReadonlySet<string> = new Set(this.skipKeys());
    const known: ReadonlySet<string> = new Set(
      this.sections().flatMap((s) => s.fields.map((f) => f.key)),
    );
    const shown = (f: FormFieldDef): boolean =>
      !skip.has(f.key) && !NOT_SHOWN.has(f.type) && isFieldVisible(f.visibleIf, ctx);
    const textLang = langAttr(this.contentLang(), lang);
    const sectionBlocks = this.sections().map((section) => ({
      key: section.key,
      label: resolveI18n(section.label, lang),
      labelLang: langAttr(resolvedI18nLang(section.label, lang), lang),
      chunks: chunksOf(section.fields.filter(shown).flatMap((f) => this.piece(f, data, ctx, lang))),
    }));
    const otherChunks = chunksOf(
      Object.entries(data)
        .filter(([key, value]) => !known.has(key) && !skip.has(key) && !isEmptyAnswer(value))
        .map(([key, value]) => ({
          kind: 'cell' as const,
          cell: {
            key,
            label: key,
            value: formatFieldValue(value),
            mono: false,
            labelLang: null,
            valueLang: textLang,
          },
        })),
    );
    const other = {
      key: '__other',
      label: this.i18n.translate('forms.answers.other'),
      labelLang: null,
      chunks: otherChunks,
    };
    return [...sectionBlocks, other].filter((b) => b.chunks.length);
  });

  /** The piece of a shown field, or none when its answer is empty. */
  private piece(
    f: FormFieldDef,
    data: Readonly<Record<string, unknown>>,
    ctx: Readonly<Record<string, unknown>>,
    lang: string,
  ): readonly AnswerPiece[] {
    const raw = f.type === 'computed' ? this.computedValue(f, data, ctx) : data[f.key];
    if (isEmptyAnswer(raw)) return [];
    const label = resolveI18n(f.label, lang);
    const labelLang = langAttr(resolvedI18nLang(f.label, lang), lang);
    switch (f.type) {
      case 'positions':
        return [{ kind: 'positions', chunk: { kind: 'positions', key: f.key, label, value: raw } }];
      case 'table':
        return [
          {
            kind: 'row',
            row: tableRow(f.key, label, raw, labelLang, langAttr(this.contentLang(), lang)),
          },
        ];
      case 'textarea':
        return [
          {
            kind: 'row',
            row: { kind: 'text', cell: this.cell(f, label, labelLang, raw), markdown: true },
          },
        ];
      default:
        return [{ kind: 'cell', cell: this.cell(f, label, labelLang, raw) }];
    }
  }

  private cell(f: FormFieldDef, label: string, labelLang: string | null, raw: unknown): AnswerCell {
    const lang = this.i18n.uiLocale();
    const value = formatAnswer(f, raw, {
      lang,
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
      labelLang,
      valueLang: this.valueLang(f, raw, lang),
    };
  }

  /**
   * The language of a shown answer: the application language for free text, the language
   * of the option label for a choice, else none (numbers, dates and Ja/Nein are UI text).
   */
  private valueLang(f: FormFieldDef, raw: unknown, lang: string): string | null {
    if (FREE_TEXT.has(f.type)) return langAttr(this.contentLang(), lang);
    if (!OPTION.has(f.type)) return null;
    const option = f.options?.find((o) => o.value === raw);
    return langAttr(resolvedI18nLang(option?.label, lang), lang);
  }

  /** The stored value of a computed field, else the value of its rule. */
  private computedValue(
    f: FormFieldDef,
    data: Readonly<Record<string, unknown>>,
    ctx: Readonly<Record<string, unknown>>,
  ): unknown {
    if (!isEmptyAnswer(data[f.key]) || !f.compute) return data[f.key];
    try {
      return evalJsonLogic(f.compute, ctx);
    } catch {
      return null;
    }
  }
}

/** The rows of a run of cells and rows: neighbouring short cells share one grid row. */
function rowsOf(pieces: readonly AnswerPiece[]): readonly AnswerRow[] {
  const cellRuns = runs(pieces, (a, b) => a.kind === 'cell' && b.kind === 'cell');
  return cellRuns.flatMap((run): readonly AnswerRow[] => {
    const cells = run.flatMap((p) => (p.kind === 'cell' ? [p.cell] : []));
    const rows = run.flatMap((p) => (p.kind === 'row' ? [p.row] : []));
    return cells.length ? [{ kind: 'grid', key: cells[0].key, cells }] : rows;
  });
}

/** The chunks of a section: the cost positions alone, everything between them in one group. */
function chunksOf(pieces: readonly AnswerPiece[]): readonly AnswerChunk[] {
  return runs(pieces, (a, b) => a.kind !== 'positions' && b.kind !== 'positions').flatMap(
    (run): readonly AnswerChunk[] => {
      const head = run[0];
      if (head.kind === 'positions') return [head.chunk];
      const rows = rowsOf(run);
      const first = rows[0];
      return [{ kind: 'group', key: first.kind === 'text' ? first.cell.key : first.key, rows }];
    },
  );
}

/**
 * A `table` answer: a list of rows. Rows that are objects give the columns by their keys;
 * any other value shows as text.
 */
function tableRow(
  key: string,
  label: string,
  raw: unknown,
  labelLang: string | null,
  valueLang: string | null,
): AnswerRow {
  const list = Array.isArray(raw) ? raw : [];
  const objects = list.filter(
    (r): r is Record<string, unknown> => typeof r === 'object' && r !== null && !Array.isArray(r),
  );
  if (!objects.length || objects.length !== list.length) {
    return {
      kind: 'text',
      cell: { key, label, value: formatFieldValue(raw), mono: false, labelLang, valueLang },
      markdown: false,
    };
  }
  const columns = [...new Set(objects.flatMap((r) => Object.keys(r)))];
  const rows = objects.map((r) => columns.map((c) => formatFieldValue(r[c])));
  return { kind: 'table', key, label, labelLang, valueLang, columns, rows };
}
