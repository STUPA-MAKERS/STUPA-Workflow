import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  BudgetPotCreateBody,
  BudgetPotInfo,
  BudgetPotUpdateBody,
  Uuid,
} from '@core/api/models';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { CurrencyInputComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminOptionsService } from '../admin/admin-options.service';

/** Editier-Formularzustand eines Topfs (flach). */
interface PotForm {
  gremiumId: string;
  name: string;
  total: string;
  currency: string;
  period: string;
  active: boolean;
}

function emptyForm(): PotForm {
  return { gremiumId: '', name: '', total: '', currency: 'EUR', period: '', active: true };
}

/** Haushaltsperioden-Optionen: Kalenderjahre + akademische Spannen rund ums laufende Jahr. */
function buildPeriodOptions(): SelectOption[] {
  const now = new Date().getFullYear();
  const opts: SelectOption[] = [];
  for (let y = now + 1; y >= now - 3; y--) {
    opts.push({ value: String(y), label: String(y) });
    opts.push({ value: `${y}/${(y + 1) % 100}`, label: `${y}/${(y + 1) % 100}` });
  }
  return opts;
}

/**
 * Budget-Topf-Verwaltung (#76, T-17). **Flaches** Konfigurieren der Töpfe gegen
 * die echte Budget-API (`POST/GET/PATCH /budget-pots`, P(`budget.manage`)) —
 * Anlegen + Bearbeiten von Stammdaten (Gremium, Name, Limit, Währung, Periode,
 * aktiv). Das große hierarchische Budget-Feature ist bewusst **separat/später**;
 * hier nur das scharfe Schalten des flachen Konfigurierens.
 */
@Component({
  selector: 'app-budget-pots',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CardComponent, SelectComponent, CurrencyInputComponent],
  template: `
    <header class="pots__head">
      <h1 class="pots__title">{{ 'budget.pots.title' | t }}</h1>
      <p class="pots__subtitle">{{ 'budget.pots.subtitle' | t }}</p>
    </header>

    <app-card [heading]="(editingId() ? 'budget.pots.edit' : 'budget.pots.create') | t">
      <form class="pots__form" (submit)="submit($event)">
        <div class="pots__grid">
          <app-select
            name="gremium"
            [label]="'budget.pots.gremium' | t"
            [placeholder]="'budget.pots.gremiumPlaceholder' | t"
            [options]="gremiumOptions()"
            [required]="true"
            [hint]="editingId() ? ('budget.pots.gremiumLocked' | t) : ''"
            [ngModel]="form().gremiumId"
            (ngModelChange)="patch('gremiumId', $event)"
          />
          <div class="field">
            <label class="field__label" for="pot-name">{{ 'budget.pots.name' | t }}</label>
            <input
              id="pot-name"
              class="field__control"
              name="name"
              [ngModel]="form().name"
              (ngModelChange)="patch('name', $event)"
              required
            />
          </div>
          <div class="field">
            <label class="field__label" for="pot-total">{{ 'budget.pots.total' | t }}</label>
            <app-currency-input
              name="total"
              [placeholder]="'budget.pots.totalPlaceholder' | t"
              [ariaLabel]="'budget.pots.total' | t"
              [ngModel]="form().total"
              (ngModelChange)="patch('total', $event)"
            />
          </div>
          <app-select
            name="currency"
            [label]="'budget.pots.currency' | t"
            [options]="currencyOptions"
            [ngModel]="form().currency"
            (ngModelChange)="patch('currency', $event)"
          />
          <app-select
            name="period"
            [label]="'budget.pots.period' | t"
            [placeholder]="'budget.pots.periodPlaceholder' | t"
            [options]="periodOptions"
            [ngModel]="form().period"
            (ngModelChange)="patch('period', $event)"
          />
          <div class="field">
            <app-select
              name="active"
              [label]="'budget.pots.active' | t"
              [options]="activeOptions()"
              [ngModel]="form().active ? 'true' : 'false'"
              (ngModelChange)="patch('active', $event === 'true')"
            />
          </div>
        </div>

        <div class="pots__actions">
          <app-button
            type="submit"
            size="sm"
            [disabled]="!canSubmit()"
            [loading]="saving()"
          >
            {{ (editingId() ? 'budget.pots.save' : 'budget.pots.add') | t }}
          </app-button>
          @if (editingId()) {
            <app-button type="button" variant="ghost" size="sm" (click)="cancelEdit()">
              {{ 'budget.pots.cancel' | t }}
            </app-button>
          }
        </div>
      </form>
    </app-card>

    <section class="pots__list" [attr.aria-label]="'budget.pots.title' | t">
      @if (loading()) {
        <p class="pots__status" aria-live="polite">{{ 'budget.pots.loading' | t }}</p>
      } @else if (loadError()) {
        <p class="pots__status pots__status--error" role="alert">{{ 'budget.pots.error' | t }}</p>
      } @else if (!pots().length) {
        <p class="pots__status">{{ 'budget.pots.empty' | t }}</p>
      } @else {
        <table class="pots__table">
          <thead>
            <tr>
              <th>{{ 'budget.pots.name' | t }}</th>
              <th>{{ 'budget.pots.total' | t }}</th>
              <th>{{ 'budget.pots.period' | t }}</th>
              <th>{{ 'budget.pots.active' | t }}</th>
              <th class="pots__th-actions">{{ 'budget.pots.actions' | t }}</th>
            </tr>
          </thead>
          <tbody>
            @for (pot of pots(); track pot.id) {
              <tr [class.pots__row--editing]="editingId() === pot.id">
                <td>{{ pot.name }}</td>
                <td>{{ pot.total === null ? '—' : money(pot.total, pot.currency) }}</td>
                <td>{{ pot.period || '—' }}</td>
                <td>{{ (pot.active ? 'budget.pots.yes' : 'budget.pots.no') | t }}</td>
                <td class="pots__th-actions">
                  <app-button variant="secondary" size="sm" (click)="startEdit(pot)">
                    {{ 'budget.pots.editAction' | t }}
                  </app-button>
                </td>
              </tr>
            }
          </tbody>
        </table>
      }
    </section>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .pots__title {
        margin: 0;
      }
      .pots__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .pots__grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
        gap: var(--space-4);
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .field__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text);
      }
      .field__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-surface);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .field__control:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 1px;
      }
      .pots__actions {
        display: flex;
        gap: var(--space-2);
        margin-top: var(--space-4);
      }
      .pots__status {
        color: var(--color-text-muted);
        padding: var(--space-4) 0;
      }
      .pots__status--error {
        color: var(--color-danger);
      }
      .pots__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-md);
      }
      .pots__table th,
      .pots__table td {
        text-align: left;
        padding: var(--space-3);
        border-bottom: var(--border-width) solid var(--color-border);
      }
      .pots__th-actions {
        text-align: right;
      }
      .pots__row--editing {
        background: var(--color-primary-subtle);
      }
    `,
  ],
})
export class BudgetPotsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly options = inject(AdminOptionsService);

  readonly pots = signal<BudgetPotInfo[]>([]);
  readonly gremiumOptions = signal<SelectOption[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal(false);
  readonly saving = signal(false);
  readonly editingId = signal<Uuid | null>(null);
  readonly form = signal<PotForm>(emptyForm());

  readonly activeOptions = computed<SelectOption[]>(() => [
    { value: 'true', label: this.i18n.translate('budget.pots.yes') },
    { value: 'false', label: this.i18n.translate('budget.pots.no') },
  ]);

  /** Währungen als Dropdown statt Freitext (#6). */
  readonly currencyOptions: SelectOption[] = ['EUR', 'CHF', 'USD', 'GBP'].map((c) => ({
    value: c,
    label: c,
  }));

  /** Haushaltsperioden als Dropdown (#6): laufendes Jahr ± Umgebung. */
  readonly periodOptions: SelectOption[] = buildPeriodOptions();

  readonly canSubmit = computed(() => {
    const f = this.form();
    // Beim Bearbeiten ist das Gremium fix (PATCH ändert es nicht); beim Anlegen Pflicht.
    const gremiumOk = this.editingId() ? true : !!f.gremiumId;
    return gremiumOk && f.name.trim().length > 0 && !this.saving();
  });

  constructor() {
    this.options
      .gremiumOptions()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (opts) => this.gremiumOptions.set(opts),
        error: () => this.gremiumOptions.set([]),
      });
    this.reload();
  }

  money(value: number, currency: string): string {
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(value);
  }

  patch<K extends keyof PotForm>(key: K, value: PotForm[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  startEdit(pot: BudgetPotInfo): void {
    this.editingId.set(pot.id);
    this.form.set({
      gremiumId: pot.gremiumId,
      name: pot.name,
      total: pot.total === null ? '' : String(pot.total),
      currency: pot.currency,
      period: pot.period ?? '',
      active: pot.active,
    });
  }

  cancelEdit(): void {
    this.editingId.set(null);
    this.form.set(emptyForm());
  }

  submit(event: Event): void {
    event.preventDefault();
    if (!this.canSubmit()) return;
    const f = this.form();
    const total = f.total.trim() === '' ? null : f.total.trim();
    const currency = f.currency.trim() || 'EUR';
    const period = f.period.trim() === '' ? null : f.period.trim();
    this.saving.set(true);

    const id = this.editingId();
    if (id) {
      const body: BudgetPotUpdateBody = {
        name: f.name.trim(),
        total,
        currency,
        period,
        active: f.active,
      };
      this.api.updateBudgetPot(id, body).subscribe({
        next: () => this.onSaved('budget.pots.toast.updated'),
        error: () => this.onSaveError(),
      });
    } else {
      const body: BudgetPotCreateBody = {
        gremiumId: f.gremiumId,
        name: f.name.trim(),
        total,
        currency,
        period,
        active: f.active,
      };
      this.api.createBudgetPot(body).subscribe({
        next: () => this.onSaved('budget.pots.toast.created'),
        error: () => this.onSaveError(),
      });
    }
  }

  private onSaved(key: 'budget.pots.toast.created' | 'budget.pots.toast.updated'): void {
    this.saving.set(false);
    this.toast.success(this.i18n.translate(key));
    this.cancelEdit();
    this.reload();
  }

  private onSaveError(): void {
    this.saving.set(false);
    this.toast.error(this.i18n.translate('budget.pots.toast.failed'));
  }

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.budgetPots().subscribe({
      next: (pots) => {
        this.pots.set(pots);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }
}
