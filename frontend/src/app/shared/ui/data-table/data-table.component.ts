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
  templateUrl: './data-table.component.html',
  styleUrl: './data-table.component.scss',
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
