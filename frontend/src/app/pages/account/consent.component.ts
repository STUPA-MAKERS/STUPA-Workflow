import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { ConsentRequest } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { IconComponent } from '@shared/ui';

/**
 * OAuth-Consent (#MCP): nach dem Login wählt der Nutzer hier, WELCHE Scopes und WELCHE
 * Token-Lebensdauer (inkl. »läuft nie ab«) der Agent/MCP erhält, bevor der Code gemintet
 * wird. Approve/Deny liefern eine Loopback-Redirect-URL, zu der weitergeleitet wird.
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

  readonly req = signal<ConsentRequest | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly submitting = signal(false);

  /** Ausgewählte Scopes (Key → an/aus); initial alle angefragten. */
  readonly selected = signal<Record<string, boolean>>({});
  readonly lifetime = signal<string>('30d');

  /** i18n-Key für ein Lifetime-Preset (account.lifetime.<key>). */
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
        // Zurück zum lokalen Loopback-Callback des MCP-Clients (bzw. mit error=…).
        window.location.assign(r.redirect);
      },
      error: () => {
        this.error.set('account.consent.error');
        this.submitting.set(false);
      },
    });
  }
}
