import { ChangeDetectionStrategy, Component, computed, inject, input, model, output } from '@angular/core';
import type { GuestsMode, JoinLink } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SegmentedComponent, SwitchComponent, type SegmentedOption } from '@stupa-makers/ui-kit';
import { JoinLinkComponent } from './join-link.component';

/**
 * The public participation of a meeting (#17), for "Sitzung anlegen" (step 2) and
 * "Sitzung bearbeiten": the switch "Öffentliche Teilnahme (QR)", then the choice
 * "Gäste dürfen abstimmen" / "Gäste schauen nur zu" (two equal segments with one line
 * each), then the join link with its QR code, or, before the create, where it will be.
 */
@Component({
  selector: 'app-public-join-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, SwitchComponent, SegmentedComponent, NoteComponent, JoinLinkComponent],
  templateUrl: './public-join-settings.component.html',
  styleUrl: './public-join-settings.component.scss',
})
export class PublicJoinSettingsComponent {
  private readonly i18n = inject(I18nService);

  readonly publicJoin = model(false);
  readonly guestsMode = model<GuestsMode>('vote');
  readonly disabled = input(false);
  /** The join link of an existing meeting, or `null` (create dialog, not loaded yet). */
  readonly link = input<JoinLink | null>(null);
  /** The create dialog: the link exists only after the create. */
  readonly creating = input(false);
  readonly rotating = input(false);
  readonly rotate = output<void>();

  protected readonly modes = computed<SegmentedOption[]>(() => [
    { value: 'vote', label: this.i18n.translate('guests.mode.vote') },
    { value: 'watch', label: this.i18n.translate('guests.mode.watch') },
  ]);

  setMode(value: string | null): void {
    if (value === 'vote' || value === 'watch') this.guestsMode.set(value);
  }
}
