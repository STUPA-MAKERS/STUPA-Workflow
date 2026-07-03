import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import { LOCATION } from '@core/browser/location.token';
import type { ConsentRequest } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * OAuth consent: after login the user picks which scopes and which token lifetime
 * (including "never expires") the agent/MCP receives before the code is minted.
 * Approve/Deny return a loopback redirect URL to forward to.
 */
@Component({
  selector: 'app-oauth-consent',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent],
  templateUrl: './consent.component.html',
  styleUrl: './consent.component.scss',
})
export class OAuthConsentComponent {
  private readonly api = inject(ApiClient);
  private readonly location = inject(LOCATION);

  readonly req = signal<ConsentRequest | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly submitting = signal(false);

  /** Selected scopes (key → on/off); initially all requested ones. */
  readonly selected = signal<Record<string, boolean>>({});
  readonly lifetime = signal<string>('30d');

  /** i18n key for a lifetime preset (account.lifetime.<key>). */
  lifetimeKey(value: string): TranslationKey {
    return `account.lifetime.${value}` as TranslationKey;
  }

  scopeLabelKey(key: string): TranslationKey {
    return `account.scope.${key.replace(':', '_')}.label` as TranslationKey;
  }

  scopeDescKey(key: string): TranslationKey {
    return `account.scope.${key.replace(':', '_')}.desc` as TranslationKey;
  }

  readonly anySelected = computed(() =>
    Object.values(this.selected()).some(Boolean),
  );

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

  toggle(key: string): void {
    this.selected.update((s) => ({ ...s, [key]: !s[key] }));
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
    this.api.submitConsent({ approve, scopes, lifetime: this.lifetime() }).subscribe({
      next: (r) => {
        // Back to the MCP client's local loopback callback (or with error=…).
        this.location.assign(r.redirect);
      },
      error: () => {
        this.error.set('account.consent.error');
        this.submitting.set(false);
      },
    });
  }
}
