import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { ApplicationListItem, Uuid } from '@core/api/models';
import {
  BadgeComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
} from '@shared/ui';

/**
 * Aufgaben (#64): Anträge mit ausstehender Entscheidung für die eigene Rolle
 * (vote-States, in denen der Nutzer abstimmen darf). Tabellarisch; Klick auf eine
 * Zeile öffnet die Detailansicht (dort liegt das Abstimmen / der Übergang).
 */
@Component({
  selector: 'app-tasks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, TranslatePipe, BadgeComponent, DataTableComponent, CellDirective],
  template: `
    <header class="tasks__head">
      <h1 class="tasks__title">{{ 'tasks.title' | t }}</h1>
      <p class="tasks__sub">{{ 'tasks.subtitle' | t }}</p>
    </header>

    @if (loading()) {
      <p class="tasks__muted" aria-live="polite">{{ 'tasks.loading' | t }}</p>
    } @else {
      <app-data-table
        [columns]="columns()"
        [rows]="tasks()"
        [emptyText]="'tasks.empty' | t"
        [clickable]="true"
        (rowClick)="open($any($event).id)"
      >
        <ng-template appCell="title" let-r>{{ titleOf($any(r)) }}</ng-template>
        <ng-template appCell="state" let-r>
          <app-badge [color]="$any(r).state?.color">{{ $any(r).state?.label }}</app-badge>
        </ng-template>
        <ng-template appCell="amount" let-r>{{ $any(r).amount ? ($any(r).amount + ' ' + ($any(r).currency ?? '')) : '—' }}</ng-template>
        <ng-template appCell="createdAt" let-r>{{ $any(r).createdAt | date: 'mediumDate' }}</ng-template>
      </app-data-table>
    }
  `,
  styles: [
    `
      :host { display: flex; flex-direction: column; gap: var(--space-4); }
      .tasks__title { margin: 0; }
      .tasks__sub { color: var(--color-text-muted); font-size: var(--fs-sm); margin: var(--space-1) 0 0; }
      .tasks__muted { color: var(--color-text-muted); }
      .tasks__actions { display: inline-flex; gap: var(--space-2); justify-content: flex-end; }
    `,
  ],
})
export class TasksComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);

  protected readonly tasks = signal<ApplicationListItem[]>([]);
  protected readonly loading = signal(true);

  protected readonly columns = signal<ColumnDef[]>([
    { key: 'title', label: this.i18n.translate('tasks.col.title') },
    { key: 'state', label: this.i18n.translate('tasks.col.state') },
    { key: 'amount', label: this.i18n.translate('tasks.col.amount'), align: 'end', width: '10rem' },
    { key: 'createdAt', label: this.i18n.translate('tasks.col.created'), width: '10rem' },
  ]);

  /** Antragstitel (System-Titelfeld) mit Fallback. */
  protected titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  constructor() {
    this.reload();
  }

  private reload(): void {
    this.api.listTasks().subscribe({
      next: (t) => {
        this.tasks.set(t);
        this.loading.set(false);
      },
      error: () => {
        this.tasks.set([]);
        this.loading.set(false);
      },
    });
  }

  protected open(id: Uuid): void {
    void this.router.navigate(['/applications', id]);
  }
}
