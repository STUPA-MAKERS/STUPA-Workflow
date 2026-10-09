import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import type { ApplicationDecision } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldGroupComponent } from '@shared/ui/field-group/field-group.component';
import { FieldRowComponent } from '@shared/ui/field-group/field-group.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { formatDiff, formatMoney } from './decision.util';

/**
 * The section "Beschluss" (F1): the decision on an application.
 *
 * It shows the requested amount (struck through when the approved one deviates), the
 * approved amount with the difference, the numbered conditions and where the decision
 * came from. The team view links the vote. The applicant view (`applicant`) has no
 * meeting, no agenda number and no vote link, and adds a note that only the approved
 * amount is funded.
 */
@Component({
  selector: 'app-decision-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    LocalizedDatePipe,
    FieldGroupComponent,
    FieldRowComponent,
    NoteComponent,
  ],
  templateUrl: './decision-section.component.html',
  styleUrl: './decision-section.component.scss',
})
export class DecisionSectionComponent {
  private readonly i18n = inject(I18nService);

  readonly decision = input.required<ApplicationDecision>();
  readonly currency = input<string | null>('EUR');
  /** The applicant page: no vote link and a note about the funded amount. */
  readonly applicant = input(false);
  /** The id of the heading, unique on the page. */
  readonly headingId = input('decision-title');

  /** The decision deviates: another amount or at least one condition. */
  readonly deviates = computed(
    () => this.decision().amountDeviates || this.decision().conditions.length > 0,
  );

  readonly requested = computed(() =>
    formatMoney(this.decision().requestedAmount, this.i18n.formatLocale(), this.currency()),
  );

  /** The approved amount; "as requested" shows the requested amount. */
  readonly approved = computed(() => {
    const d = this.decision();
    return formatMoney(d.approvedAmount ?? d.requestedAmount, this.i18n.formatLocale(), this.currency());
  });

  readonly diff = computed(() => {
    const d = this.decision();
    return d.amountDeviates
      ? formatDiff(d.requestedAmount, d.approvedAmount, this.i18n.formatLocale(), this.currency())
      : '';
  });

  /** "Studierendenparlament, 34. Sitzung, TOP 6" (the applicant view: the Gremium only). */
  readonly source = computed(() => {
    const d = this.decision();
    const parts: string[] = [];
    if (d.gremiumName) parts.push(d.gremiumName);
    if (!this.applicant()) {
      if (d.meetingTitle) parts.push(d.meetingTitle);
      if (d.agendaPosition !== null) {
        parts.push(this.i18n.translate('decision.sourceTop', { n: d.agendaPosition }));
      }
    }
    return parts.join(', ');
  });

  /** The note of the applicant view, or `''` without a deviation. */
  readonly applicantNote = computed(() => {
    const d = this.decision();
    if (d.amountDeviates) {
      return this.i18n.translate('decision.applicantNote', { amount: this.approved() });
    }
    return d.conditions.length ? this.i18n.translate('decision.applicantNoteConditions') : '';
  });
}
