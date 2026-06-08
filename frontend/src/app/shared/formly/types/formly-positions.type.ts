import { ChangeDetectionStrategy, Component, type OnInit, inject } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

/** Ein Vergleichsangebot innerhalb einer Kostenposition. */
interface Offer {
  label: string;
  value: number | null;
  preferred: boolean;
}

/** Eine Kostenposition mit mehreren Vergleichsangeboten. */
interface Position {
  label: string;
  offers: Offer[];
}

/**
 * Formly-Feldtyp `positions` (Kostenpositionen). Der Modellwert ist ein Array von
 * Positionen; jede trägt ≥ `minOffers` Vergleichsangebote, von denen genau eines
 * bevorzugt ist — dessen Wert ist der Positionswert. Der Gesamtbetrag (Σ Positionen)
 * fließt serverseitig in `amount`. Validität (min Positionen/Angebote, ein
 * bevorzugtes, Werte > 0) wird auf das FormControl gespiegelt.
 */
@Component({
  selector: 'app-formly-positions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <fieldset class="pos">
      <legend class="pos__legend">
        {{ props.label }}
        @if (props.required) { <span class="pos__req" aria-hidden="true">*</span> }
      </legend>
      @if (props.description) { <p class="pos__hint">{{ props.description }}</p> }

      @for (p of positions; track $index; let pi = $index) {
        <div class="pos__card">
          <div class="pos__card-head">
            <input
              class="pos__title"
              [value]="p.label"
              (input)="setPositionLabel(pi, $any($event.target).value)"
              [attr.placeholder]="t('apply.positions.label')"
              [attr.aria-label]="t('apply.positions.label')"
            />
            <span class="pos__value">{{ t('apply.positions.positionValue') }}: {{ fmt(positionValue(p)) }}</span>
            <button type="button" class="pos__icon" (click)="removePosition(pi)" [attr.aria-label]="t('apply.positions.remove')">✕</button>
          </div>

          <table class="pos__offers">
            <thead>
              <tr>
                <th>{{ t('apply.positions.offer') }}</th>
                <th class="pos__num">{{ t('apply.positions.value') }}</th>
                <th class="pos__pref">{{ t('apply.positions.preferred') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              @for (o of p.offers; track $index; let oi = $index) {
                <tr>
                  <td>
                    <input [value]="o.label" (input)="setOfferLabel(pi, oi, $any($event.target).value)"
                      [attr.placeholder]="t('apply.positions.offer')" [attr.aria-label]="t('apply.positions.offer')" />
                  </td>
                  <td class="pos__num">
                    <input type="number" min="0" step="0.01" [value]="o.value ?? ''"
                      (input)="setOfferValue(pi, oi, $any($event.target).value)"
                      [attr.aria-label]="t('apply.positions.value')" />
                  </td>
                  <td class="pos__pref">
                    <input type="radio" [name]="'pref-' + pi" [checked]="o.preferred"
                      (change)="setPreferred(pi, oi)" [attr.aria-label]="t('apply.positions.preferred')" />
                  </td>
                  <td>
                    <button type="button" class="pos__icon" (click)="removeOffer(pi, oi)" [attr.aria-label]="t('apply.positions.remove')">✕</button>
                  </td>
                </tr>
              }
            </tbody>
          </table>
          <button type="button" class="pos__add pos__add--sm" (click)="addOffer(pi)">+ {{ t('apply.positions.addOffer') }}</button>
        </div>
      }

      <button type="button" class="pos__add" (click)="addPosition()">+ {{ t('apply.positions.add') }}</button>

      <p class="pos__total"><strong>{{ t('apply.positions.total') }}: {{ fmt(total()) }}</strong></p>

      @if (showError && errorText) {
        <p class="pos__error" role="alert">{{ errorText }}</p>
      }
    </fieldset>
  `,
  styles: [
    `
      .pos { display: flex; flex-direction: column; gap: var(--space-3); border: none; padding: 0; margin: 0; }
      .pos__legend { font-size: var(--fs-sm); font-weight: var(--fw-medium); padding: 0; }
      .pos__req { color: var(--color-danger); }
      .pos__hint { font-size: var(--fs-xs); color: var(--color-text-muted); margin: 0; }
      .pos__card {
        display: flex; flex-direction: column; gap: var(--space-2);
        padding: var(--space-3); border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md); background: var(--color-surface);
      }
      .pos__card-head { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
      .pos__title { flex: 1; min-width: 10rem; font-weight: var(--fw-medium); }
      .pos__value { font-size: var(--fs-sm); color: var(--color-text-muted); font-variant-numeric: tabular-nums; }
      .pos__offers { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
      .pos__offers th { text-align: start; font-size: var(--fs-xs); color: var(--color-text-muted); font-weight: var(--fw-semibold); padding: var(--space-1) var(--space-2); }
      .pos__offers td { padding: var(--space-1) var(--space-2); }
      .pos__num { text-align: end; }
      .pos__num input { text-align: end; }
      .pos__pref { text-align: center; }
      .pos input { padding: var(--space-1) var(--space-2); border: var(--border-width) solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-bg); color: inherit; width: 100%; }
      .pos__pref input, .pos input[type='radio'] { width: auto; }
      .pos__icon { background: transparent; border: 0; cursor: pointer; color: var(--color-text-muted); font-size: var(--fs-md); }
      .pos__icon:hover { color: var(--color-danger); }
      .pos__add { align-self: flex-start; background: transparent; border: var(--border-width) dashed var(--color-border); border-radius: var(--radius-md); padding: var(--space-2) var(--space-3); cursor: pointer; color: var(--color-primary); font: inherit; }
      .pos__add--sm { border-style: none; padding: var(--space-1) 0; }
      .pos__total { margin: 0; font-variant-numeric: tabular-nums; }
      .pos__error { font-size: var(--fs-xs); color: var(--color-danger); margin: 0; }
    `,
  ],
})
export class FormlyPositionsType extends FieldType<FieldTypeConfig> implements OnInit {
  private readonly i18n = inject(I18nService);

  ngOnInit(): void {
    // Gültigkeit sofort spiegeln: ein leeres (min-)Positionsfeld ist ungültig, auch
    // wenn der Antragsteller es nie berührt (sonst durchläuft es die Wizard-Pflicht).
    queueMicrotask(() => this.revalidate(this.positions));
  }

  protected t(key: string): string {
    return this.i18n.translate(key as TranslationKey);
  }

  get minOffers(): number {
    return Number(this.props['minOffers']) || 3;
  }
  get minPositions(): number {
    return Number(this.props['minPositions']) || 1;
  }

  get positions(): Position[] {
    const v = this.formControl.value;
    return Array.isArray(v) ? (v as Position[]) : [];
  }

  override get showError(): boolean {
    return this.formControl.invalid && (this.formControl.touched || this.formControl.dirty);
  }

  get errorText(): string {
    return this.t('apply.positions.invalid');
  }

  protected fmt(value: number): string {
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(value);
  }

  protected positionValue(p: Position): number {
    const pref = p.offers.find((o) => o.preferred);
    return pref?.value ?? 0;
  }

  protected total(): number {
    return this.positions.reduce((sum, p) => sum + this.positionValue(p), 0);
  }

  private blankOffer(preferred = false): Offer {
    return { label: '', value: null, preferred };
  }

  private commit(next: Position[]): void {
    this.formControl.setValue(next);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
    this.revalidate(next);
  }

  /** Validität auf das FormControl spiegeln (min Positionen/Angebote, ein bevorzugtes, Werte > 0). */
  private revalidate(positions: Position[]): void {
    let ok = positions.length >= this.minPositions;
    for (const p of positions) {
      if (!p.label.trim()) ok = false;
      if (p.offers.length < this.minOffers) ok = false;
      if (p.offers.filter((o) => o.preferred).length !== 1) ok = false;
      for (const o of p.offers) {
        if (!o.label.trim() || o.value === null || o.value <= 0) ok = false;
      }
    }
    if (this.props.required && positions.length === 0) ok = false;
    this.formControl.setErrors(ok ? null : { positions: true });
  }

  addPosition(): void {
    const offers = Array.from({ length: this.minOffers }, (_, i) => this.blankOffer(i === 0));
    this.commit([...this.positions, { label: '', offers }]);
  }

  removePosition(pi: number): void {
    this.commit(this.positions.filter((_, i) => i !== pi));
  }

  addOffer(pi: number): void {
    this.commit(
      this.positions.map((p, i) =>
        i === pi ? { ...p, offers: [...p.offers, this.blankOffer(p.offers.length === 0)] } : p,
      ),
    );
  }

  removeOffer(pi: number, oi: number): void {
    this.commit(
      this.positions.map((p, i) =>
        i === pi ? { ...p, offers: p.offers.filter((_, k) => k !== oi) } : p,
      ),
    );
  }

  setPositionLabel(pi: number, label: string): void {
    this.commit(this.positions.map((p, i) => (i === pi ? { ...p, label } : p)));
  }

  setOfferLabel(pi: number, oi: number, label: string): void {
    this.commit(
      this.positions.map((p, i) =>
        i === pi
          ? { ...p, offers: p.offers.map((o, k) => (k === oi ? { ...o, label } : o)) }
          : p,
      ),
    );
  }

  setOfferValue(pi: number, oi: number, raw: string): void {
    const value = raw === '' ? null : Number(raw);
    this.commit(
      this.positions.map((p, i) =>
        i === pi
          ? { ...p, offers: p.offers.map((o, k) => (k === oi ? { ...o, value } : o)) }
          : p,
      ),
    );
  }

  setPreferred(pi: number, oi: number): void {
    this.commit(
      this.positions.map((p, i) =>
        i === pi
          ? { ...p, offers: p.offers.map((o, k) => ({ ...o, preferred: k === oi })) }
          : p,
      ),
    );
  }
}
