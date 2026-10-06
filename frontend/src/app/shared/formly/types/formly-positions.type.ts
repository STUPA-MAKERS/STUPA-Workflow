import { ChangeDetectionStrategy, Component, type OnInit, inject, signal } from '@angular/core';
import { FieldType, type FieldTypeConfig } from '@ngx-formly/core';
import { ButtonComponent, IconComponent, SwitchComponent } from '@stupa-makers/ui-kit';
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
  /** Opt-out of comparison offers. It needs a reason and allows only one offer. */
  noOffers?: boolean;
  noOffersReason?: string;
}

let nextUid = 0;

/**
 * Formly field type `positions` (cost positions). The model value is an array of
 * positions. Each position carries at least `minOffers` comparison offers. Exactly one
 * offer is preferred, and its value is the value of the position. The server writes the
 * total of all positions into `amount`. The component mirrors validity onto the
 * FormControl: minimum positions and offers, one preferred offer, and values above 0.
 *
 * Look (board Anträge-Bearbeiten): one card per position. A complete position starts
 * collapsed (name, "n Angebote · bevorzugt: …", amount); a new or an incomplete one
 * starts open. Open, it shows the name, the switch "keine Vergleichsangebote möglich",
 * the offers with the radio for the preferred one, and "Angebot hinzufügen". A position
 * without comparison offers keeps exactly one offer (supplier and amount) and needs a
 * reason (D12); without the offer the server answers 422.
 *
 * `props.serverErrors` (index → text) holds the 422 messages of the last save; the
 * position shows its message and opens. The next change clears them.
 */
@Component({
  selector: 'app-formly-positions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent, SwitchComponent],
  templateUrl: './formly-positions.type.html',
  styleUrl: './formly-positions.type.scss',
})
export class FormlyPositionsType extends FieldType<FieldTypeConfig> implements OnInit {
  private readonly i18n = inject(I18nService);
  private readonly uid = `pos-${nextUid++}`;

  /** The open positions, by index. */
  private readonly open = signal<ReadonlySet<number>>(new Set());

  ngOnInit(): void {
    // A complete position starts collapsed; a new or an incomplete one starts open.
    this.open.set(
      new Set(this.positions.flatMap((p, i) => (this.positionComplete(p) ? [] : [i]))),
    );
    // Mirror validity at once. A field below `minPositions` is invalid even when the
    // applicant never touches it. Otherwise it passes the required check of the wizard.
    queueMicrotask(() => this.revalidate(this.positions));
  }

  /** The position is open: always while the server named an error for it. */
  protected isOpen(pi: number): boolean {
    return this.open().has(pi) || this.serverError(pi) !== '';
  }

  protected toggleOpen(pi: number): void {
    this.open.update((cur) => {
      const next = new Set(cur);
      if (this.isOpen(pi)) next.delete(pi);
      else next.add(pi);
      return next;
    });
    // An open position with a server error closes only after its error is gone. The
    // errors of the other positions stay.
    if (this.serverError(pi)) this.dropServerError(pi);
  }

  protected cardId(pi: number): string {
    return `${this.uid}-${pi}`;
  }

  /** The radios of one position form one group; the name is unique on the page. */
  protected radioName(pi: number): string {
    return `${this.uid}-pref-${pi}`;
  }

  /** The second line of a collapsed position. */
  protected summary(p: Position): string {
    const count = this.i18n.translate(
      p.offers.length === 1 ? 'forms.positions.offerOne' : 'forms.positions.offerOther',
      { count: p.offers.length },
    );
    if (p.noOffers) return `${count} · ${this.t('forms.positions.noOffersShort')}`;
    const preferred = p.offers.find((o) => o.preferred)?.label.trim();
    return preferred
      ? `${count} · ${this.i18n.translate('forms.positions.preferredBy', { name: preferred })}`
      : count;
  }

  /** The 422 message of the last save for one position (index), or ''. Index -1 is the
   *  message for the field as a whole. */
  protected serverError(pi: number): string {
    const map = this.props['serverErrors'] as Record<number, string> | undefined;
    return map?.[pi] ?? '';
  }

  private clearServerErrors(): void {
    if (this.props['serverErrors']) delete this.props['serverErrors'];
  }

  /** Remove the 422 message of one position. When no message is left, the control is
   *  valid or invalid by its own checks again. */
  private dropServerError(pi: number): void {
    const map = { ...(this.props['serverErrors'] as Record<number, string>) };
    delete map[pi];
    if (Object.keys(map).length) {
      this.props['serverErrors'] = map;
      return;
    }
    this.clearServerErrors();
    this.revalidate(this.positions);
  }

  /** The accessible name of the radio of an offer: "Bevorzugt: <supplier>". */
  protected radioLabel(o: Offer, oi: number): string {
    const name =
      o.label.trim() || this.i18n.translate('forms.positions.offerN', { n: oi + 1 });
    return this.i18n.translate('forms.positions.preferOfferNamed', { name });
  }

  private positionComplete(p: Position): boolean {
    return (
      !!p.label.trim() &&
      p.offers.length >= this.requiredOffers(p) &&
      p.offers.filter((o) => o.preferred).length === 1 &&
      p.offers.every((o) => !!o.label.trim() && o.value !== null && o.value > 0) &&
      !(p.noOffers === true && !(p.noOffersReason ?? '').trim())
    );
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
  /** Whether the form config offers the comparison-offer opt-out at all. Default yes. */
  get allowNoOffers(): boolean {
    return this.props['allowNoOffers'] !== false;
  }
  /** Offers required for one position: 1 when the position opted out, else `minOffers`. */
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

  // Inline per-field validation marks the affected field red and shows the message in place.
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

  /** Terse error message for one position card, or '' when the position is valid. The
   *  message of the server comes first. */
  protected cardError(p: Position, pi = -2): string {
    const server = this.serverError(pi);
    if (server) return server;
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
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
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
    this.clearServerErrors();
    this.formControl.setValue(next);
    this.formControl.markAsDirty();
    this.formControl.markAsTouched();
    this.revalidate(next);
  }

  /** Mirror validity onto the FormControl (min positions/offers, one preferred, values > 0). */
  private revalidate(positions: Position[]): void {
    let ok = positions.length >= this.minPositions;
    for (const p of positions) {
      if (!this.positionComplete(p)) ok = false;
    }
    if (this.props.required && positions.length === 0) ok = false;
    this.formControl.setErrors(ok ? null : { positions: true });
  }

  addPosition(): void {
    const offers = Array.from({ length: this.minOffers }, (_, i) => this.blankOffer(i === 0));
    const index = this.positions.length;
    this.commit([...this.positions, { label: '', offers }]);
    this.open.update((cur) => new Set([...cur, index]));
  }

  removePosition(pi: number): void {
    this.commit(this.positions.filter((_, i) => i !== pi));
    // The positions after the removed one move up by one.
    this.open.update(
      (cur) => new Set([...cur].filter((i) => i !== pi).map((i) => (i > pi ? i - 1 : i))),
    );
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

  /** The value cell under edit. It shows the raw value instead of the formatted value. */
  protected editing: { pi: number; oi: number } | null = null;

  protected beginEditValue(pi: number, oi: number): void {
    this.editing = { pi, oi };
  }
  protected endEditValue(): void {
    this.editing = null;
  }

  /** Display text of the value input. It shows the raw text while the user types.
   *  Otherwise it shows a localized number with 2 decimals (1.234,56). It omits the
   *  currency symbol because the column header carries the € sign. */
  protected offerValueText(pi: number, oi: number): string {
    const v = this.positions[pi]?.offers[oi]?.value ?? null;
    if (v === null) return '';
    if (this.editing && this.editing.pi === pi && this.editing.oi === oi) {
      return String(v);
    }
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(v);
  }

  /** Parse a localized money input into a `number`. It accepts "1.234,56" and
   *  "1234.56". An empty or invalid input gives `null`. */
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

  /** Toggle the comparison-offer opt-out. When on, drop the blank offers and keep one
   *  offer input marked as preferred. When off, pad the offers back up to `minOffers`. */
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
