import { ChangeDetectionStrategy, Component, computed, viewChild } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FabComponent, PageHeaderComponent } from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { GuestSettingsComponent } from './guest-settings/guest-settings.component';
import { MeetingWindowSettingsComponent } from './meeting-window/meeting-window.component';

/**
 * The admin page "Fristen & Fenster" (`admin.deadlines`).
 *
 * `app-meeting-window-settings` holds the open window of meetings (the earliest open and
 * the early open that asks first). `app-guest-settings` holds the settings for
 * applications without an account: the discard window and the lifetime of the
 * personal link. While one of the two sections has changes, the floating button
 * "Speichern" saves them.
 */
@Component({
  selector: 'app-admin-deadlines',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FabComponent,
    TranslatePipe,
    PageHeaderComponent,
    BreadcrumbsComponent,
    GuestSettingsComponent,
    MeetingWindowSettingsComponent,
  ],
  templateUrl: './deadlines.component.html',
  styleUrl: './deadlines.component.scss',
})
export class AdminDeadlinesComponent {
  private readonly meetingWindow = viewChild(MeetingWindowSettingsComponent);
  private readonly guestSettings = viewChild(GuestSettingsComponent);
  /** The settings sections that have changes that are not saved. */
  private readonly dirtySections = computed(() =>
    [this.meetingWindow(), this.guestSettings()].filter((s) => !!s && s.dirty()),
  );
  protected readonly settingsDirty = computed(() => this.dirtySections().length > 0);
  protected readonly settingsSaving = computed(() => this.dirtySections().some((s) => s?.saving()));
  protected readonly settingsValid = computed(() => this.dirtySections().every((s) => s?.valid()));

  /** "Speichern": send every settings section that has changes. */
  protected saveSettings(): void {
    for (const s of this.dirtySections()) s?.save();
  }
}
