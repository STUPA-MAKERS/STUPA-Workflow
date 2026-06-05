import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type BadgeVariant = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'info';

/** Status-Chip (z. B. Antrags-Status, Vote-Ergebnis). */
@Component({
  selector: 'app-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge" [class]="'badge--' + variant"><ng-content /></span>`,
  styles: [
    `
      .badge {
        display: inline-flex;
        align-items: center;
        padding: var(--space-1) var(--space-3);
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
        line-height: 1.4;
        border-radius: var(--radius-pill);
        white-space: nowrap;
      }
      .badge--neutral {
        background: var(--color-surface-sunken);
        color: var(--color-text-muted);
      }
      .badge--primary {
        background: var(--color-primary-subtle);
        color: var(--color-primary);
      }
      .badge--success {
        background: var(--color-success-subtle);
        color: var(--color-success);
      }
      .badge--warning {
        background: var(--color-warning-subtle);
        color: var(--color-warning);
      }
      .badge--danger {
        background: var(--color-danger-subtle);
        color: var(--color-danger);
      }
      .badge--info {
        background: var(--color-info-subtle);
        color: var(--color-info);
      }
    `,
  ],
})
export class BadgeComponent {
  @Input() variant: BadgeVariant = 'neutral';
}
