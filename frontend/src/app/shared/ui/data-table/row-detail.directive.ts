import { Directive, TemplateRef, inject } from '@angular/core';

/**
 * Markiert ein `<ng-template>` als ausklappbare Detail-Zeile der
 * {@link DataTableComponent}: `<ng-template appRowDetail let-row>…`. Wird je
 * Zeile gerendert, für die `isExpanded(row)` true ist (volle Breite darunter).
 */
@Directive({ selector: '[appRowDetail]', standalone: true })
export class RowDetailDirective {
  readonly tpl = inject<TemplateRef<{ $implicit: unknown }>>(TemplateRef);
}
