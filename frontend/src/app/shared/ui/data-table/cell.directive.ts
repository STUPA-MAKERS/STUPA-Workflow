import { Directive, Input, TemplateRef, inject } from '@angular/core';

/**
 * Markiert ein `<ng-template>` als Zell-Renderer einer Spalte der
 * {@link DataTableComponent}: `<ng-template appCell="status" let-row>…`.
 * Der `let-row`-Kontext ist die jeweilige Zeile.
 */
@Directive({ selector: '[appCell]', standalone: true })
export class CellDirective {
  /** Spalten-Key, für den dieses Template gerendert wird. */
  @Input('appCell') key = '';
  readonly tpl = inject<TemplateRef<{ $implicit: unknown; index: number }>>(TemplateRef);
}
