import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';

/**
 * The header every page starts with: breadcrumbs, title, subtitle and actions.
 *
 * One component owns the whole block, so the breadcrumb can never drift away
 * from the title it belongs to. Before this, each page built its own `<header>`
 * and the breadcrumb lived in the shell, which gave a different alignment on a
 * `wide` route than on a normal one.
 *
 * Put actions in the `actions` slot:
 *
 * ```html
 * <app-page-header [title]="'invoices.title' | t" [subtitle]="'invoices.subtitle' | t">
 *   <app-button actions (click)="add()">…</app-button>
 * </app-page-header>
 * ```
 */
@Component({
  selector: 'app-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BreadcrumbsComponent],
  templateUrl: './page-header.component.html',
  styleUrl: './page-header.component.scss',
})
export class PageHeaderComponent {
  readonly title = input.required<string>();
  readonly subtitle = input<string | null>(null);
}
