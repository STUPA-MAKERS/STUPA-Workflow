import { NgTemplateOutlet } from '@angular/common';
import {
  type AfterContentInit,
  ChangeDetectionStrategy,
  Component,
  ContentChild,
  ContentChildren,
  EventEmitter,
  Input,
  Output,
  type QueryList,
  type TemplateRef,
  signal,
} from '@angular/core';
import { CellDirective } from './cell.directive';
import { RowDetailDirective } from './row-detail.directive';

/** Spalten-Definition der {@link DataTableComponent}. */
export interface ColumnDef {
  key: string;
  label: string;
  align?: 'start' | 'end';
  /** CSS-Breite (z. B. `12rem`); optional. */
  width?: string;
}

/**
 * Geteilte, datengetriebene Tabelle (#26). Spalten kommen als {@link ColumnDef}-
 * Liste; einzelne Zellen lassen sich per `<ng-template appCell="key" let-row>`
 * frei rendern (Badges/Buttons/Links). Ohne Template wird `row[key]` als Text
 * gezeigt. Optional als Box (Standard) und mit Zeilen-Klick.
 *
 * So bleiben alle Admin-Tabellen visuell konsistent (eine Quelle für Kopf/Rahmen/
 * Hover/Empty-State), statt jede Seite ihr eigenes `<table>` zu bauen.
 */
@Component({
  selector: 'app-data-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet],
  template: `
    <div class="dt" [class.dt--boxed]="boxed">
      <table class="dt__table">
        <thead>
          <tr>
            @for (col of columns; track col.key) {
              <th scope="col" [style.text-align]="col.align ?? 'start'" [style.width]="col.width || null">{{ col.label }}</th>
            }
          </tr>
        </thead>
        <tbody>
          @for (row of rows; track trackRow(row, $index); let i = $index) {
            <tr [class.dt__row--clickable]="clickable" (click)="onRow(row)" [attr.tabindex]="clickable ? 0 : null" (keydown.enter)="onRow(row)">
              @for (col of columns; track col.key) {
                <td [style.text-align]="col.align ?? 'start'">
                  @if (cellFor(col.key); as tpl) {
                    <ng-container [ngTemplateOutlet]="tpl" [ngTemplateOutletContext]="{ $implicit: row, index: i }" />
                  } @else {
                    {{ text(row, col.key) }}
                  }
                </td>
              }
            </tr>
            @if (rowDetail && isExpanded && isExpanded(row)) {
              <tr class="dt__detail-row">
                <td [attr.colspan]="columns.length">
                  <ng-container [ngTemplateOutlet]="rowDetail.tpl" [ngTemplateOutletContext]="{ $implicit: row }" />
                </td>
              </tr>
            }
          } @empty {
            <tr>
              <td class="dt__empty" [attr.colspan]="columns.length">{{ emptyText }}</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: [
    `
      .dt--boxed {
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        overflow: hidden;
      }
      .dt__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .dt__table th {
        text-align: start;
        padding: var(--space-3) var(--space-4);
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--color-text-muted);
        background: var(--color-surface-sunken);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .dt__table td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
        vertical-align: middle;
      }
      .dt__row--clickable {
        cursor: pointer;
      }
      .dt__table tbody tr:hover td,
      .dt__row--clickable:focus-visible td {
        background: var(--color-surface-sunken);
      }
      .dt__detail-row > td {
        padding: 0;
        background: var(--color-surface-sunken);
      }
      .dt__empty {
        text-align: center;
        color: var(--color-text-muted);
        padding: var(--space-6) !important;
      }
    `,
  ],
})
export class DataTableComponent implements AfterContentInit {
  @Input() columns: ColumnDef[] = [];
  @Input() rows: readonly unknown[] = [];
  @Input() emptyText = '—';
  @Input() boxed = true;
  /** Stabiler Track-Key je Zeile (sonst Index). */
  @Input() rowKey?: (row: unknown, index: number) => unknown;
  /** Macht Zeilen klickbar (Cursor/Tab/Enter) + emittiert `rowClick`. */
  @Input() clickable = false;
  @Output() rowClick = new EventEmitter<unknown>();

  /** Prädikat: für welche Zeilen die Detail-Zeile gezeigt wird. */
  @Input() isExpanded?: (row: unknown) => boolean;

  @ContentChildren(CellDirective) private cellDirs!: QueryList<CellDirective>;
  @ContentChild(RowDetailDirective) protected rowDetail?: RowDetailDirective;
  private readonly cellMap = signal<Map<string, TemplateRef<unknown>>>(new Map());

  ngAfterContentInit(): void {
    const build = (): void =>
      this.cellMap.set(new Map(this.cellDirs.map((c) => [c.key, c.tpl as TemplateRef<unknown>])));
    build();
    this.cellDirs.changes.subscribe(build);
  }

  protected cellFor(key: string): TemplateRef<unknown> | null {
    return this.cellMap().get(key) ?? null;
  }

  protected text(row: unknown, key: string): unknown {
    return (row as Record<string, unknown>)[key];
  }

  protected trackRow(row: unknown, index: number): unknown {
    return this.rowKey ? this.rowKey(row, index) : index;
  }

  protected onRow(row: unknown): void {
    if (this.clickable) this.rowClick.emit(row);
  }
}
