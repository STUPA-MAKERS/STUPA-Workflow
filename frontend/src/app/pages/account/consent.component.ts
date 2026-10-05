import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiClient } from '@core/api/api-client.service';
import type { ConsentRequest } from '@core/api/models';
import { LOCATION } from '@core/browser/location.token';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, CheckboxComponent, IconComponent } from '@stupa-makers/ui-kit';
import { scopeDesc, scopeLabel } from './scope-labels';

/**
 * OAuth consent page (board Konto-OAuth-Einwilligung), step two of the MCP login.
 *
 * The page names the client (`clientId`) and lists EVERY scope that the client asks for,
 * with its label and description; all start ticked. A scope the person does not hold
 * says so: the agent does not get it. The lifetimes come from the server (no "never",
 * every token expires), the default one starts chosen.
 *
 * Without `mcp.use` (`canUseMcp` false) the page shows the error line instead of the
 * choices, and "Erlauben" stays disabled; "Ablehnen" still reports the denial to the
 * client.
 *
 * The form post is the same as before: `POST /oauth/consent` with `approve`, the chosen
 * `scopes` and the `lifetime`. The answer is a loopback redirect URL to follow.
 */
@Component({
  selector: 'app-oauth-consent',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CheckboxComponent,
    FormsModule,
    IconComponent,
    NoteComponent,
    SkeletonComponent,
    TranslatePipe,
  ],
  templateUrl: './consent.component.html',
  styleUrl: './consent.component.scss',
})
export class OAuthConsentComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly location = inject(LOCATION);

  readonly req = signal<ConsentRequest | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly submitting = signal(false);

  /** Selected scopes, keyed by scope key. Every requested scope starts on. */
  readonly selected = signal<Record<string, boolean>>({});
  readonly lifetime = signal<string>('30d');

  readonly anySelected = computed(() => Object.values(this.selected()).some(Boolean));

  constructor() {
    this.api.consentRequest().subscribe({
      next: (r) => {
        this.req.set(r);
        this.selected.set(Object.fromEntries(r.requestedScopes.map((s) => [s.key, true])));
        this.lifetime.set(r.defaultLifetime);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('account.consent.error');
        this.loading.set(false);
      },
    });
  }

  /** The label of a scope; an unknown scope shows its key. */
  scopeLabel(key: string): string {
    return scopeLabel(this.i18n, key);
  }

  /** The description of a scope, or '' for an unknown scope. */
  scopeDesc(key: string): string {
    return scopeDesc(this.i18n, key);
  }

  /** The label of a lifetime key; an unknown key shows itself. */
  lifetimeLabel(value: string): string {
    const key = `account.lifetime.${value}`;
    const text = this.i18n.translate(key as TranslationKey);
    return text === key ? value : text;
  }

  setScope(key: string, on: boolean): void {
    this.selected.update((s) => ({ ...s, [key]: on }));
  }

  setLifetime(value: string): void {
    this.lifetime.set(value);
  }

  approve(): void {
    const scopes = Object.entries(this.selected())
      .filter(([, on]) => on)
      .map(([k]) => k);
    this.submit(true, scopes);
  }

  deny(): void {
    this.submit(false, []);
  }

  private submit(approve: boolean, scopes: string[]): void {
    this.submitting.set(true);
    this.error.set(null);
    this.api.submitConsent({ approve, scopes, lifetime: this.lifetime() }).subscribe({
      next: (r) => {
        // Go back to the local loopback callback of the MCP client. The URL can carry error=…
        this.location.assign(r.redirect);
      },
      error: () => {
        this.error.set('account.consent.error');
        this.submitting.set(false);
      },
    });
  }
}
