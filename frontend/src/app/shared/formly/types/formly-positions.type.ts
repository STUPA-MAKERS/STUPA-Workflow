import { ChangeDetectionStrategy, Component, type OnInit, inject } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

/** A comparison offer within a cost position. */
interface Offer {
  label: string;
  value: number | null;
  preferred: boolean;
}

/** A cost position with several comparison offers. */
interface Position {
  label: string;
  offers: Offer[];
  /** Opt-out of comparison offers (needs a reason; only one offer then). */
  noOffers?: boolean;
  noOffersReason?: string;
}

/**
 * Formly field type `positions` (cost positions). The model value is an array of
 * positions; each carries ≥ `minOffers` comparison offers, exactly one of which is
 * preferred — its value is the position value. The total (Σ positions) flows into
 * `amount` server-side. Validity (min positions/offers, one preferred, values > 0)
 * is mirrored onto the FormControl.
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
              [class.pos__invalid]="titleInvalid(p)"
              [attr.aria-invalid]="titleInvalid(p) ? 'true' : null"
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
                <th class="pos__actcol"></th>
              </tr>
            </thead>
            <tbody>
              @for (o of p.offers; track $index; let oi = $index) {
                <tr>
                  <td>
                    <input [value]="o.label" (input)="setOfferLabel(pi, oi, $any($event.target).value)"
                      [class.pos__invalid]="offerLabelInvalid(o)" [attr.aria-invalid]="offerLabelInvalid(o) ? 'true' : null"
                      [attr.placeholder]="t('apply.positions.offer')" [attr.aria-label]="t('apply.positions.offer')" />
                  </td>
                  <td class="pos__num">
                    <input type="text" inputmode="decimal" class="pos__money" [value]="offerValueText(pi, oi)"
                      [class.pos__invalid]="offerValueInvalid(o)" [attr.aria-invalid]="offerValueInvalid(o) ? 'true' : null"
                      (focus)="beginEditValue(pi, oi)" (blur)="endEditValue()"
                      (input)="setOfferValue(pi, oi, $any($event.target).value)"
                      [attr.aria-label]="t('apply.positions.value')" />
                  </td>
                  <td class="pos__pref">
                    <input type="radio" [name]="'pref-' + pi" [checked]="o.preferred"
                      (change)="setPreferred(pi, oi)" [attr.aria-label]="t('apply.positions.preferred')" />
                  </td>
                  <td class="pos__actcol">
                    <button type="button" class="pos__icon" (click)="removeOffer(pi, oi)"
                      [disabled]="p.offers.length <= requiredOffers(p)"
                      [attr.title]="p.offers.length <= requiredOffers(p) ? t('apply.positions.minOffersHint') : null"
                      [attr.aria-label]="t('apply.positions.remove')">✕</button>
                  </td>
                </tr>
              }
            </tbody>
          </table>
          <button type="button" class="pos__add pos__add--sm" (click)="addOffer(pi)">+ {{ t('apply.positions.addOffer') }}</button>
          @if (allowNoOffers) {
            <label class="pos__noOffers">
              <input type="checkbox" [checked]="p.noOffers === true"
                (change)="setNoOffers(pi, $any($event.target).checked)" />
              <span>{{ t('apply.positions.noOffers') }}</span>
            </label>
            @if (p.noOffers) {
              <p class="pos__hint">{{ t('apply.positions.noOffersHint') }}</p>
              <textarea class="pos__reason" rows="2"
                [value]="p.noOffersReason ?? ''"
                [class.pos__invalid]="reasonInvalid(p)"
                [attr.aria-invalid]="reasonInvalid(p) ? 'true' : null"
                (input)="setNoOffersReason(pi, $any($event.target).value)"
                [attr.placeholder]="t('apply.positions.noOffersReason')"
                [attr.aria-label]="t('apply.positions.noOffersReason')"></textarea>
            }
          }
          @if (cardError(p); as msg) {
            <p class="pos__field-error" role="alert">{{ msg }}</p>
          }
        </div>
      }

      <button type="button" class="pos__add" (click)="addPosition()">+ {{ t('apply.positions.add') }}</button>
      @if (showError && positions.length < minPositions) {
        <p class="pos__field-error" role="alert">{{ t('apply.positions.errMinPositions') }}</p>
      }

      <p class="pos__total"><strong>{{ t('apply.positions.total') }}: {{ fmt(total()) }}</strong></p>
    </fieldset>
  `,
  styles: [
    `
      /* Standalone, set-off block — clearly separated from the rest of the form. */
      .pos {
        display: flex; flex-direction: column; gap: var(--space-4);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface-sunken, var(--color-surface));
        padding: var(--space-4);
        margin: 0;
      }
      .pos__legend { float: left; width: 100%; font-size: var(--fs-md); font-weight: var(--fw-semibold); padding: 0; margin-bottom: var(--space-1); }
      .pos__req { color: var(--color-danger); margin-left: var(--space-1); }
      .pos__hint { font-size: var(--fs-sm); color: var(--color-text-muted); margin: 0; }
      .pos__card {
        display: flex; flex-direction: column; gap: var(--space-3);
        padding: var(--space-4); border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md); background: var(--color-bg-elevated, var(--color-surface));
      }
      .pos__card-head { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
      .pos__title { flex: 1; min-width: 12rem; font-weight: var(--fw-medium); }
      .pos__value { font-size: var(--fs-sm); color: var(--color-text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
      /* table-layout: fixed — otherwise the intrinsic min-width of the inputs
         (~20ch default) forces a table wider than the mobile viewport. */
      .pos__offers { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); table-layout: fixed; }
      .pos__offers th { text-align: start; font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: 0.04em; color: var(--color-text-muted); font-weight: var(--fw-semibold); padding: 0 var(--space-2) var(--space-2); }
      .pos__offers td { padding: var(--space-1) var(--space-2); vertical-align: middle; }
      .pos__num { text-align: end; width: 9rem; }
      .pos__num input { text-align: end; }
      .pos__pref { text-align: center; width: 5rem; }
      .pos__actcol { width: 2.5rem; }
      /* Inputs consistent with the rest of the app (height/padding/radius). */
      .pos input {
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-bg); color: inherit; width: 100%;
        min-width: 0; /* inputs may shrink below their intrinsic width */
        min-height: 2.25rem; font: inherit;
      }
      .pos input:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
      /* No browser spin buttons on number inputs (inconsistent with the rest). */
      .pos input[type='number'] { appearance: textfield; -moz-appearance: textfield; }
      .pos input[type='number']::-webkit-outer-spin-button,
      .pos input[type='number']::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
      .pos__pref input[type='radio'] { width: 1.15rem; height: 1.15rem; min-height: 0; accent-color: var(--color-primary); cursor: pointer; }
      .pos__noOffers { display: flex; align-items: center; gap: var(--space-2); font-size: var(--fs-sm); cursor: pointer; }
      .pos__noOffers input[type='checkbox'] { width: 1.15rem; height: 1.15rem; min-height: 0; padding: 0; accent-color: var(--color-primary); cursor: pointer; flex: 0 0 auto; }
      .pos textarea.pos__reason {
        padding: var(--space-2) var(--space-3);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
        background: var(--color-bg); color: inherit; width: 100%;
        font: inherit; resize: vertical;
      }
      .pos textarea.pos__reason:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
      .pos textarea.pos__invalid { border-color: var(--color-danger); }
      .pos__icon { background: transparent; border: 0; cursor: pointer; color: var(--color-text-muted); font-size: var(--fs-md); line-height: 1; padding: var(--space-1); }
      .pos__icon:hover:not(:disabled) { color: var(--color-danger); }
      .pos__icon:disabled { opacity: 0.35; cursor: not-allowed; }
      .pos__money { font-variant-numeric: tabular-nums; }
      .pos input.pos__invalid { border-color: var(--color-danger); }
      .pos input.pos__invalid:focus-visible { outline-color: var(--color-danger); }
      .pos__field-error { font-size: var(--fs-xs); color: var(--color-danger); margin: 0; }
      .pos__add { align-self: flex-start; background: transparent; border: var(--border-width) dashed var(--color-border); border-radius: var(--radius-md); padding: var(--space-2) var(--space-3); cursor: pointer; color: var(--color-primary); font: inherit; font-weight: var(--fw-medium); }
      .pos__add:hover { background: var(--color-surface); }
      .pos__add--sm { border-style: none; padding: var(--space-1) 0; }
      .pos__total { margin: 0; font-size: var(--fs-md); font-variant-numeric: tabular-nums; }
      .pos__error { font-size: var(--fs-sm); color: var(--color-danger); margin: 0; }
      /* Mobile (768px convention): narrower columns + tighter padding, the header
         row is dropped (placeholders/aria-labels carry the meaning) — this keeps the
         card within the viewport instead of overflowing horizontally. */
      @media (max-width: 768px) {
        .pos { padding: var(--space-3); }
        .pos__card { padding: var(--space-3); }
        .pos__offers thead { display: none; }
        .pos__offers th, .pos__offers td { padding-inline: var(--space-1); }
        .pos__num { width: 5.5rem; }
        .pos__pref { width: 2.5rem; }
        .pos__actcol { width: 2rem; }
        .pos__title { min-width: 0; }
      }
    `,
  ],
})
export class FormlyPositionsType extends FieldType<FieldTypeConfig> implements OnInit {
  private readonly i18n = inject(I18nService);

  ngOnInit(): void {
    // Mirror validity immediately: an empty (min-)positions field is invalid even if
    // the applicant never touches it (otherwise it passes the wizard's required check).
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
  /** Opt-out of comparison offers offered at all (form config; default yes). */
  get allowNoOffers(): boolean {
    return this.props['allowNoOffers'] !== false;
  }
  /** Offers required for one position — 1 when it opted out, else `minOffers`. */
  protected requiredOffers(p: Position): number {
    return this.allowNoOffers && p.noOffers ? 1 : this.minOffers;
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

  // --- Inline per-field validation: mark the affected field red, message in place. ---
  protected titleInvalid(p: Position): boolean {
    return this.showError && !p.label.trim();
  }
  protected offerLabelInvalid(o: Offer): boolean {
    return this.showError && !o.label.trim();
  }
  protected offerValueInvalid(o: Offer): boolean {
    return this.showError && (o.value === null || o.value <= 0);
  }
  protected reasonInvalid(p: Position): boolean {
    return this.showError && p.noOffers === true && !(p.noOffersReason ?? '').trim();
  }

  /** Concrete, terse error message per position card (or '' when valid). */
  protected cardError(p: Position): string {
    if (!this.showError) return '';
    if (p.offers.length < this.requiredOffers(p)) return this.t('apply.positions.errMinOffers');
    if (p.offers.filter((o) => o.preferred).length !== 1) return this.t('apply.positions.errPreferred');
    if (!p.label.trim()) return this.t('apply.positions.errLabel');
    if (p.offers.some((o) => !o.label.trim() || o.value === null || o.value <= 0)) {
      return this.t('apply.positions.errOffers');
    }
    if (this.reasonInvalid(p)) return this.t('apply.positions.errNoOffersReason');
    return '';
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

  /** Mirror validity onto the FormControl (min positions/offers, one preferred, values > 0). */
  private revalidate(positions: Position[]): void {
    let ok = positions.length >= this.minPositions;
    for (const p of positions) {
      if (!p.label.trim()) ok = false;
      if (p.offers.length < this.requiredOffers(p)) ok = false;
      if (p.offers.filter((o) => o.preferred).length !== 1) ok = false;
      for (const o of p.offers) {
        if (!o.label.trim() || o.value === null || o.value <= 0) ok = false;
      }
      if (p.noOffers === true && !(p.noOffersReason ?? '').trim()) ok = false;
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
    const value = this.parseNum(raw);
    this.commit(
      this.positions.map((p, i) =>
        i === pi
          ? { ...p, offers: p.offers.map((o, k) => (k === oi ? { ...o, value } : o)) }
          : p,
      ),
    );
  }

  /** Which value cell is currently being edited (then raw value instead of formatted). */
  protected editing: { pi: number; oi: number } | null = null;

  protected beginEditValue(pi: number, oi: number): void {
    this.editing = { pi, oi };
  }
  protected endEditValue(): void {
    this.editing = null;
  }

  /** Display text of the value input: raw while typing, otherwise formatted to 2
   *  decimals localized (1.234,56) — without a currency symbol (the column says €). */
  protected offerValueText(pi: number, oi: number): string {
    const v = this.positions[pi]?.offers[oi]?.value ?? null;
    if (v === null) return '';
    if (this.editing && this.editing.pi === pi && this.editing.oi === oi) {
      return String(v);
    }
    return new Intl.NumberFormat(this.i18n.locale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(v);
  }

  /** Robustly parse a localized/free money input to `number` (accepts "1.234,56"
   *  and "1234.56"); empty/invalid → `null`. */
  private parseNum(raw: string): number | null {
    const s = raw.trim();
    if (!s) return null;
    let cleaned = s.replace(/[^\d.,-]/g, '');
    if (cleaned.includes(',') && cleaned.includes('.')) {
      // The last separator is the decimal separator.
      cleaned =
        cleaned.lastIndexOf(',') > cleaned.lastIndexOf('.')
          ? cleaned.replace(/\./g, '').replace(',', '.')
          : cleaned.replace(/,/g, '');
    } else if (cleaned.includes(',')) {
      cleaned = cleaned.replace(',', '.');
    }
    const n = Number(cleaned);
    return Number.isFinite(n) ? n : null;
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

  /** Toggle the comparison-offer opt-out. On: drop untouched blank offers (one
   *  offer input remains, marked preferred). Off: pad back up to `minOffers`. */
  setNoOffers(pi: number, checked: boolean): void {
    this.commit(
      this.positions.map((p, i) => {
        if (i !== pi) return p;
        if (checked) {
          let offers = p.offers.filter((o) => o.label.trim() || o.value !== null);
          if (!offers.length) offers = [this.blankOffer(true)];
          if (!offers.some((o) => o.preferred)) {
            offers = offers.map((o, k) => ({ ...o, preferred: k === 0 }));
          }
          return { ...p, noOffers: true, offers };
        }
        const pad = Array.from({ length: Math.max(0, this.minOffers - p.offers.length) }, () =>
          this.blankOffer(),
        );
        return { ...p, noOffers: false, noOffersReason: '', offers: [...p.offers, ...pad] };
      }),
    );
  }

  setNoOffersReason(pi: number, reason: string): void {
    this.commit(
      this.positions.map((p, i) => (i === pi ? { ...p, noOffersReason: reason } : p)),
    );
  }
}
