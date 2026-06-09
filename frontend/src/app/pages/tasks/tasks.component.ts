import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { ApplicationListItem, Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  IconComponent,
  ToastService,
} from '@shared/ui';
import { stateBadgeVariant } from '../applications/applications.util';

/**
 * Aufgaben (#64): Anträge mit ausstehender Entscheidung für die eigene Rolle
 * (vote/approval-States, in denen der Nutzer handeln darf). Tabellarisch; Klick auf
 * eine Zeile öffnet die Detailansicht (dort liegt Annehmen/Ablehnen bzw. Abstimmen).
 */
@Component({
  selector: 'app-tasks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, TranslatePipe, BadgeComponent, ButtonComponent, DataTableComponent, CellDirective, IconComponent],
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
          <app-badge [variant]="stateVariant($any(r).state?.category)">{{ $any(r).state?.label }}</app-badge>
        </ng-template>
        <ng-template appCell="amount" let-r>{{ $any(r).amount ? ($any(r).amount + ' ' + ($any(r).currency ?? '')) : '—' }}</ng-template>
        <ng-template appCell="createdAt" let-r>{{ $any(r).createdAt | date: 'mediumDate' }}</ng-template>
        <ng-template appCell="actions" let-r>
          @if ($any(r).state?.kind === 'approval') {
            <span class="tasks__actions" (click)="$event.stopPropagation()">
              <app-button
                variant="success"
                size="sm"
                [iconOnly]="true"
                [ariaLabel]="'tasks.accept' | t"
                [loading]="deciding() === $any(r).id"
                (click)="decide($any(r).id, 'accept')"
              ><app-icon name="check" [size]="16" /></app-button>
              <app-button
                variant="danger"
                size="sm"
                [iconOnly]="true"
                [ariaLabel]="'tasks.reject' | t"
                [loading]="deciding() === $any(r).id"
                (click)="decide($any(r).id, 'reject')"
              ><app-icon name="remove" [size]="16" /></app-button>
            </span>
          }
        </ng-template>
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
  protected readonly stateVariant = stateBadgeVariant;

  private readonly toast = inject(ToastService);
  protected readonly deciding = signal<Uuid | null>(null);

  protected readonly columns = signal<ColumnDef[]>([
    { key: 'title', label: this.i18n.translate('tasks.col.title') },
    { key: 'state', label: this.i18n.translate('tasks.col.state') },
    { key: 'amount', label: this.i18n.translate('tasks.col.amount'), align: 'end', width: '10rem' },
    { key: 'createdAt', label: this.i18n.translate('tasks.col.created'), width: '10rem' },
    { key: 'actions', label: this.i18n.translate('tasks.col.actions'), align: 'end', width: '7rem' },
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

  /** Approval-Task inline entscheiden (#28). Bei Erfolg verschwindet die Aufgabe. */
  protected decide(id: Uuid, decision: 'accept' | 'reject'): void {
    if (this.deciding()) return;
    this.deciding.set(id);
    this.api.submitApproval(id, decision).subscribe({
      next: () => {
        this.deciding.set(null);
        this.toast.success(this.i18n.translate('tasks.decided'));
        this.reload();
      },
      error: (err: { status?: number }) => {
        this.deciding.set(null);
        const key =
          err.status === 403
            ? 'tasks.forbidden'
            : err.status === 409
              ? 'tasks.conflict'
              : 'tasks.error';
        this.toast.error(this.i18n.translate(key));
        this.reload();
      },
    });
  }
}
