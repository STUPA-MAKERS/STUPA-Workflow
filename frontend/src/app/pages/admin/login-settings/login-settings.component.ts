import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import { FabComponent, InputComponent, PageHeaderComponent } from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../../layout/breadcrumbs.component';
import { AdminApiService } from '../admin-api.service';
import { type LoginSettings, MAX_SESSION_DAYS } from '../admin.models';

/** The edit state. The fields hold the text of the inputs, so a bad entry stays visible. */
interface Draft {
  web: string;
  pwa: string;
}

/** The body of the PUT. */
type LoginSettingsBody = Pick<LoginSettings, 'webSessionDays' | 'pwaSessionDays'>;

/** A whole number in [1, MAX_SESSION_DAYS], else `null`. */
function sessionDays(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= MAX_SESSION_DAYS ? n : null;
}

function draftOf(s: LoginSettings): Draft {
  return { web: String(s.webSessionDays), pwa: String(s.pwaSessionDays) };
}

/**
 * "Anmeldung" (permission `admin.users`): the lifetimes of an SSO login.
 *
 * Two settings of `GET/PUT /admin/login-settings`, each a whole number of days from 1
 * to 400:
 *
 * - `webSessionDays`: a login in a browser tab.
 * - `pwaSessionDays`: a login in the installed app. The app tells the server at the
 *   login start with `?client=pwa` (`AuthService.login`).
 *
 * A login stays valid for that many days after its last use. A change applies to every
 * session at its next renewal. The upper bound is 400, because browsers delete a cookie
 * after 400 days at the latest.
 *
 * The page shows the form only with `admin.users` and not after a 403, so a person
 * without the right never sees a form that the server refuses.
 */
@Component({
  selector: 'app-login-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    PageHeaderComponent,
    BreadcrumbsComponent,
    FabComponent,
    InputComponent,
    LoadStateComponent,
  ],
  templateUrl: './login-settings.component.html',
  styleUrl: './login-settings.component.scss',
})
export class LoginSettingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  protected readonly form: SettingsForm<LoginSettings, Draft> = settingsForm<LoginSettings, Draft, LoginSettingsBody>({
    allowed: () => this.auth.can('admin.users'),
    load: () => this.api.getLoginSettings(),
    put: (body) => this.api.putLoginSettings(body),
    draftOf,
    initial: { web: '', pwa: '' },
    body: () => this.body(),
    unchanged: (b, s) => b.webSessionDays === s.webSessionDays && b.pwaSessionDays === s.pwaSessionDays,
  });
  protected readonly saving = this.form.saving;
  /** The stored values; the draft compares against them. */
  protected readonly saved = this.form.saved;
  protected readonly draft = this.form.draft;

  protected readonly web = computed(() => sessionDays(this.draft().web));
  protected readonly pwa = computed(() => sessionDays(this.draft().pwa));
  protected readonly webError = computed(() => (this.web() === null ? this.rangeText() : ''));
  protected readonly pwaError = computed(() => (this.pwa() === null ? this.rangeText() : ''));

  /** The body of the PUT, or `null` while a field is invalid. */
  protected readonly body = computed<LoginSettingsBody | null>(() => {
    const web = this.web();
    const pwa = this.pwa();
    if (web === null || pwa === null) return null;
    return { webSessionDays: web, pwaSessionDays: pwa };
  });

  protected readonly dirty = this.form.dirty;
  protected readonly canSave = this.form.canSave;

  private rangeText(): string {
    return this.i18n.translate('admin.loginSettings.range', { max: MAX_SESSION_DAYS });
  }

  protected patch(change: Partial<Draft>): void {
    this.form.patch(change);
  }

  protected save(): void {
    this.form.save();
  }
}
