import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  BadgeComponent,
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { downloadBlob } from '@shared/download.util';
import {
  type Account,
  BudgetTreeApi,
  type BudgetTreeNode,
  type Expense,
  type ExpenseKind,
  type FiscalYear,
  flattenBudgetOptions,
} from '../budget/budget-tree.api';
import { SimplifyPathPipe } from '@shared/budget-path';

/**
 * Ausgaben/Einnahmen-Tab (#25): tatsächliche Buchungen sehen/anlegen/verwalten.
 *
 * Eine Buchung ist **eigenständig** (Kostenstelle + HHJ wählbar) oder an einen
 * **Antrag gebunden** (ersetzt dessen gebundenen Betrag anteilig; Kostenstelle + HHJ
 * werden vom Antrag geerbt). Links filtert ein Kostenstellen-Baum (wie die Antragsliste);
 * die Liste lädt serverseitig per Infinite-Scroll nach.
 */
@Component({
  selector: 'app-expenses',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    LocalizedDatePipe,
    TranslatePipe,
    SimplifyPathPipe,
    BadgeComponent,
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    FilterBarComponent,
    FilterFieldComponent,
    FilterRangeComponent,
    IconComponent,
    SelectComponent,
    CostCentreTreeComponent,
  ],
  template: `
    <header class="exp__head">
      <div class="exp__headRow">
        <div>
          <h1 class="exp__title">{{ 'expenses.title' | t }}</h1>
          <p class="exp__subtitle">{{ 'expenses.subtitle' | t }}</p>
        </div>
        <div class="exp__headActions">
          <input
            class="exp__search"
            type="search"
            [placeholder]="'expenses.search' | t"
            [ngModel]="q()"
            (ngModelChange)="onSearch($event)"
            [attr.aria-label]="'expenses.search' | t"
          />
          <app-filter-bar [live]="true" [activeCount]="activeFilterCount()" (reset)="resetFilters()">
            <app-filter-field [label]="'expenses.filter.kind' | t">
              <div class="exp__kinds">
                <app-button [variant]="kind() === '' ? 'primary' : 'ghost'" size="sm" (click)="setKind('')">{{ 'expenses.filter.all' | t }}</app-button>
                <app-button [variant]="kind() === 'expense' ? 'primary' : 'ghost'" size="sm" (click)="setKind('expense')">{{ 'expenses.kind.expense' | t }}</app-button>
                <app-button [variant]="kind() === 'income' ? 'primary' : 'ghost'" size="sm" (click)="setKind('income')">{{ 'expenses.kind.income' | t }}</app-button>
              </div>
            </app-filter-field>
            <app-filter-field [label]="'expenses.filter.amountRange' | t">
              <app-filter-range>
                <app-currency-input start [placeholder]="'expenses.filter.amountMin' | t" [ariaLabel]="'expenses.filter.amountMin' | t" [ngModel]="amountMin()" (ngModelChange)="onAmountFilter('min', $event)" />
                <app-currency-input end [placeholder]="'expenses.filter.amountMax' | t" [ariaLabel]="'expenses.filter.amountMax' | t" [ngModel]="amountMax()" (ngModelChange)="onAmountFilter('max', $event)" />
              </app-filter-range>
            </app-filter-field>
            <app-filter-field [label]="'expenses.filter.dateRange' | t">
              <app-filter-range>
                <app-datepicker start [ariaLabel]="'expenses.filter.dateFrom' | t" [ngModel]="createdFrom()" (ngModelChange)="onDateFilter('from', $event)" />
                <app-datepicker end [ariaLabel]="'expenses.filter.dateTo' | t" [ngModel]="createdTo()" (ngModelChange)="onDateFilter('to', $event)" />
              </app-filter-range>
            </app-filter-field>
          </app-filter-bar>
          @if (canExport()) {
            <app-button variant="secondary" size="sm" (click)="onExport()" [loading]="exporting()">
              <span class="exp__btnIcon"><app-icon name="export" [size]="16" /> {{ 'expenses.export' | t }}</span>
            </app-button>
          }
          @if (canManage()) {
            <app-button variant="secondary" size="sm" (click)="openTransfer()">{{ 'expenses.transfer' | t }}</app-button>
            <app-button size="sm" (click)="openCreate()">{{ 'expenses.add' | t }}</app-button>
          }
        </div>
      </div>
    </header>

    <div class="exp__layout">
      <!-- Mobil (≤768px) einklappbar: Toggle nur dort sichtbar, Desktop zeigt
           den Baum unverändert immer (wie der Budget-Tab-Picker). -->
      <aside class="exp__tree">
        <button
          type="button"
          class="exp__treeToggle"
          [attr.aria-expanded]="treeOpen()"
          (click)="treeOpen.set(!treeOpen())"
        >
          {{ 'expenses.filter.costCentre' | t }}
          <app-icon [name]="treeOpen() ? 'chevron-up' : 'chevron-down'" [size]="14" />
        </button>
        <div class="exp__treeBody" [class.exp__treeBody--open]="treeOpen()">
          <app-cost-centre-tree
            [nodes]="budgetTree()"
            [selectedId]="budgetId()"
            [allLabel]="'expenses.filter.allCostCentres' | t"
            [ariaLabel]="'expenses.filter.costCentre' | t"
            (picked)="selectBudget($event); treeOpen.set(false)"
          />
        </div>
      </aside>

      <div class="exp__main">
        @if (loading()) {
          <p class="exp__status" aria-live="polite">{{ 'expenses.loading' | t }}</p>
        } @else {
          <div class="exp__tableWrap">
            <table class="exp__table">
              <thead>
                <tr>
                  <th scope="col" [attr.aria-sort]="ariaSort('createdAt')">
                    <button type="button" class="exp__sort" (click)="onSort('createdAt')">{{ 'expenses.col.date' | t }}{{ sortInd('createdAt') }}</button>
                  </th>
                  <th scope="col">{{ 'expenses.col.kind' | t }}</th>
                  <th scope="col">{{ 'expenses.col.description' | t }}</th>
                  <th scope="col">{{ 'expenses.col.costCentre' | t }}</th>
                  <th scope="col">{{ 'expenses.col.application' | t }}</th>
                  <th scope="col" class="exp__num" [attr.aria-sort]="ariaSort('amount')">
                    <button type="button" class="exp__sort" (click)="onSort('amount')">{{ 'expenses.col.amount' | t }}{{ sortInd('amount') }}</button>
                  </th>
                  @if (canManage()) { <th scope="col" class="exp__num"></th> }
                </tr>
              </thead>
              <tbody>
                @for (e of items(); track e.id) {
                  <tr [class.exp__tr--income]="e.kind === 'income'">
                    <td class="exp__cellDate">{{ e.createdAt | ldate: 'mediumDate' }}</td>
                    <td>
                      <app-badge [variant]="e.kind === 'income' ? 'success' : 'neutral'">{{ (e.kind === 'income' ? 'expenses.kind.income' : 'expenses.kind.expense') | t }}</app-badge>
                    </td>
                    <td class="exp__cellDesc">{{ e.description }}</td>
                    <td class="exp__mono">{{ e.pathKey ? (e.pathKey | simplifyPath) : '—' }}</td>
                    <td>
                      @if (e.applicationId) {
                        <a class="exp__appLink" [routerLink]="['/applications', e.applicationId]">{{ e.applicationTitle || ('expenses.linkedApplication' | t) }}</a>
                      } @else { — }
                    </td>
                    <td class="exp__num exp__amount" [class.exp__amount--income]="e.kind === 'income'">{{ e.kind === 'income' ? '+' : '−' }}{{ money(e.amount) }}</td>
                    @if (canManage()) {
                      <td class="exp__num">
                        <span class="exp__actions">
                          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.edit' | t" [title]="'action.edit' | t" (click)="openEdit(e)"><app-icon name="edit" /></app-button>
                          <app-button variant="ghost" size="sm" [iconOnly]="true" [ariaLabel]="'action.delete' | t" [title]="'action.delete' | t" (click)="askDelete(e)"><app-icon name="delete" /></app-button>
                        </span>
                      </td>
                    }
                  </tr>
                } @empty {
                  <tr>
                    <td class="exp__empty" [attr.colspan]="canManage() ? 7 : 6">{{ 'expenses.empty' | t }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          @if (hasMore()) {
            <div #sentinel class="exp__sentinel" aria-hidden="true"></div>
            <div class="exp__more">
              @if (loadingMore()) {
                <span class="exp__status">{{ 'expenses.loadingMore' | t }}</span>
              } @else {
                <app-button variant="secondary" size="sm" (click)="loadMore()">{{ 'expenses.loadMore' | t }}</app-button>
              }
            </div>
          }
          @if (total() > 0) {
            <p class="exp__count">{{ 'expenses.count' | t: { count: items().length, total: total() } }}</p>
          }
        }
      </div>
    </div>

    <!-- Anlegen -->
    <app-dialog [open]="createOpen()" [title]="'expenses.add' | t" [closeLabel]="'action.cancel' | t" (closed)="createOpen.set(false)">
      <form id="exp-create" class="exp__form" (submit)="create($event)">
        <div class="exp__kinds">
          <app-button type="button" [variant]="newKind() === 'expense' ? 'primary' : 'ghost'" size="sm" (click)="newKind.set('expense')">{{ 'expenses.kind.expense' | t }}</app-button>
          <app-button type="button" [variant]="newKind() === 'income' ? 'primary' : 'ghost'" size="sm" (click)="setNewKindIncome()">{{ 'expenses.kind.income' | t }}</app-button>
        </div>

        <label class="exp__label" for="exp-desc">{{ 'expenses.field.description' | t }}</label>
        <input id="exp-desc" class="exp__input" [ngModel]="newDescription()" (ngModelChange)="newDescription.set($event)" name="description" [placeholder]="'expenses.field.descriptionPlaceholder' | t" />

        <label class="exp__label" for="exp-amount">{{ 'expenses.field.amount' | t }}</label>
        <app-currency-input name="amount" [ngModel]="newAmount()" (ngModelChange)="newAmount.set($event)" [ariaLabel]="'expenses.field.amount' | t" />

        @if (newKind() === 'expense') {
          <label class="exp__label" for="exp-app">{{ 'expenses.field.linkApplication' | t }}</label>
          @if (newApplicationId()) {
            <div class="exp__picked">
              <span class="exp__pickedText">{{ appQuery() }}</span>
              <app-button type="button" variant="ghost" size="sm" (click)="clearApp()">{{ 'expenses.field.unlink' | t }}</app-button>
            </div>
            <p class="exp__hint">{{ 'expenses.field.inheritedCostCentre' | t }}</p>
          } @else {
            <div class="exp__typeahead">
              <input
                id="exp-app"
                class="exp__input"
                type="search"
                autocomplete="off"
                [ngModel]="appQuery()"
                (ngModelChange)="onAppSearch($event)"
                name="appSearch"
                [placeholder]="'expenses.field.linkApplicationPlaceholder' | t"
                role="combobox"
                [attr.aria-expanded]="appCandidates().length > 0"
                aria-autocomplete="list"
              />
              @if (appCandidates().length) {
                <ul class="exp__suggest" role="listbox">
                  @for (a of appCandidates(); track a.id) {
                    <li>
                      <button type="button" class="exp__suggestItem" (click)="pickApp(a)">{{ a.title }}</button>
                    </li>
                  }
                </ul>
              }
            </div>
          }
        }

        @if (!newApplicationId()) {
          <app-select name="cc" [label]="'expenses.field.costCentre' | t" [placeholder]="'expenses.field.costCentrePlaceholder' | t" [options]="costCentreOptions()" [required]="true" [ngModel]="newBudgetId()" (ngModelChange)="onPickBudget($event)" />
          @if (newBudgetId()) {
            @if (fiscalYearOptions().length) {
              <app-select name="fy" [label]="'expenses.field.fiscalYear' | t" [placeholder]="'expenses.field.fiscalYearPlaceholder' | t" [options]="fiscalYearOptions()" [required]="true" [ngModel]="newFiscalYearId()" (ngModelChange)="newFiscalYearId.set($event)" />
            } @else {
              <p class="exp__hint exp__hint--warn">{{ 'expenses.field.noFiscalYear' | t }}</p>
            }
          }
        }

        @if (accountOptions().length) {
          <app-select name="account" [label]="'expenses.field.account' | t" [placeholder]="'expenses.field.accountPlaceholder' | t" [options]="accountOptions()" [ngModel]="newAccountId()" (ngModelChange)="newAccountId.set($event)" />
        }
      </form>
      <div dialog-footer class="exp__dialogFoot">
        <app-button variant="ghost" (click)="createOpen.set(false)">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!canSubmitCreate()" [loading]="saving()" (click)="create($event)">{{ 'expenses.add' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Bearbeiten -->
    <app-dialog [open]="!!editing()" [title]="'expenses.edit' | t" [closeLabel]="'action.cancel' | t" (closed)="editing.set(null)">
      <form id="exp-edit" class="exp__form" (submit)="saveEdit($event)">
        <label class="exp__label" for="exp-edesc">{{ 'expenses.field.description' | t }}</label>
        <input id="exp-edesc" class="exp__input" [ngModel]="editDescription()" (ngModelChange)="editDescription.set($event)" name="edesc" />
        <label class="exp__label" for="exp-eamount">{{ 'expenses.field.amount' | t }}</label>
        <app-currency-input name="eamount" [ngModel]="editAmount()" (ngModelChange)="editAmount.set($event)" [ariaLabel]="'expenses.field.amount' | t" />
      </form>
      <div dialog-footer class="exp__dialogFoot">
        <app-button variant="ghost" (click)="editing.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button [loading]="saving()" (click)="saveEdit($event)">{{ 'action.save' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Löschen -->
    <app-dialog [open]="!!confirmDelete()" [title]="'expenses.delete.title' | t" [closeLabel]="'action.cancel' | t" (closed)="confirmDelete.set(null)">
      <p>{{ 'expenses.delete.body' | t: { description: confirmDelete()?.description ?? '' } }}</p>
      <div dialog-footer class="exp__dialogFoot">
        <app-button variant="ghost" (click)="confirmDelete.set(null)">{{ 'action.cancel' | t }}</app-button>
        <app-button variant="danger" [loading]="saving()" (click)="doDelete()">{{ 'expenses.delete.confirm' | t }}</app-button>
      </div>
    </app-dialog>

    <!-- Übertrag (KS → KS) -->
    <app-dialog [open]="transferOpen()" [title]="'expenses.transferTitle' | t" [closeLabel]="'action.cancel' | t" (closed)="transferOpen.set(false)">
      <form id="exp-transfer" class="exp__form" (submit)="createTransfer($event)">
        <app-select name="tfrom" [label]="'expenses.transferFrom' | t" [placeholder]="'expenses.field.costCentrePlaceholder' | t" [options]="costCentreOptions()" [required]="true" [ngModel]="tFromId()" (ngModelChange)="onTransferFrom($event)" />
        <app-select name="tto" [label]="'expenses.transferTo' | t" [placeholder]="'expenses.field.costCentrePlaceholder' | t" [options]="costCentreOptions()" [required]="true" [ngModel]="tToId()" (ngModelChange)="tToId.set($event)" />
        @if (tFromId()) {
          @if (transferFyOptions().length) {
            <app-select name="tfy" [label]="'expenses.field.fiscalYear' | t" [placeholder]="'expenses.field.fiscalYearPlaceholder' | t" [options]="transferFyOptions()" [required]="true" [ngModel]="tFiscalYearId()" (ngModelChange)="tFiscalYearId.set($event)" />
          } @else {
            <p class="exp__hint exp__hint--warn">{{ 'expenses.field.noFiscalYear' | t }}</p>
          }
        }
        <label class="exp__label" for="exp-tamount">{{ 'expenses.field.amount' | t }}</label>
        <app-currency-input name="tamount" [ngModel]="tAmount()" (ngModelChange)="tAmount.set($event)" [ariaLabel]="'expenses.field.amount' | t" />
        <label class="exp__label" for="exp-tdesc">{{ 'expenses.field.description' | t }}</label>
        <input id="exp-tdesc" class="exp__input" [ngModel]="tDescription()" (ngModelChange)="tDescription.set($event)" name="tdesc" [placeholder]="'expenses.field.descriptionPlaceholder' | t" />
      </form>
      <div dialog-footer class="exp__dialogFoot">
        <app-button variant="ghost" (click)="transferOpen.set(false)">{{ 'action.cancel' | t }}</app-button>
        <app-button [disabled]="!canSubmitTransfer()" [loading]="saving()" (click)="createTransfer($event)">{{ 'expenses.transferConfirm' | t }}</app-button>
      </div>
    </app-dialog>
  `,
  styles: [
    `
      :host { display: block; }
      /* Kopf auf normale Body-Breite zentrieren (wie Anträge); Baum im linken Rand. */
      .exp__head { width: 100%; max-width: var(--layout-max-width); margin: 0 auto var(--space-5); }
      .exp__headRow { display: flex; align-items: start; justify-content: space-between; gap: var(--space-4); flex-wrap: wrap; }
      .exp__title { margin: 0; }
      .exp__subtitle { color: var(--color-text-muted); margin: var(--space-1) 0 0; }
      .exp__headActions { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
      .exp__btnIcon { display: inline-flex; align-items: center; gap: var(--space-2); }
      .exp__kinds { display: inline-flex; gap: var(--space-1); }
      .exp__search, .exp__input {
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
        color: var(--color-text);
        font: inherit;
      }
      .exp__search { min-width: 14rem; height: 2.25rem; }
      .exp__layout {
        display: grid;
        grid-template-columns:
          minmax(12rem, 1fr)
          minmax(0, var(--layout-max-width))
          minmax(0, 1fr);
        gap: var(--space-5);
        align-items: start;
      }
      /* Kostenstellen-Baum im linken Rand (Breakout) + sticky (wie Anträge). */
      .exp__tree {
        justify-self: end;
        width: 100%;
        max-width: 16rem;
        position: sticky;
        top: calc(var(--layout-header-height) + var(--space-4));
        align-self: start;
        /* 3/4 viewport so the tree scrolls internally and clearly floats. */
        max-height: 75vh;
        overflow-y: auto;
      }
      .exp__main { min-width: 0; }
      .exp__empty { text-align: center; color: var(--color-text-muted); padding: var(--space-6) !important; }
      @media (max-width: 60rem) {
        .exp__layout { grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr); }
        .exp__head { max-width: none; }
      }
      @media (max-width: 40rem) {
        .exp__layout { grid-template-columns: 1fr; }
        .exp__tree { position: static; max-height: none; }
      }
      .exp__status { color: var(--color-text-muted); padding: var(--space-4) 0; }
      .exp__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
      .exp__row {
        display: grid;
        grid-template-columns: 7rem 6rem 1fr auto auto;
        align-items: center;
        gap: var(--space-3);
        padding: var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
      }
      .exp__date { color: var(--color-text-muted); font-size: var(--fs-sm); }
      .exp__desc { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
      .exp__descText { font-weight: var(--fw-medium); }
      .exp__meta { font-size: var(--fs-sm); color: var(--color-text-muted); }
      .exp__cc { font-variant-numeric: tabular-nums; }
      .exp__appLink { color: var(--color-primary); text-decoration: none; }
      .exp__appLink:hover { text-decoration: underline; }
      .exp__amount { font-variant-numeric: tabular-nums; font-weight: var(--fw-semibold); white-space: nowrap; }
      .exp__amount--income { color: var(--color-success, #2e7d32); }
      .exp__actions { display: inline-flex; gap: var(--space-1); justify-content: flex-end; }
      .exp__sentinel { height: 1px; }
      .exp__more { display: flex; justify-content: center; margin-top: var(--space-4); }
      .exp__count { text-align: center; color: var(--color-text-muted); font-size: var(--fs-sm); margin-top: var(--space-3); }
      /* --- Tabelle (#25) --- */
      .exp__tableWrap {
        overflow-x: auto;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
      }
      .exp__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .exp__table th,
      .exp__table td {
        padding: var(--space-2) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
        text-align: start;
        vertical-align: middle;
      }
      .exp__table tbody tr:last-child td {
        border-bottom: none;
      }
      .exp__table tbody tr:hover {
        background: var(--color-surface-sunken);
      }
      .exp__table th {
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
        white-space: nowrap;
      }
      .exp__sort {
        background: transparent;
        border: 0;
        padding: 0;
        cursor: pointer;
        font: inherit;
        color: inherit;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
      }
      .exp__sort:hover {
        color: var(--color-primary);
      }
      .exp__num {
        text-align: end;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
      }
      .exp__cellDate {
        color: var(--color-text-muted);
        white-space: nowrap;
      }
      .exp__cellDesc {
        font-weight: var(--fw-medium);
        min-width: 12rem;
      }
      .exp__mono {
        font-variant-numeric: tabular-nums;
        color: var(--color-text-muted);
      }
      .exp__amount {
        font-weight: var(--fw-semibold);
      }
      .exp__amount--income {
        color: var(--color-success, #2e7d32);
      }
      .exp__appLink {
        color: var(--color-primary);
        text-decoration: none;
      }
      .exp__appLink:hover {
        text-decoration: underline;
      }
      .exp__actions {
        display: inline-flex;
        gap: var(--space-1);
        justify-content: flex-end;
      }
      .exp__form { display: flex; flex-direction: column; gap: var(--space-2); }
      .exp__label { font-size: var(--fs-sm); font-weight: var(--fw-medium); margin-top: var(--space-2); }
      .exp__hint { font-size: var(--fs-sm); color: var(--color-text-muted); margin: 0; }
      .exp__hint--warn { color: var(--color-danger); }
      .exp__dialogFoot { display: flex; justify-content: flex-end; gap: var(--space-3); }
      /* Antrags-Typeahead (wie Nutzersuche) */
      .exp__typeahead { position: relative; }
      .exp__suggest {
        list-style: none;
        margin: var(--space-1) 0 0;
        padding: var(--space-1);
        position: absolute;
        z-index: 10;
        left: 0;
        right: 0;
        max-height: 14rem;
        overflow-y: auto;
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-md, 0 4px 16px rgba(0, 0, 0, 0.3));
      }
      .exp__suggestItem {
        display: block;
        width: 100%;
        text-align: left;
        padding: var(--space-2) var(--space-3);
        background: transparent;
        border: 0;
        border-radius: var(--radius-sm);
        color: var(--color-text);
        cursor: pointer;
        font: inherit;
      }
      .exp__suggestItem:hover { background: var(--color-primary-subtle); }
      .exp__picked {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-2);
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-surface);
      }
      .exp__pickedText { font-weight: var(--fw-medium); }
      /* Betrags-Filter (von/bis) */
      @media (max-width: 720px) {
        .exp__layout { grid-template-columns: 1fr; }
        .exp__tree { position: static; max-height: none; }
        .exp__row { grid-template-columns: 1fr auto; }
      }
      /* Mobil (≤768px): Baum hinter einklappbarem Toggle (Standard: zu),
         eine Spalte. Desktop unverändert — Toggle existiert dort nur versteckt. */
      .exp__treeToggle {
        display: none;
      }
      @media (max-width: 768px) {
        .exp__layout { grid-template-columns: 1fr; }
        .exp__tree {
          position: static;
          max-height: none;
          max-width: none;
          justify-self: stretch;
        }
        .exp__treeToggle {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: var(--space-2);
          width: 100%;
          min-height: 2.5rem;
          padding: var(--space-2) var(--space-3);
          font: inherit;
          font-weight: var(--fw-medium);
          color: var(--color-text);
          background: var(--color-surface);
          border: var(--border-width) solid var(--color-border);
          border-radius: var(--radius-md);
          cursor: pointer;
        }
        .exp__treeBody {
          display: none;
          padding-top: var(--space-3);
        }
        .exp__treeBody--open {
          display: block;
        }
      }
      /* Mobil (≤768px): Suche in voller Breite, Tabellenzeilen als Karten (rein CSS). */
      @media (max-width: 768px) {
        .exp__search { flex: 1 1 100%; min-width: 0; }
        .exp__tableWrap {
          overflow-x: visible;
          border: none;
          border-radius: 0;
          background: transparent;
        }
        .exp__table,
        .exp__table tbody { display: block; }
        .exp__table thead { display: none; }
        .exp__table tbody tr {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: var(--space-1) var(--space-3);
          padding: var(--space-3) var(--space-4);
          margin-bottom: var(--space-3);
          background: var(--color-surface);
          border: var(--border-width) solid var(--color-border);
          border-radius: var(--radius-lg);
        }
        .exp__table tbody tr:last-child { margin-bottom: 0; }
        .exp__table th,
        .exp__table td {
          padding: 0;
          border-bottom: none;
        }
        /* Beschreibung als volle erste Zeile der Karte. */
        .exp__cellDesc {
          flex: 1 1 100%;
          min-width: 0;
          order: -1;
        }
        /* Betrag (+ Aktionen) rechtsbündig in der Meta-Zeile. */
        .exp__amount { margin-left: auto; }
        .exp__empty {
          flex: 1 1 100%;
          padding: var(--space-6) !important;
        }
      }
    `,
  ],
})
export class ExpensesComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly apps = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly canManage = computed(() => this.auth.can('budget.book'));

  private readonly PAGE = 20;
  readonly budgetTree = signal<BudgetTreeNode[]>([]);
  readonly items = signal<Expense[]>([]);
  readonly total = signal(0);
  private nextOffset = 0;
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly hasMore = computed(() => this.items().length < this.total());

  readonly kind = signal<'' | ExpenseKind>('');
  readonly q = signal('');
  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Mobil: Baum hinter einklappbarem Toggle (Desktop immer sichtbar). */
  readonly treeOpen = signal(false);
  readonly sortField = signal<'createdAt' | 'amount'>('createdAt');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');
  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  /** Zahl aktiver Filter (für den Indikator am Filter-Button). */
  readonly activeFilterCount = computed(
    () =>
      [
        this.kind(),
        this.amountMin().trim(),
        this.amountMax().trim(),
        this.createdFrom(),
        this.createdTo(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  readonly costCentreOptions = computed<SelectOption[]>(() =>
    flattenBudgetOptions(this.budgetTree()),
  );

  // --- Anlegen-Dialog ---
  readonly createOpen = signal(false);
  readonly newKind = signal<ExpenseKind>('expense');
  readonly newAmount = signal('');
  readonly newDescription = signal('');
  readonly newBudgetId = signal('');
  readonly newFiscalYearId = signal('');
  readonly newApplicationId = signal('');
  readonly appQuery = signal('');
  /** Antrags-Treffer der Typeahead-Suche (max. 8). */
  readonly appCandidates = signal<{ id: string; title: string }[]>([]);
  readonly fiscalYearOptions = signal<SelectOption[]>([]);
  readonly saving = signal(false);

  // --- Bearbeiten/Löschen ---
  readonly editing = signal<Expense | null>(null);
  readonly editAmount = signal('');
  readonly editDescription = signal('');
  readonly confirmDelete = signal<Expense | null>(null);

  // --- Export + Konten ---
  readonly canExport = computed(() => this.auth.can('budget.export'));
  readonly exporting = signal(false);
  readonly accounts = signal<Account[]>([]);
  readonly accountOptions = computed<SelectOption[]>(() =>
    this.accounts().map((a) => ({
      value: a.id,
      label: a.iban ? `${a.name} (${a.iban})` : a.name,
    })),
  );
  readonly newAccountId = signal('');

  // --- Übertrag-Dialog ---
  readonly transferOpen = signal(false);
  readonly tFromId = signal('');
  readonly tToId = signal('');
  readonly tFiscalYearId = signal('');
  readonly tAmount = signal('');
  readonly tDescription = signal('');
  readonly transferFyOptions = signal<SelectOption[]>([]);
  readonly canSubmitTransfer = computed(
    () =>
      !!this.tFromId() &&
      !!this.tToId() &&
      this.tFromId() !== this.tToId() &&
      !!this.tFiscalYearId() &&
      Number(this.tAmount()) > 0 &&
      !!this.tDescription().trim(),
  );

  readonly canSubmitCreate = computed(() => {
    if (!this.newDescription().trim() || !(Number(this.newAmount()) > 0)) return false;
    // Gebunden: Kostenstelle + HHJ werden vom Antrag geerbt.
    if (this.newApplicationId()) return true;
    // Eigenständig: Kostenstelle **und** HHJ explizit erforderlich (sonst 422).
    return !!this.newBudgetId() && !!this.newFiscalYearId();
  });

  constructor() {
    this.api.tree().subscribe({
      next: (tree) => this.budgetTree.set(tree),
      error: () => this.budgetTree.set([]),
    });
    this.api.listAccounts().subscribe({
      next: (accs) => this.accounts.set(accs.filter((a) => a.active)),
      error: () => this.accounts.set([]),
    });
    this.reload();

    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMore();
        },
        { rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  money(amount: string): string {
    return Number(amount).toLocaleString(this.i18n.locale() === 'en' ? 'en-US' : 'de-DE', {
      style: 'currency',
      currency: 'EUR',
    });
  }

  setKind(k: '' | ExpenseKind): void {
    this.kind.set(k);
    this.reload();
  }

  selectBudget(id: string): void {
    this.budgetId.set(id);
    this.reload();
  }

  onSearch(value: string): void {
    this.q.set(value);
    this.debouncedReload();
  }

  onAmountFilter(which: 'min' | 'max', value: string): void {
    (which === 'min' ? this.amountMin : this.amountMax).set(value);
    this.debouncedReload();
  }

  onDateFilter(which: 'from' | 'to', value: string): void {
    (which === 'from' ? this.createdFrom : this.createdTo).set(value);
    this.debouncedReload();
  }

  resetFilters(): void {
    this.kind.set('');
    this.amountMin.set('');
    this.amountMax.set('');
    this.createdFrom.set('');
    this.createdTo.set('');
    this.reload();
  }

  /** Spalten-Sortierung umschalten (gleiche Spalte → Richtung kippen). */
  onSort(field: 'createdAt' | 'amount'): void {
    if (this.sortField() === field) {
      this.sortOrder.update((o) => (o === 'desc' ? 'asc' : 'desc'));
    } else {
      this.sortField.set(field);
      this.sortOrder.set('desc');
    }
    this.reload();
  }

  sortInd(field: 'createdAt' | 'amount'): string {
    if (this.sortField() !== field) return '';
    return this.sortOrder() === 'asc' ? ' ↑' : ' ↓';
  }

  ariaSort(field: 'createdAt' | 'amount'): 'ascending' | 'descending' | 'none' {
    if (this.sortField() !== field) return 'none';
    return this.sortOrder() === 'asc' ? 'ascending' : 'descending';
  }

  private debouncedReload(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => this.reload(), 250);
  }

  private reload(): void {
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loading.set(true);
    this.fetch(true);
  }

  loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  private fetch(initial: boolean): void {
    this.api
      .listExpenses({
        budget: this.budgetId() || undefined,
        kind: this.kind() || undefined,
        q: this.q().trim() || undefined,
        amountMin: this.amountMin().trim() ? Number(this.amountMin()) : undefined,
        amountMax: this.amountMax().trim() ? Number(this.amountMax()) : undefined,
        createdFrom: this.createdFrom() || undefined,
        createdTo: this.createdTo() || undefined,
        sort: this.sortField(),
        order: this.sortOrder(),
        limit: this.PAGE,
        offset: this.nextOffset,
      })
      .subscribe({
        next: (page) => {
          this.total.set(page.total);
          this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
          this.nextOffset = page.offset + page.items.length;
          this.loading.set(false);
          this.loadingMore.set(false);
        },
        error: () => {
          this.loading.set(false);
          this.loadingMore.set(false);
        },
      });
  }

  // --- create ---
  openCreate(): void {
    this.newKind.set('expense');
    this.newAmount.set('');
    this.newDescription.set('');
    this.newBudgetId.set(this.budgetId() || '');
    this.newFiscalYearId.set('');
    this.newApplicationId.set('');
    this.newAccountId.set('');
    this.appQuery.set('');
    this.appCandidates.set([]);
    this.fiscalYearOptions.set([]);
    if (this.budgetId()) this.loadFiscalYears(this.budgetId());
    this.createOpen.set(true);
  }

  // --- Export ---
  onExport(): void {
    if (this.exporting()) return;
    this.exporting.set(true);
    this.api
      .exportExpensesXlsx({
        budget: this.budgetId() || undefined,
        kind: this.kind() || undefined,
        q: this.q().trim() || undefined,
        amountMin: this.amountMin().trim() || undefined,
        amountMax: this.amountMax().trim() || undefined,
        createdFrom: this.createdFrom() || undefined,
        createdTo: this.createdTo() || undefined,
      })
      .subscribe({
        next: (blob) => {
          downloadBlob(blob, 'buchungen.xlsx');
          this.exporting.set(false);
        },
        error: () => this.exporting.set(false),
      });
  }

  // --- Übertrag ---
  openTransfer(): void {
    this.tFromId.set(this.budgetId() || '');
    this.tToId.set('');
    this.tFiscalYearId.set('');
    this.tAmount.set('');
    this.tDescription.set('');
    this.transferFyOptions.set([]);
    if (this.tFromId()) this.loadTransferFy(this.tFromId());
    this.transferOpen.set(true);
  }

  onTransferFrom(id: string): void {
    this.tFromId.set(id);
    this.tFiscalYearId.set('');
    this.transferFyOptions.set([]);
    if (id) this.loadTransferFy(id);
  }

  private loadTransferFy(budgetId: string): void {
    const top = this.findTop(this.budgetTree(), budgetId);
    if (!top) return;
    this.api.listFiscalYears(top.id).subscribe({
      next: (fys: FiscalYear[]) => {
        this.transferFyOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        const active = fys.filter((f) => f.active);
        if (active.length === 1) this.tFiscalYearId.set(active[0].id);
      },
      error: () => this.transferFyOptions.set([]),
    });
  }

  createTransfer(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitTransfer() || this.saving()) return;
    this.saving.set(true);
    this.api
      .createTransfer({
        fromBudgetId: this.tFromId(),
        toBudgetId: this.tToId(),
        fiscalYearId: this.tFiscalYearId(),
        amount: this.tAmount(),
        description: this.tDescription().trim(),
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.transferOpen.set(false);
          this.toast.success(this.i18n.translate('expenses.transferToast'));
          this.reload();
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  setNewKindIncome(): void {
    this.newKind.set('income');
    // Einnahmen sind nicht an Anträge bindbar.
    this.clearApp();
  }

  /** Antrags-Typeahead (wie die Nutzersuche): Treffer als Vorschlagsliste. */
  onAppSearch(value: string): void {
    this.appQuery.set(value);
    const q = value.trim();
    if (!q) {
      this.appCandidates.set([]);
      return;
    }
    this.apps.listApplications({ q, limit: 8 }).subscribe({
      next: (page) =>
        this.appCandidates.set(
          page.items.map((a) => ({ id: a.id, title: a.title || a.id })),
        ),
      error: () => this.appCandidates.set([]),
    });
  }

  pickApp(a: { id: string; title: string }): void {
    this.newApplicationId.set(a.id);
    this.appQuery.set(a.title);
    this.appCandidates.set([]);
  }

  clearApp(): void {
    this.newApplicationId.set('');
    this.appQuery.set('');
    this.appCandidates.set([]);
  }

  onPickBudget(id: string): void {
    this.newBudgetId.set(id);
    this.newFiscalYearId.set('');
    this.fiscalYearOptions.set([]);
    if (id) this.loadFiscalYears(id);
  }

  /** Top-Level-Knoten finden, dessen Unterbaum ``budgetId`` enthält, und HHJ laden. */
  private loadFiscalYears(budgetId: string): void {
    const top = this.findTop(this.budgetTree(), budgetId);
    if (!top) return;
    this.api.listFiscalYears(top.id).subscribe({
      next: (fys: FiscalYear[]) => {
        // Alle HHJ anbieten (Backend lässt explizite, auch inaktive HHJ zu); ein
        // einzelnes aktives HHJ wird vorausgewählt.
        this.fiscalYearOptions.set(fys.map((f) => ({ value: f.id, label: f.display })));
        const active = fys.filter((f) => f.active);
        if (active.length === 1) this.newFiscalYearId.set(active[0].id);
      },
      error: () => this.fiscalYearOptions.set([]),
    });
  }

  private findTop(nodes: BudgetTreeNode[], targetId: string): BudgetTreeNode | null {
    const contains = (n: BudgetTreeNode): boolean =>
      n.id === targetId || n.children.some(contains);
    return nodes.find((root) => contains(root)) ?? null;
  }

  create(event: Event): void {
    event.preventDefault();
    if (!this.canSubmitCreate() || this.saving()) return;
    const linked = !!this.newApplicationId();
    this.saving.set(true);
    this.api
      .bookExpense({
        amount: this.newAmount(),
        description: this.newDescription().trim(),
        kind: this.newKind(),
        applicationId: linked ? this.newApplicationId() : null,
        budgetId: linked ? null : this.newBudgetId() || null,
        fiscalYearId: linked ? null : this.newFiscalYearId() || null,
        accountId: this.newAccountId() || null,
      })
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.createOpen.set(false);
          this.toast.success(this.i18n.translate('expenses.toast.created'));
          this.reload();
        },
        error: (err) => {
          this.saving.set(false);
          this.toast.error(this.problemDetail(err));
        },
      });
  }

  /** Lesbaren Fehlertext aus dem problem+json (``detail``) ziehen, sonst generisch. */
  private problemDetail(err: unknown): string {
    const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
    return detail || this.i18n.translate('expenses.toast.failed');
  }

  // --- edit ---
  openEdit(e: Expense): void {
    this.editing.set(e);
    this.editAmount.set(e.amount);
    this.editDescription.set(e.description);
  }

  saveEdit(event: Event): void {
    event.preventDefault();
    const e = this.editing();
    if (!e || this.saving()) return;
    this.saving.set(true);
    this.api
      .updateExpense(e.id, {
        amount: this.editAmount(),
        description: this.editDescription().trim(),
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.editing.set(null);
          this.items.update((list) => list.map((x) => (x.id === updated.id ? updated : x)));
          this.toast.success(this.i18n.translate('expenses.toast.saved'));
        },
        error: () => {
          this.saving.set(false);
          this.toast.error(this.i18n.translate('expenses.toast.failed'));
        },
      });
  }

  // --- delete ---
  askDelete(e: Expense): void {
    this.confirmDelete.set(e);
  }

  doDelete(): void {
    const e = this.confirmDelete();
    if (!e || this.saving()) return;
    this.saving.set(true);
    this.api.deleteExpense(e.id).subscribe({
      next: () => {
        this.saving.set(false);
        this.confirmDelete.set(null);
        this.items.update((list) => list.filter((x) => x.id !== e.id));
        this.total.update((t) => Math.max(0, t - 1));
        this.toast.success(this.i18n.translate('expenses.toast.deleted'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('expenses.toast.failed'));
      },
    });
  }
}
