import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ButtonComponent, SelectComponent, type SelectOption } from '@stupa-makers/ui-kit';
import {
  ACTION_TYPES,
  NOTIFY_RECIPIENT_KINDS,
  type ActionDef,
  type Guard,
  type NotifyRecipient,
  type TransitionDef,
} from '../admin.models';
import { GuardEditorComponent } from './guard-editor.component';
import { actionParamOf, recipientNeedsRef, recipientsOf } from './flow-guard.util';

/** Guard + actions pane of the selected transition (below the graph). */
@Component({
  selector: 'app-transition-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, SelectComponent, GuardEditorComponent],
  templateUrl: './transition-detail.component.html',
  styleUrl: './transition-detail.component.scss',
})
export class TransitionDetailComponent {
  private readonly i18n = inject(I18nService);

  readonly transition = input.required<TransitionDef>();
  readonly roleOptions = input.required<SelectOption[]>();
  readonly gremiumOptions = input.required<SelectOption[]>();
  readonly webhookOptions = input.required<SelectOption[]>();

  readonly guardChange = output<Guard | null>();
  readonly actionAdd = output<string>();
  readonly actionRemove = output<number>();
  readonly actionParamChange = output<{ ai: number; key: string; value: string }>();
  readonly recipientAdd = output<number>();
  readonly recipientRemove = output<{ ai: number; ri: number }>();
  readonly recipientKindChange = output<{ ai: number; ri: number; kind: string }>();
  readonly recipientRefChange = output<{ ai: number; ri: number; ref: string }>();

  protected actionOptions(): SelectOption[] {
    return ACTION_TYPES.map((a) => ({
      value: a,
      label: this.i18n.translate(`admin.flow.actionType.${a}` as TranslationKey),
    }));
  }

  protected actionLabel(type: string): string {
    return this.i18n.translate(`admin.flow.actionType.${type}` as TranslationKey);
  }

  protected recipientKindOptions(): SelectOption[] {
    return NOTIFY_RECIPIENT_KINDS.map((k) => ({
      value: k,
      label: this.i18n.translate(`admin.flow.recipientKind.${k}` as TranslationKey),
    }));
  }

  protected recipientsOf(act: ActionDef): NotifyRecipient[] {
    return recipientsOf(act);
  }

  protected actionParam(act: ActionDef, key: string): string {
    return actionParamOf(act, key);
  }

  protected recipientNeedsRef(kind: string): boolean {
    return recipientNeedsRef(kind);
  }
}
