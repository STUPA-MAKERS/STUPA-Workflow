import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiClient } from '@core/api/api-client.service';
import type { Profile } from '@core/api/models';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe, formatMoment } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  AvatarComponent,
  IconComponent,
  NoteComponent,
  PageHeaderComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from '../../layout/breadcrumbs.component';

/** Where a person changes the image of the avatar (spec 001122). */
export const GRAVATAR_PROFILE_URL = 'https://gravatar.com/profile';

/** The OIDC claims that hold a time in seconds since 1970 (OIDC Core 5.1). */
const TIME_CLAIMS: ReadonlySet<string> = new Set(['updated_at']);

/** The order of the known claims; any other claim follows by name, `sub` comes last. */
const CLAIM_ORDER: readonly string[] = [
  'name',
  'preferred_username',
  'given_name',
  'middle_name',
  'family_name',
  'nickname',
  'email',
  'email_verified',
  'groups',
];

function claimRank(key: string): number {
  if (key === 'sub') return Number.MAX_SAFE_INTEGER;
  const i = CLAIM_ORDER.indexOf(key);
  return i === -1 ? CLAIM_ORDER.length : i;
}

/** One row of the page: the label of the claim and its value as text. */
export interface ProfileRow {
  readonly key: string;
  readonly label: string;
  readonly value: string;
}

/**
 * Account page "Profil" (`/account/profile`, spec 001120).
 *
 * The page shows, read only, what the platform has from the SSO about the signed-in
 * person: one row per claim of the login, without the claims of the token itself (spec
 * 001121), and the last login. A claim that the catalog knows shows its label, any other
 * claim its name.
 *
 * The avatar links to the Gravatar profile in a new tab, because the image comes from
 * there. A pointer shows the link symbol on hover; a touch screen shows it always. When
 * the admin switched Gravatar off, the avatar shows the initials and has no link (spec
 * 001122).
 */
@Component({
  selector: 'app-account-profile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    AvatarComponent,
    BreadcrumbsComponent,
    IconComponent,
    LocalizedDatePipe,
    NoteComponent,
    PageHeaderComponent,
    SkeletonComponent,
    TranslatePipe,
  ],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss',
})
export class AccountProfileComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly branding = inject(BrandingService);

  protected readonly gravatarUrl = GRAVATAR_PROFILE_URL;
  readonly profile = signal<Profile | null>(null);
  readonly loading = signal(true);
  readonly error = signal<TranslationKey | null>(null);

  /** The avatar links to Gravatar only while the app shows Gravatar images. */
  readonly gravatarLink = computed(
    () => this.branding.loaded() && this.branding.gravatarEnabled(),
  );

  /** The name of the head: the display name, else the e-mail address. */
  readonly name = computed(() => {
    const p = this.profile();
    return p?.displayName || p?.email || '—';
  });

  readonly rows = computed<ProfileRow[]>(() =>
    [...(this.profile()?.claims ?? [])]
      .sort((a, b) => claimRank(a.key) - claimRank(b.key) || a.key.localeCompare(b.key))
      .map((c) => ({
        key: c.key,
        label: this.label(c.key),
        value: this.text(c.key, c.value),
      })),
  );

  constructor() {
    this.api.getMyProfile().subscribe({
      next: (p) => {
        this.profile.set(p);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('account.profile.error');
        this.loading.set(false);
      },
    });
  }

  private label(key: string): string {
    const k = `account.profile.claim.${key}`;
    const label = this.i18n.translate(k as TranslationKey);
    return label === k ? key : label;
  }

  /** The value as text: a list joined, a flag as Ja/Nein, a time as a date, else JSON. */
  private text(key: string, value: unknown): string {
    if (typeof value === 'string') return value;
    if (typeof value === 'boolean') return this.i18n.translate(value ? 'common.yes' : 'common.no');
    if (typeof value === 'number' && TIME_CLAIMS.has(key)) {
      return formatMoment(value * 1000, this.i18n.formatLocale(), 'medium');
    }
    if (Array.isArray(value)) {
      return value.length === 0 ? '—' : value.map((v) => (typeof v === 'string' ? v : JSON.stringify(v))).join(', ');
    }
    return JSON.stringify(value);
  }
}
